#!/usr/bin/env python3
"""Rebuild Stage 2 tables, predeclared decisions and figures; never optimize.

Usage: python analysis/summarize_stage2.py RUN_ID
The H1--H6 rules below are fixed before inspecting Stage 2 outcomes. Their
thresholds are descriptive replication criteria, not statistical significance.
Raw JSON may live in runs/RUN_ID/artifacts.zip (members relative to the run).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median
from zipfile import ZipFile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("Original", "Gate-only", "ZX")
PREFIXES = {"Original": "original", "Gate-only": "gate", "ZX": "zx"}
METRICS = ("t_count", "two_q_count", "depth", "non_clifford_rotations", "total_gates")
SEEDS = tuple(range(100, 110))
PRESELECTED = (
    "stage2_phase_4q_L80_s100", "stage2_phase_8q_L80_s100",
    "stage2_tof_ladder_5q", "stage2_qft_5q",
)
RULES = {
    "H1": "At 4q/L80, >=8/10 verified T-nonincreasing strict-2Q wins and median g2>0; AND at 8q/L80, >=8/10 strict-2Q increases and median g2<0.",
    "H2": "Both Toffoli ladders (5q,7q) have strict T reduction AND strict 2Q increase.",
    "H3": "Both QFT inputs (5q,7q) have strict 2Q increase AND strict depth increase.",
    "H4": "At 8q, g2(L160)-g2(L80)>0 in >=8/10 matched seeds AND median paired difference>0.",
    "H5": "S2(reuse)-S2(unique)>0 in >=8/10 matched seeds AND median paired difference>0; T nonincrease is reported separately.",
    "H6": "(ZX2Q-Gate2Q)_cascade > (ZX2Q-Gate2Q)_disjoint for the two fixed 6q inputs.",
}


def expected_ids():
    ids = [f"stage2_phase_{n}q_L80_s{s}" for n in (4, 8) for s in SEEDS]
    ids += [f"stage2_tof_ladder_{n}q" for n in (5, 7)]
    ids += [f"stage2_qft_{n}q" for n in (5, 7)]
    ids += [f"stage2_phase_{n}q_L160_s{s}" for n in (4, 8) for s in SEEDS]
    ids += [f"stage2_parity6_{c}_s{s}" for s in SEEDS for c in ("reuse", "unique")]
    ids += ["stage2_tof6_disjoint2", "stage2_tof6_cascade2"]
    return ids


class RunReader:
    def __init__(self, run):
        self.run = run
        self.archive = None
        self.missing = []

    def json(self, relative, default=None):
        path = self.run / relative
        if path.exists():
            return json.loads(path.read_text())
        archive_path = self.run / "artifacts.zip"
        if archive_path.exists():
            if self.archive is None:
                self.archive = ZipFile(archive_path)
            try:
                return json.loads(self.archive.read(relative))
            except KeyError:
                pass
        self.missing.append(relative)
        return default

    def close(self):
        if self.archive:
            self.archive.close()


def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def save_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def number(value, integral=False):
    if value is None or value == "" or value == "N/A":
        return None
    return int(value) if integral else float(value)


def reduction(base, candidate):
    return None if base is None or candidate is None or base == 0 else 100 * (base - candidate) / base


def difference(a, b):
    return None if a is None or b is None else a - b


def describe(values):
    values = list(values)
    good = [v for v in values if v is not None]
    return {"n": len(good), "missing": len(values) - len(good),
            "median": median(good) if good else None,
            "min": min(good) if good else None, "max": max(good) if good else None}


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


def descriptor(cid, row, spec):
    """Use the frozen IDs as a transparent fallback for missing row metadata."""
    d = {k: row.get(k) if row.get(k) not in ("", None) else spec.get(k)
         for k in ("family", "qubits", "seed", "operations", "batch", "condition", "pair_id")}
    if m := re.fullmatch(r"stage2_phase_(\d+)q_L(\d+)_s(\d+)", cid):
        n, length, seed = map(int, m.groups())
        d.update(family="phase", qubits=n, seed=seed, operations=length,
                 batch="A" if length == 80 else "B1", condition=f"phase_{n}q_L{length}",
                 pair_id=f"phase_{n}q_s{seed}")
    elif m := re.fullmatch(r"stage2_tof_ladder_(\d+)q", cid):
        n = int(m.group(1))
        d.update(family="toffoli_ladder", qubits=n, batch="A", condition=f"toffoli_ladder_{n}q")
    elif m := re.fullmatch(r"stage2_qft_(\d+)q", cid):
        n = int(m.group(1))
        d.update(family="qft", qubits=n, batch="A", condition=f"qft_{n}q")
    elif m := re.fullmatch(r"stage2_parity6_(reuse|unique)_s(\d+)", cid):
        condition, seed = m.group(1), int(m.group(2))
        d.update(family="parity_reuse", qubits=6, seed=seed, batch="B2",
                 condition=f"parity_{condition}", pair_id=f"parity6_s{seed}")
    elif m := re.fullmatch(r"stage2_tof6_(disjoint|cascade)2", cid):
        d.update(family="toffoli_overlap", qubits=6, batch="B3", condition=f"toffoli_{m.group(1)}")
    return d


def make_pairs(rows, reader, metadata):
    grouped = defaultdict(dict)
    integer_fields = METRICS + ("qubits", "seed", "repetitions", "operations", "timed_repeats", "cnot_count", "cz_count")
    float_fields = ("optimization_ms_median", "optimization_ms_min", "optimization_ms_max", "verification_max_abs_residual")
    for r in rows:
        if r["method"] not in METHODS:
            raise ValueError(f"Unexpected method: {r['method']}")
        if r["method"] in grouped[r["circuit_id"]]:
            raise ValueError(f"Duplicate circuit/method row: {r['circuit_id']} / {r['method']}")
        for key in integer_fields:
            r[key] = number(r.get(key), integral=True)
        for key in float_fields:
            r[key] = number(r.get(key))
        grouped[r["circuit_id"]][r["method"]] = r
    verification = reader.json("verification.json", {})
    ids = expected_ids() + sorted(set(grouped) - set(expected_ids()))
    pairs, structures = [], {}
    for cid in ids:
        methods = grouped.get(cid, {})
        any_row = next(iter(methods.values()), {})
        input_json = reader.json(f"inputs/{cid}.json", {})
        structure = input_json.get("input_structure", {})
        if not structure:
            structure = verification.get(cid, {}).get("input_structure", {})
        structures[cid] = structure
        d = descriptor(cid, any_row, input_json.get("spec", {}))
        valid = all(methods.get(m, {}).get("verification_status") == "passed" for m in METHODS)
        p = {"circuit_id": cid, **d, "planned_input": cid in expected_ids(),
             "all_three_verified": valid, "present_method_rows": len(methods),
             "run_id": metadata["run_id"], "code_commit": metadata.get("code_commit"),
             "experiment_datetime": any_row.get("experiment_datetime")}
        for method in METHODS:
            r, prefix = methods.get(method, {}), PREFIXES[method]
            for key in METRICS + ("optimization_ms_median", "optimization_ms_min", "optimization_ms_max", "timed_repeats", "timing_status", "status", "verification_status", "verification_max_abs_residual", "error"):
                p[f"{prefix}_{key}"] = r.get(key)
        b, z, original = (methods.get(m, {}) for m in ("Gate-only", "ZX", "Original"))
        for key in METRICS:
            p[f"delta_{key}_zx_minus_gate"] = difference(z.get(key), b.get(key)) if valid else None
            p[f"{key}_reduction_pct_vs_gate"] = reduction(b.get(key), z.get(key)) if valid else None
            p[f"{key}_reduction_pct_vs_original"] = reduction(original.get(key), z.get(key)) if valid else None
        p["twoq_saved_vs_gate"] = difference(b.get("two_q_count"), z.get("two_q_count")) if valid else None
        relevant = ("two_q_count", "depth") if d["family"] == "qft" else ("t_count", "two_q_count")
        p["category_metrics"] = "+".join(relevant)
        p["effect_category"] = category([p[f"delta_{key}_zx_minus_gate"] for key in relevant])
        dt, dq = p["delta_t_count_zx_minus_gate"], p["delta_two_q_count_zx_minus_gate"]
        p["t_nonincrease_and_2q_reduction"] = dt <= 0 and dq < 0 if dt is not None and dq is not None else None
        p["runtime_ratio_zx_to_gate"] = (
            z["optimization_ms_median"] / b["optimization_ms_median"]
            if valid and b.get("optimization_ms_median") and z.get("optimization_ms_median") is not None else None)
        p["both_timing_complete"] = all(methods.get(m, {}).get("timing_status") == "complete" for m in ("Gate-only", "ZX"))
        outputs = reader.json(f"outputs/{cid}.json", {})
        pre = outputs.get("ZX-before-cleanup", {}).get("metrics", {})
        pre_check = verification.get(cid, {}).get("methods", {}).get("ZX-before-cleanup", {})
        p["zx_before_cleanup_verification_status"] = pre_check.get("status")
        for key in METRICS:
            p[f"zx_before_cleanup_{key}"] = pre.get(key)
        graphs = reader.json(f"graphs/{cid}.json", {})
        for key in ("graph_before_vertices", "graph_before_edges", "graph_after_vertices", "graph_after_edges"):
            p[key] = graphs.get("counts", {}).get(key)
        for key in ("active_wire_count", "raw_gate_count", "raw_gate_dependency_depth", "distinct_raw_zphase_angles_mod_2pi"):
            value = structure.get(key)
            p[f"input_{key}"] = json.dumps(value) if isinstance(value, (dict, list)) else value
        for key in ("phase_placement_count", "distinct_visited_parities", "repeat_visits_to_existing_parities", "parities_with_nonzero_combined_phase", "parities_with_odd_combined_quarter_phase"):
            p[f"input_{key}"] = structure.get("phase_polynomial_structure", {}).get(key)
        pairs.append(p)
    return pairs, verification, structures


def condition_summaries(pairs):
    groups = defaultdict(list)
    for p in pairs:
        groups[p["condition"]].append(p)
    summaries = []
    for condition, ps in groups.items():
        counts = Counter(p["effect_category"] for p in ps)
        d = {"condition": condition, "family": ps[0]["family"], "qubits": ps[0]["qubits"],
             "operations": ps[0]["operations"], "inputs": len(ps),
             "verified_inputs": sum(p["all_three_verified"] for p in ps),
             "complete_timings": sum(p["both_timing_complete"] for p in ps),
             **{k: counts[k] for k in ("improvement", "tradeoff", "unchanged", "regression", "unavailable")},
             "t_nonincrease_and_2q_reduction": None if ps[0]["family"] == "qft" else sum(p["t_nonincrease_and_2q_reduction"] is True for p in ps),
             "twoq_increase_count": sum(p["delta_two_q_count_zx_minus_gate"] is not None and p["delta_two_q_count_zx_minus_gate"] > 0 for p in ps),
             "depth_increase_count": sum(p["delta_depth_zx_minus_gate"] is not None and p["delta_depth_zx_minus_gate"] > 0 for p in ps),
             "t_increase_count": None if ps[0]["family"] == "qft" else sum(p["delta_t_count_zx_minus_gate"] is not None and p["delta_t_count_zx_minus_gate"] > 0 for p in ps)}
        for key in ("t_count_reduction_pct_vs_gate", "two_q_count_reduction_pct_vs_gate", "depth_reduction_pct_vs_gate", "runtime_ratio_zx_to_gate", "twoq_saved_vs_gate"):
            d.update({f"{key}_{stat}": value for stat, value in describe(p[key] for p in ps).items()})
        summaries.append(d)
    return summaries


def matched_tables(index):
    phase = []
    for n in (4, 8):
        for seed in SEEDS:
            a, b = (index[f"stage2_phase_{n}q_L{length}_s{seed}"] for length in (80, 160))
            g0, g1 = a["two_q_count_reduction_pct_vs_gate"], b["two_q_count_reduction_pct_vs_gate"]
            phase.append({"qubits": n, "seed": seed, "circuit_L80": a["circuit_id"], "circuit_L160": b["circuit_id"],
                          "both_verified": a["all_three_verified"] and b["all_three_verified"],
                          "g2_L80": g0, "g2_L160": g1,
                          "difference_percentage_points_L160_minus_L80": difference(g1, g0),
                          "t_nonincrease_2q_win_L80": a["t_nonincrease_and_2q_reduction"],
                          "t_nonincrease_2q_win_L160": b["t_nonincrease_and_2q_reduction"]})
    parity = []
    for seed in SEEDS:
        reuse, unique = (index[f"stage2_parity6_{c}_s{seed}"] for c in ("reuse", "unique"))
        row = {"seed": seed, "reuse_id": reuse["circuit_id"], "unique_id": unique["circuit_id"],
               "both_verified": reuse["all_three_verified"] and unique["all_three_verified"],
               "S2_reuse": reuse["twoq_saved_vs_gate"], "S2_unique": unique["twoq_saved_vs_gate"],
               "reuse_advantage_2q_gates": difference(reuse["twoq_saved_vs_gate"], unique["twoq_saved_vs_gate"])}
        for condition, p in (("reuse", reuse), ("unique", unique)):
            for key in ("original_t_count", "original_two_q_count", "original_depth", "gate_t_count", "zx_t_count", "gate_two_q_count", "zx_two_q_count", "gate_depth", "zx_depth", "delta_t_count_zx_minus_gate", "t_nonincrease_and_2q_reduction", "input_active_wire_count", "input_distinct_visited_parities", "input_repeat_visits_to_existing_parities"):
                row[f"{condition}_{key}"] = p[key]
        parity.append(row)
    return phase, parity


def decision(eligible, expected, meets):
    return "inconclusive" if eligible != expected else "supported" if meets else "not_supported"


def evaluate_hypotheses(index, phase, parity):
    hypotheses = {}
    p4 = [index[f"stage2_phase_4q_L80_s{s}"] for s in SEEDS]
    p8 = [index[f"stage2_phase_8q_L80_s{s}"] for s in SEEDS]
    sub = {}
    for n, ps in ((4, p4), (8, p8)):
        eligible = [p for p in ps if p["all_three_verified"] and p["two_q_count_reduction_pct_vs_gate"] is not None
                    and (n != 4 or p["delta_t_count_zx_minus_gate"] is not None)]
        wins = sum(p["t_nonincrease_and_2q_reduction"] is True for p in eligible) if n == 4 else sum(p["delta_two_q_count_zx_minus_gate"] > 0 for p in eligible)
        stats = describe(p["two_q_count_reduction_pct_vs_gate"] for p in ps)
        med_ok = stats["median"] is not None and (stats["median"] > 0 if n == 4 else stats["median"] < 0)
        sub[f"phase_{n}q_L80"] = {"expected_inputs": 10, "verified_inputs": sum(p["all_three_verified"] for p in ps),
                                  "eligible_inputs": len(eligible), "criterion_count": wins, "required_count": 8,
                                  "g2_percent": stats, "status": decision(len(eligible), 10, wins >= 8 and med_ok)}
    overall = "inconclusive" if any(v["status"] == "inconclusive" for v in sub.values()) else "supported" if all(v["status"] == "supported" for v in sub.values()) else "not_supported"
    hypotheses["H1"] = {"criterion": RULES["H1"], "status": overall, "subconditions": sub}
    for name, ids, metrics, predicates in (
        ("H2", [f"stage2_tof_ladder_{n}q" for n in (5, 7)], ("t_count", "two_q_count"), (lambda x: x < 0, lambda x: x > 0)),
        ("H3", [f"stage2_qft_{n}q" for n in (5, 7)], ("two_q_count", "depth"), (lambda x: x > 0, lambda x: x > 0)),
    ):
        observations = []
        for cid in ids:
            p = index[cid]
            diffs = [p[f"delta_{key}_zx_minus_gate"] for key in metrics]
            eligible = p["all_three_verified"] and all(v is not None for v in diffs)
            observations.append({"circuit_id": cid, "verified": p["all_three_verified"], "eligible": eligible,
                                 "differences_zx_minus_gate": dict(zip(metrics, diffs)),
                                 "criterion_met": all(f(v) for f, v in zip(predicates, diffs)) if eligible else None})
        n = sum(o["eligible"] for o in observations)
        wins = sum(o["criterion_met"] is True for o in observations)
        hypotheses[name] = {"criterion": RULES[name], "status": decision(n, 2, wins == 2),
                            "expected_inputs": 2, "eligible_inputs": n, "criterion_count": wins, "observations": observations}
    for name, matched, key in (
        ("H4", [r for r in phase if r["qubits"] == 8], "difference_percentage_points_L160_minus_L80"),
        ("H5", parity, "reuse_advantage_2q_gates"),
    ):
        eligible = [r for r in matched if r["both_verified"] and r[key] is not None]
        stats = describe(r[key] for r in matched)
        wins = sum(r[key] > 0 for r in eligible)
        hypotheses[name] = {"criterion": RULES[name], "status": decision(len(eligible), 10, wins >= 8 and stats["median"] is not None and stats["median"] > 0),
                            "expected_pairs": 10, "verified_pairs": sum(r["both_verified"] for r in matched),
                            "eligible_pairs": len(eligible), "criterion_count": wins, "required_count": 8,
                            "paired_difference": stats, "observations": matched}
    hypotheses["H5"]["t_nonincrease_and_2q_win"] = {
        c: {"expected_inputs": 10,
            "verified_inputs": sum(index[f"stage2_parity6_{c}_s{s}"]["all_three_verified"] for s in SEEDS),
            "criterion_count": sum(index[f"stage2_parity6_{c}_s{s}"]["t_nonincrease_and_2q_reduction"] is True for s in SEEDS),
            "t_increase_count": sum(index[f"stage2_parity6_{c}_s{s}"]["delta_t_count_zx_minus_gate"] is not None and index[f"stage2_parity6_{c}_s{s}"]["delta_t_count_zx_minus_gate"] > 0 for s in SEEDS)}
        for c in ("reuse", "unique")}
    disjoint, cascade = (index[f"stage2_tof6_{c}2"] for c in ("disjoint", "cascade"))
    burdens = {"disjoint": disjoint["delta_two_q_count_zx_minus_gate"], "cascade": cascade["delta_two_q_count_zx_minus_gate"]}
    eligible = sum(p["all_three_verified"] and p["delta_two_q_count_zx_minus_gate"] is not None for p in (disjoint, cascade))
    delta = difference(burdens["cascade"], burdens["disjoint"])
    hypotheses["H6"] = {"criterion": RULES["H6"], "status": decision(eligible, 2, delta is not None and delta > 0),
                        "expected_inputs": 2, "eligible_inputs": eligible, "extra_2q_burden": burdens,
                        "cascade_minus_disjoint_extra_2q": delta,
                        "confound": "Active wires: disjoint=6, cascade=4 plus 2 identities. Cascade embeds a previously explored 4q ladder."}
    return {"interpretation": "Predeclared descriptive thresholds, not significance tests. Missing/failed verification or undefined required metrics makes the corresponding hypothesis inconclusive; no replacement seeds or omitted failures.",
            "hypotheses": hypotheses}


def runtime_table(timings):
    component_rows = []
    for cid, records in timings.items():
        for method in ("Gate-only", "ZX"):
            all_ts = [r for r in records if r.get("phase") == "timed" and r.get("method") == method]
            ts = [r for r in all_ts if r.get("status") == "passed"]
            c = {"circuit_id": cid, "method": method, "timed_calls_recorded": len(all_ts), "successful_timed_calls": len(ts), "failed_timed_calls": len(all_ts) - len(ts)}
            for key in ("input_copy_ms", "conversion_ms", "simplification_ms", "graph_copy_ms", "extraction_ms", "pre_cleanup_normalization_ms", "cleanup_ms", "final_normalization_ms", "total_ms"):
                c[key + "_median"] = median(r[key] for r in ts if r.get(key) is not None) if any(r.get(key) is not None for r in ts) else None
            component_rows.append(c)
    return component_rows


def write_tables(out, rows, pairs, conditions, hypotheses, phase, parity, metadata):
    save_csv(out / "paired_results.csv", pairs)
    save_csv(out / "condition_summary.csv", conditions)
    save_csv(out / "phase_length_pairs.csv", phase)
    save_csv(out / "parity_pairs.csv", parity)
    save_json(out / "hypotheses.json", hypotheses)
    lines = ["# Stage 2 — Predeclared hypothesis decisions", "",
             f"Run: `{metadata['run_id']}`; code: `{metadata.get('code_commit')}`.", "",
             hypotheses["interpretation"], "", "| Hypothesis | Decision | Frozen criterion |", "| --- | --- | --- |"]
    for name, h in hypotheses["hypotheses"].items():
        lines.append(f"| {name} | {h['status']} | {h['criterion']} |")
    lines += ["", "Exact counts, observed denominators, missing values, minima, medians, maxima and every paired observation are retained in [hypotheses.json](hypotheses.json).", ""]
    (out / "hypotheses.md").write_text("\n".join(lines))
    lines = ["# Stage 2 — Complete results", "", f"Run: `{metadata['run_id']}`  ",
             f"Code: `{metadata.get('code_commit')}`", "",
             f"All {len(rows)} recorded method rows are retained. Planned: 66 inputs / 198 method rows. Original optimization time and QFT T-count are N/A. Optimization time is the median of successful timed calls; partial timings are explicitly marked. Positive reduction means fewer gates. No backward/reverse extraction.", "",
             "| Circuit | Method | T | 2Q | Depth | Time ms | Verification | Timing status | Error |",
             "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for r in rows:
        error = str(r.get("error", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['circuit_id']} | {r['method']} | {fmt(r['t_count'])} | {fmt(r['two_q_count'])} | {fmt(r['depth'])} | {fmt(r['optimization_ms_median'],3)} | {r.get('verification_status')} | {r.get('timing_status')} | {error} |")
    lines += ["", "## Every input paired against Gate-only", "",
              "| Circuit | Verified | T reduction % | 2Q reduction % | Depth reduction % | 2Q saved | ZX/Gate time | T nonincrease + 2Q win | Category |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
    for p in pairs:
        lines.append(f"| {p['circuit_id']} | {p['all_three_verified']} | {fmt(p['t_count_reduction_pct_vs_gate'],1)} | {fmt(p['two_q_count_reduction_pct_vs_gate'],1)} | {fmt(p['depth_reduction_pct_vs_gate'],1)} | {fmt(p['twoq_saved_vs_gate'])} | {fmt(p['runtime_ratio_zx_to_gate'],2)} | {fmt(p['t_nonincrease_and_2q_reduction'])} | {p['effect_category']} |")
    lines += ["", "## Matched phase length comparisons", "", "| Qubits | Seed | g2 L80 % | g2 L160 % | L160 minus L80, percentage points | Both verified |", "| ---: | ---: | ---: | ---: | ---: | --- |"]
    for r in phase:
        lines.append(f"| {r['qubits']} | {r['seed']} | {fmt(r['g2_L80'],2)} | {fmt(r['g2_L160'],2)} | {fmt(r['difference_percentage_points_L160_minus_L80'],2)} | {r['both_verified']} |")
    lines += ["", "## Matched parity comparisons", "", "| Seed | S2 unique | S2 reuse | Reuse advantage | Unique T: Gate → ZX | Reuse T: Gate → ZX | Both verified |", "| ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for r in parity:
        lines.append(f"| {r['seed']} | {fmt(r['S2_unique'])} | {fmt(r['S2_reuse'])} | {fmt(r['reuse_advantage_2q_gates'])} | {fmt(r['unique_gate_t_count'])} → {fmt(r['unique_zx_t_count'])} | {fmt(r['reuse_gate_t_count'])} → {fmt(r['reuse_zx_t_count'])} | {r['both_verified']} |")
    lines += ["", "Data: [paired CSV](paired_results.csv), [condition summaries](condition_summary.csv), [H1–H6](hypotheses.md), [runtime components](runtime_components.csv), [raw rows](../../runs/" + metadata["run_id"] + "/results.csv).", ""]
    (out / "all_results.md").write_text("\n".join(lines))


def save_figure(fig, out, name):
    fig.savefig(out / f"{name}.svg", metadata={"Date": None})
    fig.savefig(out / f"{name}.png", dpi=155)
    plt.close(fig)


def figures(out, index, phase, parity, diagnostics):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none", "svg.hashsalt": out.name})
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True, layout="constrained")
    for ax, n in zip(axes, (4, 8)):
        rs = [r for r in phase if r["qubits"] == n and r["both_verified"] and r["g2_L80"] is not None and r["g2_L160"] is not None]
        for j, r in enumerate(rs):
            ax.plot([0, 1], [r["g2_L80"], r["g2_L160"]], "o-", color="#2d7892", alpha=.4, lw=1, ms=4, label="Matched seed" if j == 0 else None)
        if rs:
            ax.plot([0, 1], [median(r["g2_L80"] for r in rs), median(r["g2_L160"] for r in rs)], "s--", color="#be4c21", lw=2.3, ms=7, label="Condition median")
        ax.axhline(0, color="#555555", lw=1)
        ax.set_xticks([0, 1], ["80 operations", "160 operations"])
        ax.set_xlim(-.2, 1.2)
        ax.set_title(f"{n} qubits; {len(rs)}/10 verified, defined pairs")
        ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel("2Q reduction vs Gate-only (%)")
    axes[1].legend(loc="best", fontsize=8)
    fig.suptitle("Width and length of phase circuits\nSame-width, same-seed L80 input is a prefix of L160")
    save_figure(fig, out, "phase_width_length")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), layout="constrained")
    for ax, label, getter in (
        (axes[0], "2Q gates saved vs Gate-only", lambda r, c: r[f"S2_{c}"]),
        (axes[1], "T gates saved vs Gate-only", lambda r, c: difference(r[f"{c}_gate_t_count"], r[f"{c}_zx_t_count"])),
    ):
        valid = [r for r in parity if r["both_verified"] and all(getter(r, c) is not None for c in ("unique", "reuse"))]
        for j, r in enumerate(valid):
            ax.plot([0, 1], [getter(r, "unique"), getter(r, "reuse")], "o-", color="#7054a1", alpha=.45, lw=1, ms=4, label="Matched support seed" if j == 0 else None)
        if valid:
            ax.plot([0, 1], [median(getter(r, c) for r in valid) for c in ("unique", "reuse")], "s--", color="#be4c21", lw=2.3, ms=7, label="Condition median")
        ax.set_xticks([0, 1], ["8 unique supports", "4 supports used twice"])
        ax.set_xlim(-.2, 1.2)
        ax.set_ylabel(label)
        ax.axhline(0, color="#555555", lw=1)
        ax.grid(axis="y", alpha=.2)
    axes[1].legend(loc="best", fontsize=8)
    fig.suptitle("Controlled parity reuse: 10 matched pairs\n6 qubits; Original T=8 and 2Q=32 in each input")
    save_figure(fig, out, "parity_comparison")
    diagnostic_cases = {c["circuit_id"]: c for c in diagnostics.get("cases", [])}
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.4), layout="constrained")
    stage_prefixes = ("original", "gate", "zx_before_cleanup", "zx")
    for ax, cid in zip(axes.flat, PRESELECTED):
        p = index[cid]
        for j, (key, label, color) in enumerate((("t_count", "T", "#8c6bb1"), ("two_q_count", "2Q", "#176b9b"), ("depth", "Depth", "#c05621"))):
            values = [p.get(f"{prefix}_{key}") for prefix in stage_prefixes]
            # Display only verified stage metrics; preserve missing bars as N/A.
            for i, prefix in enumerate(stage_prefixes):
                passed = p.get(f"{prefix}_verification_status") == "passed"
                if not passed:
                    values[i] = None
            positions = np.arange(4) + (j - 1) * .23
            chosen = [(x, value) for x, value in zip(positions, values) if value is not None]
            if chosen:
                bars = ax.bar([x for x, _ in chosen], [v for _, v in chosen], .23, color=color, label=label)
                ax.bar_label(bars, fontsize=7, padding=2)
        ax.set_xticks(np.arange(4), ["Original", "Gate-only", "Extracted\npre-cleanup", "ZX final"])
        ax.set_ylabel("Logical counts / depth")
        graph_note = f"ZX vertices {fmt(p['graph_before_vertices'])} → {fmt(p['graph_after_vertices'])}"
        d = diagnostic_cases.get(cid, {})
        if d:
            trace = d.get("trace_counts", {})
            graph_note += f"; trace {d.get('status', 'unknown')}"
            if trace.get("applied_row_xors") is not None:
                graph_note += f"; row XORs {trace['applied_row_xors']}"
        else:
            graph_note += "; diagnostic trace unavailable"
        title = cid.replace("stage2_", "") + (" (T N/A)" if p["family"] == "qft" else "")
        ax.set_title(title + "\n" + graph_note, fontsize=9)
        ax.grid(axis="y", alpha=.18)
        ax.set_axisbelow(True)
        ax.margins(y=.2)
        ax.legend(fontsize=7, loc="upper left")
    fig.suptitle("Four cases selected before execution: output costs through the pipeline\nGraph size and extracted circuit cost are different quantities")
    save_figure(fig, out, "stage_costs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    run, out = ROOT / "runs" / args.run_id, ROOT / "analysis" / args.run_id
    if not run.is_dir():
        raise ValueError(f"Run directory not found: {run}")
    metadata = json.loads((run / "metadata.json").read_text())
    if metadata.get("state") != "completed" or metadata.get("mode") != "stage2_full":
        raise ValueError("Only a completed full Stage 2 run can be summarized")
    if metadata.get("run_id") != args.run_id:
        raise ValueError("Run ID mismatch")
    with (run / "results.csv").open() as f:
        rows = list(csv.DictReader(f))
    reader = RunReader(run)
    pairs, verification, structures = make_pairs(rows, reader, metadata)
    index = {p["circuit_id"]: p for p in pairs}
    phase, parity = matched_tables(index)
    conditions = condition_summaries(pairs)
    hypotheses = evaluate_hypotheses(index, phase, parity)
    timings = reader.json("timings.json", {})
    components = runtime_table(timings)
    diagnostic_path = out / "diagnostics" / "summary.json"
    diagnostics = json.loads(diagnostic_path.read_text()) if diagnostic_path.exists() else {}
    out.mkdir(parents=True, exist_ok=True)
    write_tables(out, rows, pairs, conditions, hypotheses, phase, parity, metadata)
    save_csv(out / "runtime_components.csv", components)
    save_json(out / "input_structure.json", structures)
    flat_times = [r for records in timings.values() for r in records if r.get("phase") == "timed"]
    checks = [v for x in verification.values() for v in x.get("methods", {}).values()]
    observed_ids = set(r["circuit_id"] for r in rows)
    ct = [p for p in pairs if p["family"] != "qft"]
    residuals = [r["verification_max_abs_residual"] for r in rows if r["verification_max_abs_residual"] is not None]
    all_residuals = [c["max_abs_residual"] for c in checks if c.get("max_abs_residual") is not None]
    failures = [{"circuit_id": r["circuit_id"], "method": r["method"], "status": r.get("status"), "verification_status": r.get("verification_status"), "timing_status": r.get("timing_status"), "error": r.get("error")}
                for r in rows if r.get("status") != "passed" or r.get("verification_status") != "passed" or (r["method"] != "Original" and r.get("timing_status") != "complete")]
    protocol_issues = []
    for r in rows:
        if r.get("family") == "qft" and r["t_count"] is not None:
            protocol_issues.append(f"QFT T-count must be N/A: {r['circuit_id']} / {r['method']}")
        if r["method"] == "Original" and r["optimization_ms_median"] is not None:
            protocol_issues.append(f"Original optimization time must be N/A: {r['circuit_id']}")
    summary = {
        "run_id": args.run_id, "code_commit": metadata.get("code_commit"),
        "experiment_started_jst": metadata.get("started_jst"), "experiment_finished_jst": metadata.get("finished_jst"),
        "analysis_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "results_sha256": sha256((run / "results.csv").read_bytes()).hexdigest(),
        "expected_inputs": 66, "expected_rows": 198, "recorded_inputs": len(observed_ids), "row_count": len(rows),
        "missing_input_ids": sorted(set(expected_ids()) - observed_ids), "unexpected_input_ids": sorted(observed_ids - set(expected_ids())),
        "missing_method_rows": [{"circuit_id": p["circuit_id"], "present_rows": p["present_method_rows"]} for p in pairs if p["present_method_rows"] != 3],
        "row_status_counts": dict(Counter(r.get("status") for r in rows)),
        "verification_status_counts": dict(Counter(r.get("verification_status") for r in rows)),
        "all_three_verified_inputs": sum(p["all_three_verified"] for p in pairs),
        "ct_input_count": len(ct), "ct_category_counts": dict(Counter(p["effect_category"] for p in ct)),
        "qft_category_counts": dict(Counter(p["effect_category"] for p in pairs if p["family"] == "qft")),
        "t_nonincrease_and_2q_reduction_count": sum(p["t_nonincrease_and_2q_reduction"] is True for p in ct),
        "t_nonincrease_and_2q_reduction_ids": [p["circuit_id"] for p in ct if p["t_nonincrease_and_2q_reduction"] is True],
        "t_increase_ids": [p["circuit_id"] for p in ct if p["delta_t_count_zx_minus_gate"] is not None and p["delta_t_count_zx_minus_gate"] > 0],
        "timed_call_count": len(flat_times), "expected_timed_calls": 1320,
        "timed_status_counts": dict(Counter(t.get("status") for t in flat_times)),
        "timed_hash_matches": sum(t.get("output_validation") == "hash_matches_verified_output" for t in flat_times),
        "timed_nonmatching_hash_or_unavailable": sum(t.get("output_validation") != "hash_matches_verified_output" for t in flat_times),
        "all_stage_check_count": len(checks), "all_stage_check_status_counts": dict(Counter(c.get("status") for c in checks)),
        "input_definition_check_status_counts": dict(Counter(v.get("input_definition_check", {}).get("status", "unavailable") for v in verification.values())),
        "max_abs_residual_main_rows": max(residuals) if residuals else None,
        "max_abs_residual_including_pre_cleanup": max(all_residuals) if all_residuals else None,
        "runtime_ratio_zx_to_gate": describe(p["runtime_ratio_zx_to_gate"] for p in pairs),
        "runtime_zx_slower_inputs": sum(p["runtime_ratio_zx_to_gate"] is not None and p["runtime_ratio_zx_to_gate"] > 1 for p in pairs),
        "failures_or_partial_timings": failures, "protocol_issues": protocol_issues,
        "missing_raw_json_files": sorted(set(reader.missing)),
        "hypothesis_decisions": {name: h["status"] for name, h in hypotheses["hypotheses"].items()},
        "conditions": conditions,
        "diagnostic_status_counts": dict(Counter(c.get("status") for c in diagnostics.get("cases", []))),
        "interpretation": "Fixed forward-only PyZX pipeline. Percentages are inputwise reductions summarized within a condition, not ratios of aggregate gate counts. QFT T-count and Original optimization time are N/A. Runtime is within-run classical optimization only. Seed pairs are not independent new circuits across length; engineered parity controls differ in unitary. Thresholds are descriptive, not significance tests. Missing or failed verification is retained and never counted as improvement.",
    }
    save_json(out / "summary.json", summary)
    figures(out, index, phase, parity, diagnostics)
    reader.close()
    print(json.dumps({k: v for k, v in summary.items() if k not in ("conditions", "t_nonincrease_and_2q_reduction_ids")}, indent=2))


if __name__ == "__main__":
    main()
