#!/usr/bin/env python3
"""Rebuild paired tables and figures from an immutable Stage 1 run (no optimization)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
    "qft": "QFT", "toffoli_ladder": "Toffoli ladder", "phase": "Phase circuits",
    "pauli": "Repeated Pauli rotations", "clifford_t": "Random Clifford+T",
}
METRICS = ["t_count", "two_q_count", "depth", "non_clifford_rotations", "total_gates"]
METHODS = ["Original", "Gate-only", "ZX"]
PREFIXES = {"Original": "original", "Gate-only": "gate", "ZX": "zx"}


def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def reduction(base, candidate):
    return None if base is None or candidate is None or base == 0 else 100 * (base-candidate)/base


def describe(values):
    values = [x for x in values if x is not None]
    return {"n": len(values), "median": median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def category(differences):
    if any(x is None for x in differences):
        return "unavailable"
    if all(x == 0 for x in differences):
        return "unchanged"
    if all(x <= 0 for x in differences):
        return "improvement"
    if all(x >= 0 for x in differences):
        return "regression"
    return "tradeoff"


def fmt(value, digits=None):
    if value is None:
        return "N/A"
    return str(value) if digits is None else f"{value:.{digits}f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    run = ROOT / "runs" / args.run_id
    out = ROOT / "analysis" / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((run / "metadata.json").read_text())
    if metadata.get("state") != "completed" or metadata.get("mode") != "stage1_full":
        raise ValueError("Only a completed full Stage 1 run can be summarized here")
    rows = list(csv.DictReader((run / "results.csv").open()))
    grouped = defaultdict(dict)
    for row in rows:
        if row["method"] in grouped[row["circuit_id"]]:
            raise ValueError("Duplicate circuit/method row")
        for key in METRICS + ["qubits", "seed", "repetitions", "timed_repeats"]:
            row[key] = int(row[key]) if row[key] else None
        for key in ["optimization_ms_median", "optimization_ms_min", "optimization_ms_max", "verification_max_abs_residual"]:
            row[key] = float(row[key]) if row[key] else None
        grouped[row["circuit_id"]][row["method"]] = row
    if len(rows) != metadata["expected_rows"] or len(grouped) != metadata["expected_inputs"]:
        raise ValueError("Incomplete run")
    pairs = []
    for cid, methods in grouped.items():
        if set(methods) != set(METHODS):
            raise ValueError(f"Missing method: {cid}")
        b, z = methods["Gate-only"], methods["ZX"]
        valid = all(methods[m]["verification_status"] == "passed" for m in METHODS)
        p = {"circuit_id": cid, "family": b["family"], "qubits": b["qubits"], "seed": b["seed"],
             "repetitions": b["repetitions"], "all_three_verified": valid,
             "run_id": args.run_id, "code_commit": metadata["code_commit"]}
        for method in METHODS:
            r, prefix = methods[method], PREFIXES[method]
            for key in METRICS + ["optimization_ms_median", "optimization_ms_min", "optimization_ms_max", "timed_repeats", "timing_status", "verification_status"]:
                p[f"{prefix}_{key}"] = r[key]
        for key in METRICS:
            p[f"delta_{key}_zx_minus_gate"] = z[key]-b[key] if valid and z[key] is not None and b[key] is not None else None
            p[f"{key}_reduction_pct_vs_gate"] = reduction(b[key], z[key]) if valid else None
            p[f"{key}_reduction_pct_vs_original"] = reduction(methods["Original"][key], z[key]) if valid else None
        relevant = ["two_q_count", "depth"] if b["family"] == "qft" else ["t_count", "two_q_count"]
        p["category_metrics"] = "+".join(relevant)
        p["effect_category"] = category([p[f"delta_{key}_zx_minus_gate"] for key in relevant]) if valid else "unavailable"
        p["t_nonincrease_and_2q_reduction"] = (z["t_count"] <= b["t_count"] and z["two_q_count"] < b["two_q_count"]) if valid and b["t_count"] is not None else None
        p["runtime_ratio_zx_to_gate"] = z["optimization_ms_median"]/b["optimization_ms_median"] if z["optimization_ms_median"] and b["optimization_ms_median"] else None
        outputs = json.loads((run / "outputs" / f"{cid}.json").read_text())
        pre = outputs.get("ZX-before-cleanup", {}).get("metrics", {})
        for key in METRICS:
            p[f"zx_before_cleanup_{key}"] = pre.get(key)
        pairs.append(p)
    save_csv(out / "paired_results.csv", pairs)
    families = []
    for family, name in FAMILIES.items():
        subset = [p for p in pairs if p["family"] == family]
        counts = Counter(p["effect_category"] for p in subset)
        f = {"family": family, "family_label": name, "inputs": len(subset),
             "verified_pairs": sum(p["all_three_verified"] for p in subset),
             "category_metrics": subset[0]["category_metrics"],
             **{k: counts[k] for k in ["improvement", "tradeoff", "unchanged", "regression", "unavailable"]},
             "t_nonincrease_and_2q_reduction": sum(p["t_nonincrease_and_2q_reduction"] is True for p in subset) if family != "qft" else None}
        for key in ["t_count", "two_q_count", "depth"]:
            for stat, value in describe([p[f"{key}_reduction_pct_vs_gate"] for p in subset]).items():
                f[f"{key}_reduction_pct_{stat}"] = value
        for stat, value in describe([p["runtime_ratio_zx_to_gate"] for p in subset]).items():
            f[f"runtime_ratio_{stat}"] = value
        families.append(f)
    save_csv(out / "family_summary.csv", families)
    timings = json.loads((run / "timings.json").read_text())
    flat_times = [r for records in timings.values() for r in records if r.get("phase") == "timed"]
    component_rows = []
    for cid, records in timings.items():
        for method in ["Gate-only", "ZX"]:
            ts = [r for r in records if r.get("phase") == "timed" and r["method"] == method and r["status"] == "passed"]
            c = {"circuit_id": cid, "method": method, "timed_repeats": len(ts)}
            for key in ["input_copy_ms", "conversion_ms", "simplification_ms", "graph_copy_ms", "extraction_ms", "pre_cleanup_normalization_ms", "cleanup_ms", "final_normalization_ms", "total_ms"]:
                c[key + "_median"] = median(r[key] for r in ts if key in r) if any(key in r for r in ts) else None
            component_rows.append(c)
    save_csv(out / "runtime_components.csv", component_rows)
    verification = json.loads((run / "verification.json").read_text())
    checks = [v for x in verification.values() for v in x.get("methods", {}).values()]
    ct = [p for p in pairs if p["family"] != "qft"]
    summary = {
        "run_id": args.run_id, "code_commit": metadata["code_commit"], "experiment_started_jst": metadata["started_jst"],
        "results_sha256": sha256((run / "results.csv").read_bytes()).hexdigest(),
        "row_count": len(rows), "input_count": len(pairs), "row_status_counts": dict(Counter(r["status"] for r in rows)),
        "ct_input_count": len(ct), "ct_category_counts": dict(Counter(p["effect_category"] for p in ct)),
        "qft_category_counts": dict(Counter(p["effect_category"] for p in pairs if p["family"] == "qft")),
        "t_nonincrease_and_2q_reduction_count": sum(p["t_nonincrease_and_2q_reduction"] is True for p in ct),
        "t_nonincrease_and_2q_reduction_ids": [p["circuit_id"] for p in ct if p["t_nonincrease_and_2q_reduction"] is True],
        "ct_t_increase_count": sum(p["delta_t_count_zx_minus_gate"] > 0 for p in ct if p["all_three_verified"]),
        "timed_call_count": len(flat_times), "timed_status_counts": dict(Counter(t["status"] for t in flat_times)),
        "timed_hash_matches": sum(t.get("output_validation") == "hash_matches_verified_output" for t in flat_times),
        "timed_distinct_output_count": sum(t.get("output_validation") != "hash_matches_verified_output" for t in flat_times),
        "all_stage_check_count": len(checks), "all_stage_check_status_counts": dict(Counter(c["status"] for c in checks)),
        "max_abs_residual_main_rows": max(r["verification_max_abs_residual"] for r in rows if r["verification_max_abs_residual"] is not None),
        "max_abs_residual_including_pre_cleanup": max(c["max_abs_residual"] for c in checks if c.get("max_abs_residual") is not None),
        "runtime_ratio_zx_to_gate": describe([p["runtime_ratio_zx_to_gate"] for p in pairs]),
        "by_qubits": {str(n): {"inputs": sum(p["qubits"] == n for p in pairs),
                               "twoq_increased": sum(p["qubits"] == n and p["delta_two_q_count_zx_minus_gate"] is not None and p["delta_two_q_count_zx_minus_gate"] > 0 for p in pairs),
                               "twoq_decreased": sum(p["qubits"] == n and p["delta_two_q_count_zx_minus_gate"] is not None and p["delta_two_q_count_zx_minus_gate"] < 0 for p in pairs)} for n in [4, 6, 8]},
        "families": families,
        "interpretation": "Exploratory inputs; percentages are per-input ratios summarized within family, not ratios of summed counts. Positive reduction means fewer gates. QFT T-count is not applicable. No confidence intervals are claimed."
    }
    save_json(out / "summary.json", summary)
    lines = ["# Stage 1 — Complete Results", "", f"Run: `{args.run_id}`  ", f"Code: `{metadata['code_commit']}`", "",
             "All 99 method rows are retained below. Optimization time is the median of 10 timed calls in milliseconds; Original is N/A. T-count for QFT is N/A. Positive reduction percentages mean improvement. Categories refer to T + 2Q, except QFT (2Q + depth).", "",
             "| Circuit ID | Method | T-count | 2Q count | Depth | Time (ms) | Verification |", "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for r in rows:
        lines.append(f"| {r['circuit_id']} | {r['method']} | {fmt(r['t_count'])} | {fmt(r['two_q_count'])} | {fmt(r['depth'])} | {fmt(r['optimization_ms_median'],3)} | {r['verification_status']} |")
    lines += ["", "## Paired comparison against Gate-only", "", "| Circuit ID | T reduction (%) | 2Q reduction (%) | Depth reduction (%) | ZX / Gate time | Category |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for p in pairs:
        lines.append(f"| {p['circuit_id']} | {fmt(p['t_count_reduction_pct_vs_gate'],1)} | {fmt(p['two_q_count_reduction_pct_vs_gate'],1)} | {fmt(p['depth_reduction_pct_vs_gate'],1)} | {fmt(p['runtime_ratio_zx_to_gate'],2)} | {p['effect_category']} |")
    lines += ["", "Data: [paired CSV](paired_results.csv), [family summary](family_summary.csv), [timing components](runtime_components.csv), [raw rows](../../runs/" + args.run_id + "/results.csv).", ""]
    (out / "all_results.md").write_text("\n".join(lines))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none", "svg.hashsalt": args.run_id})
    colors = {"toffoli_ladder": "#c05621", "phase": "#237a57", "pauli": "#7455ad", "clifford_t": "#176b9b"}
    markers = {4: "o", 6: "s", 8: "^"}
    fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
    ax.axhline(0, color="#777777", lw=1)
    ax.axvline(0, color="#777777", lw=1)
    for fam in colors:
        first = True
        for n in [4, 6, 8]:
            ps = [p for p in ct if p["family"] == fam and p["qubits"] == n and p["all_three_verified"]]
            ax.scatter([p["t_count_reduction_pct_vs_gate"] for p in ps], [p["two_q_count_reduction_pct_vs_gate"] for p in ps],
                       s=65, alpha=.85, edgecolor="white", linewidth=.5, color=colors[fam], marker=markers[n], label=FAMILIES[fam] if first else None)
            first = False
    for cid, shift in {"phase_4q_s0": (-90,-22), "tof_ladder_6q": (8,8), "pauli_4q_r8": (12,7)}.items():
        p = next(p for p in pairs if p["circuit_id"] == cid)
        ax.annotate(cid, (p["t_count_reduction_pct_vs_gate"],p["two_q_count_reduction_pct_vs_gate"]), xytext=shift, textcoords="offset points", fontsize=9)
    ax.set(xlabel="T-count reduction vs Gate-only (%)", ylabel="2Q reduction vs Gate-only (%)",
           title="Circuit-dependent effects of the fixed PyZX pipeline\n30 Clifford+T inputs; positive values mean reduction", xlim=(-5,70), ylim=(-120,90))
    ax.grid(alpha=.2)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
    ax.text(.98,.02,"Marker: circle = 4q; square = 6q; triangle = 8q\nOverlapping points are retained in paired_results.csv",transform=ax.transAxes,ha="right",va="bottom",fontsize=8,color="#444444")
    fig.savefig(out / "two_q_vs_t.svg", metadata={"Date": None})
    fig.savefig(out / "two_q_vs_t.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(10,4.5),layout="constrained")
    ps = [p for p in pairs if p["family"] == "qft" and p["all_three_verified"]]
    for ax,key,label in zip(axes,["two_q_count","depth"],["Logical 2Q gate count","Logical dependency depth"]):
        x=np.arange(len(ps)); width=.25
        for j,method in enumerate(METHODS):
            vals=[p[f"{PREFIXES[method]}_{key}"] for p in ps]
            bars=ax.bar(x+(j-1)*width,vals,width,label=method,color=["#b5bbc5","#176b9b","#c05621"][j])
            ax.bar_label(bars,padding=3,fontsize=8)
        ax.set_xticks(x,[str(p["qubits"])+" qubits" for p in ps])
        ax.set_ylabel(label);ax.set_ylim(0,max(p[f"zx_{key}"] for p in ps)*1.18)
        ax.grid(axis="y",alpha=.2);ax.set_axisbelow(True)
    axes[0].legend(fontsize=9)
    fig.suptitle("QFT with explicit final SWAPs: general angles, T-count N/A")
    fig.savefig(out / "qft_metrics.svg", metadata={"Date": None})
    fig.savefig(out / "qft_metrics.png", dpi=160)
    plt.close(fig)
    print(json.dumps({k:v for k,v in summary.items() if k != "families"},indent=2))


if __name__ == "__main__":
    main()
