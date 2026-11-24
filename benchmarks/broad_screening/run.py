#!/usr/bin/env python3
"""Execute the frozen 33-input Original/Gate-only/ZX screening.

Set OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1 before starting.
--prepare freezes input hashes without running optimization.
--smoke runs one four-qubit input per family into a separate run directory.
Every run uses a new directory and preserves failed as well as successful rows.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import csv
import inspect
import json
import os
from pathlib import Path
import platform
import resource
import signal
from statistics import median
import subprocess
import sys
from time import perf_counter_ns
import traceback
from zoneinfo import ZoneInfo

import numpy as np
import pyzx as zx

from circuits import build_circuit, get_specs
from semantics import evaluate, metrics, normalize, verify, verifier_controls

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "stage1-standard-v1.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
JST = ZoneInfo("Asia/Tokyo")
METHODS = CONFIG["methods"]
FIELDS = [
    "run_id", "experiment_datetime", "timezone", "circuit_id", "family", "qubits", "seed", "repetitions",
    "generator_parameters", "input_hash", "normalized_input_hash", "protocol_id", "gate_basis_id",
    "method", "pyzx_version", "code_commit", "status", "verification_status", "t_count",
    "t_count_note", "non_clifford_rotations", "two_q_count", "cnot_count", "cz_count", "depth", "total_gates",
    "optimization_ms_median", "optimization_ms_min", "optimization_ms_max", "timed_repeats",
    "timing_status", "normalization_ms", "verification_ms", "verification_max_abs_residual", "output_hash", "error"
]


def now():
    return datetime.now(timezone.utc)


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def save_json(path, value):
    """Atomically replace only this new run's intermediate snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class PipelineTimeout(TimeoutError):
    pass


class VerificationFailure(RuntimeError):
    def __init__(self, check):
        self.status = check["status"]
        super().__init__(f"Independent verification returned {self.status}")


@contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise PipelineTimeout(f"Exceeded {seconds}s")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def ms(start):
    return (perf_counter_ns() - start) / 1e6


def pipeline(c0, method, general, capture=False):
    """The artifact-producing quality call is excluded from timing summaries."""
    timings = {}
    total = perf_counter_ns()
    t = perf_counter_ns()
    source = c0.copy()
    timings["input_copy_ms"] = ms(t)
    artifacts = {}
    if method == "ZX":
        t = perf_counter_ns()
        graph = source.to_graph()
        timings["conversion_ms"] = ms(t)
        if capture:
            artifacts["graph_before"] = graph.to_json()
            artifacts["graph_before_vertices"] = graph.num_vertices()
            artifacts["graph_before_edges"] = graph.num_edges()
        t = perf_counter_ns()
        zx.simplify.full_reduce(graph, quiet=True)
        timings["simplification_ms"] = ms(t)
        if capture:
            artifacts["graph_after"] = graph.to_json()
            artifacts["graph_after_vertices"] = graph.num_vertices()
            artifacts["graph_after_edges"] = graph.num_edges()
        t = perf_counter_ns()
        extraction_graph = graph.copy()
        timings["graph_copy_ms"] = ms(t)
        t = perf_counter_ns()
        extracted = zx.extract_circuit(extraction_graph, **CONFIG["extraction"])
        timings["extraction_ms"] = ms(t)
        t = perf_counter_ns()
        source = normalize(extracted, allow_general_phases=general)
        timings["pre_cleanup_normalization_ms"] = ms(t)
        if capture:
            artifacts["extracted_before_cleanup_qasm"] = source.to_qasm()
            artifacts["extracted_before_cleanup_metrics"] = metrics(source, t_applicable=not general)
            artifacts["extracted_before_cleanup_circuit"] = source.copy()
    t = perf_counter_ns()
    cleaned = zx.optimize.basic_optimization(source, do_swaps=False, quiet=True)
    timings["cleanup_ms"] = ms(t)
    t = perf_counter_ns()
    output = normalize(cleaned, allow_general_phases=general)
    timings["final_normalization_ms"] = ms(t)
    timings["total_ms"] = ms(total)
    timings["artifact_capture_enabled"] = capture
    return output, timings, artifacts


def check_output(reference, circuit):
    t = perf_counter_ns()
    with deadline(CONFIG["resources"]["seconds_per_verification"]):
        result = verify(reference, evaluate(circuit), atol=CONFIG["verification"]["atol"])
    result["verification_ms"] = ms(t)
    return result


def source_hashes():
    paths = [Path(__file__), Path(__file__).with_name("circuits.py"),
             Path(__file__).with_name("semantics.py"), CONFIG_PATH]
    own = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    package = {}
    for module in [zx.extract, zx.simplify, zx.optimize, zx.generate, zx.circuit.gates]:
        p = Path(inspect.getfile(module))
        package[p.name] = sha256(p.read_bytes()).hexdigest()
    return {"repository_files_sha256": own, "pyzx_module_sha256": package}


def prepare_manifest():
    specs = get_specs()
    entries = []
    for spec in specs:
        raw = build_circuit(spec)
        c0 = normalize(raw, allow_general_phases=not spec["t_count_applicable"])
        entries.append({**spec, "raw_qasm_sha256": digest(raw.to_qasm()),
                        "normalized_qasm_sha256": digest(c0.to_qasm())})
    if len(entries) != 33 or len({x["circuit_id"] for x in entries}) != 33:
        raise AssertionError("Expected 33 unique input IDs")
    if len({x["raw_qasm_sha256"] for x in entries}) != 33:
        raise AssertionError("Unexpected duplicate input QASM")
    destination = ROOT / CONFIG["input_manifest"]
    value = {"protocol_id": CONFIG["protocol_id"], "created_utc": now().isoformat(),
             "research_plan_commit": CONFIG["research_plan_commit"],
             "count": 33, "family_counts": dict(Counter(x["family"] for x in entries)), "inputs": entries}
    if destination.exists():
        previous = json.loads(destination.read_text())
        if previous["inputs"] != entries:
            raise RuntimeError("Frozen manifest differs; use a new protocol ID")
    else:
        save_json(destination, value)
    return json.loads(destination.read_text())


def failed_status(exception):
    if isinstance(exception, VerificationFailure):
        return exception.status
    if isinstance(exception, PipelineTimeout):
        return "timeout"
    if isinstance(exception, MemoryError):
        return "inconclusive"
    if isinstance(exception, (NotImplementedError, TypeError)):
        return "unsupported"
    return "execution_error"


def base_row(spec, method, run_id, code_commit, normalization_ms=None):
    row = {key: None for key in FIELDS}
    row.update(run_id=run_id, experiment_datetime=now().astimezone(JST).isoformat(), timezone="Asia/Tokyo",
               circuit_id=spec["circuit_id"], family=spec["family"], qubits=spec["qubits"], seed=spec["seed"], repetitions=spec["repetitions"],
               generator_parameters=json.dumps(spec["generator_parameters"], sort_keys=True), input_hash=spec["raw_qasm_sha256"],
               normalized_input_hash=spec["normalized_qasm_sha256"], protocol_id=CONFIG["protocol_id"], gate_basis_id=CONFIG["gate_basis_id"],
               method=method, pyzx_version=zx.__version__, code_commit=code_commit,
               t_count_note="literal_T_and_Tdg" if spec["t_count_applicable"] else "not_applicable_general_angles_no_CT_synthesis",
               normalization_ms=normalization_ms, timed_repeats=0, timing_status="not_applicable" if method=="Original" else "not_measured")
    return row


def input_definition_check(spec, raw_matrix):
    """Check the algorithmic meaning of QFT/Pauli inputs independently of gates."""
    n, family = spec["qubits"], spec["family"]
    dim = 2**n
    if family == "qft":
        j, k = np.meshgrid(np.arange(dim), np.arange(dim))
        intended = np.exp(2j*np.pi*j*k/dim) / np.sqrt(dim)
    elif family == "pauli":
        intended = np.eye(dim, dtype=complex)
        rows = np.arange(dim)
        params = spec["generator_parameters"]
        for _ in range(params["block_repetitions"]):
            for term in params["chronological_block"]:
                a, b = term["qubits"]
                ma, mb = 1 << (n-1-a), 1 << (n-1-b)
                theta = np.pi*term["theta_pi"][0]/term["theta_pi"][1]
                if term["axis"] == "XX":
                    pauli_applied = intended[rows ^ ma ^ mb]
                else:
                    parity = ((rows & ma)!=0) ^ ((rows & mb)!=0)
                    pauli_applied = (1-2*parity.astype(int))[:, None] * intended
                intended = np.cos(theta/2)*intended - 1j*np.sin(theta/2)*pauli_applied
    else:
        return {"status": "not_applicable", "reason": "raw chronological gate list defines this input"}
    check = verify(intended, raw_matrix, atol=CONFIG["verification"]["atol"])
    if check["status"] != "passed":
        raise AssertionError(f"Input definition failed: {spec['circuit_id']}: {check}")
    return check


def run(args, manifest):
    run_id = args.run_id or ("smoke-" if args.smoke else "stage1-") + now().strftime("%Y%m%dT%H%M%SZ")
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_id):
        raise ValueError("run-id must contain letters, digits, hyphens or underscores")
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for sub in ["inputs", "graphs", "outputs", "records"]:
        (run_dir / sub).mkdir()
    for name in ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"]:
        if os.environ.get(name) != "1":
            raise RuntimeError(f"Set {name}=1 before starting Python")
    cap = CONFIG["resources"]["address_space_limit_bytes"]
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    controls = verifier_controls()
    save_json(run_dir / "verifier_controls.json", controls)
    specs = manifest["inputs"]
    if args.smoke:
        selected, seen = [], set()
        for spec in specs:
            if spec["family"] not in seen:
                selected.append(spec)
                seen.add(spec["family"])
        specs = selected
    start = now()
    metadata = {"run_id": run_id, "mode": "smoke" if args.smoke else "stage1_full",
                "started_utc": start.isoformat(), "started_jst": start.astimezone(JST).isoformat(),
                "timezone": "Asia/Tokyo", "code_commit": args.code_commit,
                "protocol_id": CONFIG["protocol_id"], "protocol_sha256": sha256(CONFIG_PATH.read_bytes()).hexdigest(),
                "manifest_sha256": sha256((ROOT / CONFIG["input_manifest"]).read_bytes()).hexdigest(),
                "expected_inputs": len(specs), "expected_rows": len(specs)*3,
                "pyzx": zx.__version__, "numpy": np.__version__, "python": platform.python_version(),
                "platform": platform.platform(), "cpu_count": os.cpu_count(),
                "cpu_model": next((s.split(':',1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines() if s.startswith('model name')), "unknown"),
                "thread_env": {k: os.environ[k] for k in ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"]},
                "source_hashes": source_hashes(), "state": "running"}
    save_json(run_dir / "metadata.json", metadata)
    save_json(run_dir / "protocol.json", CONFIG)
    timings_all, verification_all = {}, {}
    rows = []
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        file.flush()
        for index, spec in enumerate(specs, 1):
            cid = spec["circuit_id"]
            print(f"[{index}/{len(specs)}] {cid}", flush=True)
            general = not spec["t_count_applicable"]
            try:
                raw = build_circuit(spec)
                raw_qasm = raw.to_qasm()
                if digest(raw_qasm) != spec["raw_qasm_sha256"]:
                    raise RuntimeError(f"Frozen raw input changed: {cid}")
                t = perf_counter_ns()
                c0 = normalize(raw, allow_general_phases=general)
                normalization_ms = ms(t)
                if digest(c0.to_qasm()) != spec["normalized_qasm_sha256"]:
                    raise RuntimeError(f"Frozen normalized input changed: {cid}")
                save_json(run_dir / "inputs" / f"{cid}.json", {"spec": spec, "raw_qasm": raw_qasm, "normalized_qasm": c0.to_qasm()})
                t = perf_counter_ns()
                with deadline(CONFIG["resources"]["seconds_per_verification"]):
                    reference = evaluate(raw)
                    definition_check = input_definition_check(spec, reference)
                reference_ms = ms(t)
                verification_all[cid] = {"reference_construction_ms": reference_ms, "input_definition_check": definition_check, "methods": {}}
            except Exception as exception:
                error = f"Input preparation: {type(exception).__name__}: {exception}"
                verification_all[cid] = {"status": failed_status(exception), "error": error, "traceback": traceback.format_exc()}
                failed = []
                for method in METHODS:
                    row = base_row(spec, method, run_id, args.code_commit)
                    row.update(status=failed_status(exception), verification_status="inconclusive", error=error)
                    writer.writerow(row)
                    rows.append(row)
                    failed.append(row)
                file.flush()
                save_json(run_dir / "records" / f"{cid}.json", failed)
                save_json(run_dir / "verification.json", verification_all)
                print(error, flush=True)
                continue
            candidate_rows, candidates, outputs = {}, {}, {}
            for method in METHODS:
                row = base_row(spec, method, run_id, args.code_commit, normalization_ms)
                try:
                    if method == "Original":
                        output = c0
                        artifacts = {}
                    else:
                        with deadline(CONFIG["resources"]["seconds_per_pipeline_call"]):
                            output, _, artifacts = pipeline(c0, method, general, capture=True)
                    qasm = output.to_qasm()
                    check = check_output(reference, output)
                    row.update(metrics(output, t_applicable=not general))
                    row.update(status=check["status"], verification_status=check["status"],
                               verification_ms=check["verification_ms"], verification_max_abs_residual=check.get("max_abs_residual"),
                               output_hash=digest(qasm))
                    verification_all[cid]["methods"][method] = check
                    outputs[method] = {"qasm": qasm, "sha256": digest(qasm)}
                    if method == "ZX":
                        graphs = {key: json.loads(artifacts[key]) for key in ["graph_before", "graph_after"]}
                        graphs["counts"] = {key: val for key, val in artifacts.items() if key.endswith(("_vertices", "_edges"))}
                        save_json(run_dir / "graphs" / f"{cid}.json", graphs)
                        pre_qasm = artifacts["extracted_before_cleanup_qasm"]
                        outputs["ZX-before-cleanup"] = {"qasm": pre_qasm, "sha256": digest(pre_qasm),
                                                        "metrics": artifacts["extracted_before_cleanup_metrics"]}
                        verification_all[cid]["methods"]["ZX-before-cleanup"] = check_output(reference, artifacts["extracted_before_cleanup_circuit"])
                    if check["status"] == "passed":
                        candidates[method] = output
                except Exception as exception:
                    row.update(status=failed_status(exception), verification_status="inconclusive",
                               error=f"{method} pipeline/verification: {type(exception).__name__}: {exception}")
                    verification_all[cid]["methods"][method] = {"status": row["status"], "error": row["error"],
                                                                "traceback": traceback.format_exc()}
                candidate_rows[method] = row
                save_json(run_dir / "records" / f"{cid}.json", list(candidate_rows.values()))
                save_json(run_dir / "outputs" / f"{cid}.json", outputs)
                save_json(run_dir / "verification.json", verification_all)
            records = []
            timings_all[cid] = records
            ready = set()
            for method in ["Gate-only", "ZX"]:
                if method not in candidates:
                    continue
                try:
                    with deadline(CONFIG["resources"]["seconds_per_pipeline_call"]):
                        pipeline(c0, method, general, capture=False)
                    ready.add(method)
                except Exception as exception:
                    records.append({"method": method, "phase": "warmup", "status": failed_status(exception), "error": str(exception)})
            for repeat in range(CONFIG["timing"]["repeats"]):
                order = ["Gate-only", "ZX"] if repeat % 2 == 0 else ["ZX", "Gate-only"]
                for order_index, method in enumerate(order):
                    if method not in ready:
                        continue
                    record = {"method": method, "phase": "timed", "repeat": repeat, "order_index": order_index}
                    try:
                        with deadline(CONFIG["resources"]["seconds_per_pipeline_call"]):
                            output, stages, _ = pipeline(c0, method, general, capture=False)
                        record.update(stages)
                        qasm_hash = digest(output.to_qasm())
                        record["output_sha256"] = qasm_hash
                        if qasm_hash == candidate_rows[method]["output_hash"]:
                            record["output_validation"] = "hash_matches_verified_output"
                        else:
                            check = check_output(reference, output)
                            record["output_validation"] = check
                            record["metrics"] = metrics(output, t_applicable=not general)
                            key = f"{method}-timed-{repeat}"
                            outputs[key] = {"qasm": output.to_qasm(), "sha256": qasm_hash}
                            save_json(run_dir / "outputs" / f"{cid}.json", outputs)
                            if check["status"] != "passed":
                                raise VerificationFailure(check)
                        record["status"] = "passed"
                    except Exception as exception:
                        record.update(status=failed_status(exception), error=f"{type(exception).__name__}: {exception}")
                    records.append(record)
                save_json(run_dir / "timings.json", timings_all)
            for method in METHODS:
                row = candidate_rows[method]
                successful = [r["total_ms"] for r in records if r["method"]==method and r.get("phase")=="timed" and r["status"]=="passed"]
                row["timed_repeats"] = len(successful)
                if successful:
                    row.update(optimization_ms_median=median(successful), optimization_ms_min=min(successful), optimization_ms_max=max(successful),
                               timing_status="complete" if len(successful)==CONFIG["timing"]["repeats"] else "partial")
                elif method != "Original" and method in candidates:
                    row["timing_status"] = "failed"
                writer.writerow(row)
                file.flush()
                rows.append(row)
                print(f"  {method}: {row['status']}; T={row['t_count']} 2Q={row['two_q_count']} depth={row['depth']} time_ms={row['optimization_ms_median']}", flush=True)
            save_json(run_dir / "timings.json", timings_all)
            save_json(run_dir / "records" / f"{cid}.json", list(candidate_rows.values()))
    finish = now()
    metadata.update(state="completed", finished_utc=finish.isoformat(), finished_jst=finish.astimezone(JST).isoformat(),
                    wall_seconds=(finish-start).total_seconds(), rows_written=len(rows),
                    status_counts=dict(Counter(row["status"] for row in rows)),
                    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save_json(run_dir / "metadata.json", metadata)
    print(json.dumps({"run_id": run_id, "run_directory": str(run_dir), "status_counts": metadata["status_counts"]}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    if zx.__version__ != CONFIG["pyzx_version"] or np.__version__ != CONFIG["numpy_version"]:
        raise RuntimeError("Version mismatch; use requirements.txt")
    manifest = prepare_manifest()
    if args.prepare:
        print(json.dumps({"manifest": CONFIG["input_manifest"], "inputs": manifest["count"], "families": manifest["family_counts"]}, indent=2))
        return
    if args.code_commit is None:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
        args.code_commit = p.stdout.strip() if p.returncode==0 else None
    if args.code_commit is None:
        if args.smoke:
            args.code_commit = "uncommitted-development"
        else:
            raise RuntimeError("Full run requires --code-commit or a git checkout")
    run(args, manifest)


if __name__ == "__main__":
    main()
