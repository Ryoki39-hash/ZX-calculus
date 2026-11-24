#!/usr/bin/env python3
"""Replay four preselected Stage 2 extraction cases after benchmark completion.

This diagnostic reads the saved reduced graphs. It wraps the installed PyZX
helpers, calls their original implementations, and never changes their choices.
No simplification or optimization benchmark is rerun. Diagnostic execution is
excluded from every primary timing statistic. Raw run artifacts are read-only.

Example (set all three BLAS thread variables to 1 before Python starts):
  python benchmarks/controlled_followup/trace_extraction.py \
      --run-id stage2-YYYYMMDDTHHMMSSZ --code-commit FULL_COMMIT_SHA
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256
import importlib.util
import inspect
import json
import os
from pathlib import Path
import resource
import signal
import traceback
from unittest.mock import patch
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pyzx as zx
from pyzx.graph.jsonparser import json_to_graph
from pyzx.linalg import Mat2


ROOT = Path(__file__).resolve().parents[2]
SEMANTICS_PATH = ROOT / "benchmarks" / "broad_screening" / "semantics.py"
_spec = importlib.util.spec_from_file_location("zx_stage2_trace_semantics", SEMANTICS_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load {SEMANTICS_PATH}")
semantics = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semantics)
CASES = (
    "stage2_phase_4q_L80_s100",
    "stage2_phase_8q_L80_s100",
    "stage2_tof_ladder_5q",
    "stage2_qft_5q",
)
JST = ZoneInfo("Asia/Tokyo")


def digest(value):
    return sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def canonical_digest(value):
    """Sort dictionary keys, retaining vertex/edge/row/column list order."""
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class ArtifactReader:
    """Read exact bytes from the run directory, or its published artifact ZIP."""

    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.accessed = {}

    def read_json(self, relative):
        path = self.run_dir / relative
        if path.is_file():
            raw = path.read_bytes()
            location = path.relative_to(ROOT).as_posix()
        else:
            archive = self.run_dir / "artifacts.zip"
            with ZipFile(archive) as packed:
                raw = packed.read(relative)
            location = archive.relative_to(ROOT).as_posix() + "::" + relative
        self.accessed[relative] = {"sha256": digest(raw), "read_from": location}
        return json.loads(raw)


@contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise TimeoutError(f"Diagnostic operation exceeded {seconds} seconds")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def gate_dict(gate):
    data = {"name": gate.name}
    for key in ("control", "target", "ctrl1", "ctrl2"):
        if hasattr(gate, key):
            data[key] = int(getattr(gate, key))
    if hasattr(gate, "phase"):
        data["phase_pi"] = str(gate.phase)
    if hasattr(gate, "adjoint") and isinstance(gate.adjoint, bool):
        data["adjoint"] = gate.adjoint
    return data


def gates_dict(gates):
    return [gate_dict(gate) for gate in gates]


def counts(gates):
    return dict(Counter(gate["name"] for gate in gates))


def matrix_data(matrix):
    return [[int(bit) for bit in row] for row in matrix.data]


def frontier_data(frontier, qubit_map):
    return [{"vertex": int(v), "qubit": int(qubit_map[v])} for v in frontier]


def graph_counts(graph):
    return {"vertices": graph.num_vertices(), "edges": graph.num_edges()}


class ExtractionTrace:
    """Observe actual helper arguments/results without reimplementing extraction."""

    def __init__(self):
        self.events = []
        self.round = 0
        self.accumulator_gates = []
        self.prefix_gates = []
        self.active_application = None
        self.active_matrix = None

    def event(self, kind, **fields):
        event = {"event": len(self.events) + 1, "round": self.round, "kind": kind, **fields}
        self.events.append(event)
        return event

    @contextmanager
    def installed(self):
        extract = zx.extract
        originals = {name: getattr(extract, name) for name in (
            "clean_frontier", "neighbors_of_frontier", "remove_gadget", "bi_adj",
            "greedy_reduction", "column_optimal_swap", "filter_duplicate_cnots",
            "apply_cnots", "graph_to_swaps",
        )}
        original_row_add = Mat2.row_add
        original_to_cnots = Mat2.to_cnots

        @wraps(originals["clean_frontier"])
        def clean_frontier(g, c, frontier, qubit_map, optimize_czs=True):
            self.round += 1
            initial_size = len(c.gates)
            event = self.event(
                "clean_frontier", frontier=frontier_data(frontier, qubit_map),
                graph_before=graph_counts(g), optimize_czs=optimize_czs,
                frontier_phases=[{"vertex": int(v), "phase_pi": str(g.phase(v))} for v in frontier],
                frontier_edges=[{"vertices": [int(v), int(w)],
                                 "qubits": [int(qubit_map[v]), int(qubit_map[w])],
                                 "edge_type": int(g.edge_type(g.edge(v, w)))}
                                for i, v in enumerate(frontier) for w in frontier[i + 1:]
                                if g.connected(v, w)],
            )
            result = originals["clean_frontier"](g, c, frontier, qubit_map, optimize_czs)
            emitted = gates_dict(c.gates[initial_size:])
            self.accumulator_gates.extend(emitted)
            event.update(emitted_gates=emitted, emitted_gate_counts=counts(emitted),
                         reported_czs_saved=int(result), graph_after=graph_counts(g))
            return result

        @wraps(originals["neighbors_of_frontier"])
        def neighbors_of_frontier(g, frontier):
            event = self.event("neighbors_of_frontier", frontier_before=list(frontier),
                               graph_before=graph_counts(g))
            result = originals["neighbors_of_frontier"](g, frontier)
            event.update(frontier_after=list(frontier), neighbors_iteration_order=list(result),
                         graph_after=graph_counts(g))
            return result

        @wraps(originals["remove_gadget"])
        def remove_gadget(g, frontier, qubit_map, neighbor_set, gadgets):
            event = self.event("remove_gadget", frontier_before=frontier_data(frontier, qubit_map),
                               gadget_centers_before=list(gadgets), graph_before=graph_counts(g))
            result = originals["remove_gadget"](g, frontier, qubit_map, neighbor_set, gadgets)
            event.update(gadget_removed=bool(result), frontier_after=frontier_data(frontier, qubit_map),
                         gadget_centers_after=list(gadgets), graph_after=graph_counts(g))
            return result

        @wraps(originals["bi_adj"])
        def bi_adj(g, vs, ws):
            result = originals["bi_adj"](g, vs, ws)
            self.event("bi_adj", row_frontier_vertices=list(ws), column_neighbor_vertices=list(vs),
                       matrix=matrix_data(result))
            return result

        @wraps(originals["greedy_reduction"])
        def greedy_reduction(m):
            event = self.event("greedy_reduction", matrix_before=matrix_data(m))
            result = originals["greedy_reduction"](m)
            event.update(chosen_row_xors=None if result is None else [list(pair) for pair in result],
                         matrix_after=matrix_data(m))
            return result

        @wraps(originals["column_optimal_swap"])
        def column_optimal_swap(m):
            event = self.event("column_optimal_swap", matrix=matrix_data(m))
            result = originals["column_optimal_swap"](m)
            event["returned_permutation"] = {str(k): int(v) for k, v in result.items()}
            return result

        @wraps(originals["filter_duplicate_cnots"])
        def filter_duplicate_cnots(cnots):
            event = self.event("filter_duplicate_cnots", candidates_before=gates_dict(cnots))
            result = originals["filter_duplicate_cnots"](cnots)
            event["candidates_after"] = gates_dict(result)
            return result

        @wraps(original_to_cnots)
        def to_cnots(m, *args, **kwargs):
            event = self.event("matrix_to_cnots_candidates", matrix=matrix_data(m),
                               positional_arguments=list(args), keyword_arguments=kwargs)
            result = original_to_cnots(m, *args, **kwargs)
            event["candidate_cnots"] = gates_dict(result)
            return result

        @wraps(original_row_add)
        def row_add(m, source, target):
            # Only actual graph-updating XORs are counted. Trial eliminations in
            # to_cnots() are candidates and are not physical output gates.
            if self.active_application is None or m is not self.active_matrix:
                return original_row_add(m, source, target)
            step = {"source_row": int(source), "target_row": int(target),
                    "source_bits": list(m.data[source]), "target_before": list(m.data[target])}
            result = original_row_add(m, source, target)
            step["target_after"] = list(m.data[target])
            step["matrix_after"] = matrix_data(m)
            step["xor_identity_matches"] = step["target_after"] == [
                int(a) ^ int(b) for a, b in zip(step["source_bits"], step["target_before"])]
            self.active_application["applied_row_xors"].append(step)
            return result

        @wraps(originals["apply_cnots"])
        def apply_cnots(g, c, frontier, qubit_map, cnots, m, neighbors):
            start = len(c.gates)
            old_frontier = list(frontier)
            event = self.event(
                "apply_cnots", frontier_before=frontier_data(frontier, qubit_map),
                column_neighbor_vertices=list(neighbors), matrix_before=matrix_data(m),
                chosen_cnots_frontier_indices=gates_dict(cnots),
                chosen_cnots_qubits=[{"control": int(qubit_map[frontier[g.control]]),
                                     "target": int(qubit_map[frontier[g.target]])} for g in cnots],
                applied_row_xors=[], graph_before=graph_counts(g),
            )
            self.active_application, self.active_matrix = event, m
            try:
                result = originals["apply_cnots"](g, c, frontier, qubit_map, cnots, m, neighbors)
            finally:
                self.active_application = self.active_matrix = None
            emitted = gates_dict(c.gates[start:])
            self.accumulator_gates.extend(emitted)
            event.update(
                matrix_after=matrix_data(m), frontier_after=frontier_data(frontier, qubit_map),
                extracted_vertices=int(result), emitted_gates=emitted, emitted_gate_counts=counts(emitted),
                graph_after=graph_counts(g),
                unit_rows_before=sum(sum(row) == 1 for row in event["matrix_before"]),
                unit_rows_after=sum(sum(row) == 1 for row in m.data),
                frontier_advances=[{"old_vertex": int(old_frontier[i]),
                                    "new_vertex": int(neighbors[row.index(1)])}
                                   for i, row in enumerate(m.data) if sum(row) == 1],
            )
            return result

        @wraps(originals["graph_to_swaps"])
        def graph_to_swaps(g, no_swaps=False):
            inputs, outputs = list(g.inputs()), list(g.outputs())
            event = self.event(
                "graph_to_swaps", inputs=inputs, outputs=outputs, no_swaps=no_swaps,
                output_to_input_wire={str(q): inputs.index(list(g.neighbors(v))[0])
                                      for q, v in enumerate(outputs)},
                output_edge_types=[int(g.edge_type(g.edge(v, list(g.neighbors(v))[0])))
                                   for v in outputs],
            )
            result = originals["graph_to_swaps"](g, no_swaps)
            self.prefix_gates = gates_dict(result.gates)
            event.update(prefix_gates_in_circuit_order=self.prefix_gates,
                         prefix_gate_counts=counts(self.prefix_gates))
            return result

        wrappers = locals()
        with ExitStack() as stack:
            for name in originals:
                stack.enter_context(patch.object(extract, name, wrappers[name]))
            stack.enter_context(patch.object(Mat2, "row_add", row_add))
            stack.enter_context(patch.object(Mat2, "to_cnots", to_cnots))
            yield self

    def summarize(self, extracted, normalized, t_applicable):
        applications = [e for e in self.events if e["kind"] == "apply_cnots"]
        emitted_by_helper = {}
        for helper in ("clean_frontier", "apply_cnots"):
            emitted_by_helper[helper] = counts(
                [g for event in self.events if event["kind"] == helper for g in event["emitted_gates"]])
        expected_gates = self.prefix_gates + list(reversed(self.accumulator_gates))
        actual_gates = gates_dict(extracted.gates)
        prefix = zx.Circuit(extracted.qubits)
        prefix.gates = extracted.gates[:len(self.prefix_gates)]
        normalized_prefix = semantics.normalize(prefix, allow_general_phases=not t_applicable)
        all_counts = counts(actual_gates)
        expected_2q = all_counts.get("CNOT", 0) + all_counts.get("CZ", 0) + 3 * all_counts.get("SWAP", 0)
        return {
            "rounds": self.round, "matrix_batches": len(applications),
            "applied_row_xors": sum(len(e["applied_row_xors"]) for e in applications),
            "all_applied_row_xors_checked": all(s["xor_identity_matches"] for e in applications for s in e["applied_row_xors"]),
            "vertices_extracted_by_matrix_batches": sum(e["extracted_vertices"] for e in applications),
            "gadget_pivots": sum(len(e["gadget_centers_before"]) - len(e["gadget_centers_after"])
                                  for e in self.events if e["kind"] == "remove_gadget"),
            "emitted_gate_counts_by_helper": emitted_by_helper,
            "permutation_prefix_gate_counts": counts(self.prefix_gates),
            "normalized_prefix_metrics": semantics.metrics(normalized_prefix, t_applicable),
            "raw_extracted_gate_counts": all_counts,
            "raw_gate_accounting_matches": expected_gates == actual_gates,
            "normalized_two_q_accounting_matches": expected_2q == semantics.metrics(normalized, t_applicable)["two_q_count"],
            "czs_saved_reported_by_library": sum(e.get("reported_czs_saved", 0) for e in self.events),
        }


def source_hashes():
    paths = [Path(__file__), SEMANTICS_PATH]
    modules = {"extract.py": zx.extract, "linalg.py": inspect.getmodule(Mat2),
               "jsonparser.py": inspect.getmodule(json_to_graph),
               "base.py": inspect.getmodule(zx.Graph().copy),
               "graph_s.py": inspect.getmodule(type(zx.Graph())),
               "optimize.py": zx.optimize, "gates.py": zx.circuit.gates}
    return {
        "repository_files_sha256": {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in paths},
        "pyzx_module_sha256": {name: digest(Path(inspect.getfile(module)).read_bytes()) for name, module in modules.items()},
    }


def trace_case(cid, reader, protocol, verification_all):
    inputs = reader.read_json(f"inputs/{cid}.json")
    graphs = reader.read_json(f"graphs/{cid}.json")
    outputs = reader.read_json(f"outputs/{cid}.json")
    t_applicable = bool(inputs["spec"]["t_count_applicable"])
    general = not t_applicable
    saved_graph = graphs["graph_after"]
    graph = json_to_graph(saved_graph)
    saved_hash = canonical_digest(saved_graph)
    reloaded_hash = canonical_digest(json.loads(graph.to_json()))
    identity = {"saved_reduced_graph_sha256": saved_hash,
                "reloaded_reduced_graph_sha256": reloaded_hash,
                "serialized_graph_identity_confirmed": saved_hash == reloaded_hash,
                "comparison": "Canonical JSON dictionary keys; vertex and edge array order retained"}
    if saved_hash != reloaded_hash:
        raise ValueError("Reduced-graph JSON round trip differs; exact saved-graph replay not established")
    extraction_graph = graph.copy()  # Exactly the same copy/renumbering step as the benchmark.
    identity["extraction_copy_sha256"] = canonical_digest(json.loads(extraction_graph.to_json()))
    identity["saved_to_extraction_vertex_mapping"] = {
        str(old): int(new) for old, new in zip(graph.vertices(), extraction_graph.vertices())}
    tracer = ExtractionTrace()
    with deadline(protocol["resources"]["seconds_per_pipeline_call"]):
        with tracer.installed():
            extracted = zx.extract_circuit(extraction_graph, **protocol["extraction"])
        normalized = semantics.normalize(extracted, allow_general_phases=general)
    traced_qasm = normalized.to_qasm()
    saved_pre = outputs["ZX-before-cleanup"]
    output_identity = {
        "saved_qasm_sha256": saved_pre["sha256"], "traced_qasm_sha256": digest(traced_qasm),
        "saved_qasm_hash_valid": digest(saved_pre["qasm"]) == saved_pre["sha256"],
        "qasm_hash_matches": digest(traced_qasm) == saved_pre["sha256"],
        "saved_verification": verification_all[cid]["methods"]["ZX-before-cleanup"],
    }
    # Always verify the traced output independently, even on exact QASM match.
    # Circuit.to_matrix() is deliberately not used: its auto strategy may use ZX.
    with deadline(protocol["resources"]["seconds_per_verification"]):
        raw = zx.Circuit.from_qasm(inputs["raw_qasm"])
        verification = semantics.verify(semantics.evaluate(raw), semantics.evaluate(normalized),
                                        atol=protocol["verification"]["atol"])
    stage_metrics = {}
    for method in ("Original", "Gate-only", "ZX-before-cleanup", "ZX"):
        item = outputs[method]
        if digest(item["qasm"]) != item["sha256"]:
            raise ValueError(f"Stored QASM hash is invalid: {cid}/{method}")
        circuit = semantics.normalize(zx.Circuit.from_qasm(item["qasm"]), allow_general_phases=general)
        stage_metrics[method] = semantics.metrics(circuit, t_applicable)
    trace_counts = tracer.summarize(extracted, normalized, t_applicable)
    faithful = (output_identity["saved_qasm_hash_valid"] and output_identity["qasm_hash_matches"]
                and output_identity["saved_verification"]["status"] == "passed"
                and verification["status"] == "passed"
                and trace_counts["raw_gate_accounting_matches"]
                and trace_counts["normalized_two_q_accounting_matches"]
                and trace_counts["all_applied_row_xors_checked"])
    result = {
        "circuit_id": cid, "status": "exact_verified_replay" if faithful else "replay_requires_review",
        "spec": inputs["spec"], "graph_identity": identity, "output_identity": output_identity,
        "verification": verification, "stage_metrics": stage_metrics,
        "graph_counts": {"before_simplification": {"vertices": len(graphs["graph_before"]["vertices"]),
                                                    "edges": len(graphs["graph_before"]["edges"])},
                         "after_simplification": graph_counts(graph)},
        "trace_counts": trace_counts, "events": tracer.events,
        "extracted_raw_qasm": extracted.to_qasm(), "normalized_extracted_qasm": traced_qasm,
    }
    return result


def fmt(value):
    return "N/A" if value is None else str(value)


def case_markdown(result):
    cid = result["circuit_id"]
    lines = [f"# Extraction trace: {cid}", "", f"Status: **{result['status']}**.", ""]
    if "error" in result:
        return "\n".join(lines + [result["error"], ""])
    lines += ["The trace replays the saved reduced graph with the frozen extraction settings. "
              "All values below describe an untimed diagnostic; primary runtime measurements are unchanged.", "",
              "## Stage metrics", "", "| Stage | T | 2Q | CNOT | CZ | Depth |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, item in result["stage_metrics"].items():
        lines.append(f"| {name} | {fmt(item['t_count'])} | {item['two_q_count']} | {item['cnot_count']} | {item['cz_count']} | {item['depth']} |")
    graphs, tally = result["graph_counts"], result["trace_counts"]
    lines += ["", f"Graph vertices/edges before simplification: {graphs['before_simplification']['vertices']}/"
              f"{graphs['before_simplification']['edges']}; after: {graphs['after_simplification']['vertices']}/"
              f"{graphs['after_simplification']['edges']}.", "",
              "## Gate emission accounting", "",
              "| Origin | CNOT | CZ | H | ZPhase | SWAP |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    origins = {**tally["emitted_gate_counts_by_helper"], "permutation/boundary prefix": tally["permutation_prefix_gate_counts"]}
    for name, item in origins.items():
        lines.append(f"| {name} | {item.get('CNOT', 0)} | {item.get('CZ', 0)} | {item.get('HAD', 0)} | {item.get('ZPhase', 0)} | {item.get('SWAP', 0)} |")
    lines += ["", "Each prefix SWAP becomes three CNOTs in the common normalization. "
              "Candidate CNOT lists from trial elimination are not added to emitted-gate totals. "
              "Emission order is PyZX's internal extraction order; the library reverses the main "
              "gate list before return and prepends the permutation/boundary circuit. No alternative "
              "extraction-direction condition is introduced.", "",
              f"Raw gate-order accounting matches: `{tally['raw_gate_accounting_matches']}`. "
              f"Normalized 2Q accounting matches: `{tally['normalized_two_q_accounting_matches']}`.", "",
              "## Actual matrix batches", "",
              "Rows are ordered frontier vertices; columns are the ordered interior neighbors. "
              "An extractable row has exactly one 1. A recorded XOR is an actual operation on the "
              "matrix used to update the graph, not a discarded candidate operation.", "",
              "| Round | Matrix rows × columns | Unit rows before → after | Applied XOR / CNOT | Emitted H | Extracted vertices |",
              "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    applications = [e for e in result["events"] if e["kind"] == "apply_cnots"]
    for event in applications:
        matrix = event["matrix_before"]
        lines.append(f"| {event['round']} | {len(matrix)} × {len(matrix[0]) if matrix else 0} | "
                     f"{event['unit_rows_before']} → {event['unit_rows_after']} | {len(event['applied_row_xors'])} | "
                     f"{event['emitted_gate_counts'].get('HAD', 0)} | {event['extracted_vertices']} |")
    first_xor = next((e for e in applications if e["applied_row_xors"]), None)
    if first_xor:
        step = first_xor["applied_row_xors"][0]
        bits = lambda row: "".join(str(bit) for bit in row)
        lines += ["", f"First actual XOR (round {first_xor['round']}): source row {step['source_row']} "
                  f"`{bits(step['source_bits'])}` is XORed into target row {step['target_row']} "
                  f"`{bits(step['target_before'])}`, producing `{bits(step['target_after'])}`. "
                  "The full before/after matrices, frontier-to-wire mapping, and emitted CNOT are in the accompanying JSON."]
    output = result["output_identity"]
    lines += ["", "## Replay checks", "",
              f"- Saved graph JSON round-trip identity: `{result['graph_identity']['serialized_graph_identity_confirmed']}`.",
              f"- Normalized output QASM hash matches saved ZX-before-cleanup: `{output['qasm_hash_matches']}`.",
              f"- Saved QASM SHA-256: `{output['saved_qasm_sha256']}`.",
              f"- Replayed QASM SHA-256: `{output['traced_qasm_sha256']}`.",
              f"- Independent dense verification: `{result['verification']['status']}`; "
              f"maximum residual `{result['verification']['max_abs_residual']}`.", "",
              "## Interpretation limits", "",
              "These observations locate emitted gates and cleanup changes within this fixed pipeline. "
              "They do not prove a globally minimum CNOT count, that every emitted gate is necessary, "
              "or that a graph-size reduction causes a circuit-cost reduction. Simplification rewrite "
              "steps and all trial Gaussian elimination XORs are not individually logged. "
              "QFT T-count remains N/A because no approximate Clifford+T synthesis is performed.", ""]
    return "\n".join(lines)


def summary_markdown(summary):
    lines = ["# Stage 2 extraction diagnostics", "",
             f"Run: `{summary['run_id']}`. Benchmark source: `{summary['benchmark_code_commit']}`. "
             f"Diagnostic source: `{summary['diagnostic_code_commit']}`.", "",
             "Four cases were fixed by the Stage 2 plan before observing results. "
             "Diagnostics began after the primary run completed and do not contribute to measured runtime.", "",
             "| Input | Replay | Applied row XORs | Matrix CNOT | Frontier CNOT / CZ | Prefix SWAP | 2Q Gate → extracted → cleaned |",
             "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for result in summary["cases"]:
        if "trace_counts" not in result:
            lines.append(f"| {result['circuit_id']} | {result['status']} | N/A | N/A | N/A | N/A | N/A |")
            continue
        tally = result["trace_counts"]
        application = tally["emitted_gate_counts_by_helper"]["apply_cnots"]
        frontier = tally["emitted_gate_counts_by_helper"]["clean_frontier"]
        metrics = result["stage_metrics"]
        lines.append(f"| [{result['circuit_id']}]({result['circuit_id']}.md) | {result['status']} | "
                     f"{tally['applied_row_xors']} | {application.get('CNOT', 0)} | "
                     f"{frontier.get('CNOT', 0)} / {frontier.get('CZ', 0)} | "
                     f"{tally['permutation_prefix_gate_counts'].get('SWAP', 0)} | "
                     f"{metrics['Gate-only']['two_q_count']} → {metrics['ZX-before-cleanup']['two_q_count']} → {metrics['ZX']['two_q_count']} |")
    lines += ["", "Matrix CNOTs come from actual row-XOR batches. Frontier cleanup can also emit "
              "CNOTs while factoring CZ neighborhoods. Any boundary SWAP contributes three CNOTs "
              "after normalization. Candidate elimination gates are kept separate from emitted gates.", "",
              "The traces show where this implementation creates gates, and the saved stage metrics "
              "show how common cleanup changes their counts. They are diagnostic case studies, not "
              "proofs of causal effects or optimality. Full matrices and hashes are in the per-case JSON files.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--output-dir", type=Path, help="Optional new diagnostic directory; never inside the raw run")
    args = parser.parse_args()
    if not args.run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.run_id):
        raise ValueError("Unsafe run ID")
    if len(args.code_commit) != 40 or any(c not in "0123456789abcdef" for c in args.code_commit):
        raise ValueError("A full lowercase Git commit SHA is required")
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if os.environ.get(name) != "1":
            raise RuntimeError(f"Set {name}=1 before starting Python")
    run_dir = ROOT / "runs" / args.run_id
    reader = ArtifactReader(run_dir)
    metadata = reader.read_json("metadata.json")
    protocol = reader.read_json("protocol.json")
    if metadata.get("state") != "completed" or metadata.get("expected_inputs") != 66:
        raise RuntimeError("Diagnostics require the completed full 66-input Stage 2 run")
    if protocol["protocol_id"] != "stage2-followup-v1":
        raise ValueError("This diagnostic is scoped to stage2-followup-v1")
    hashes = source_hashes()
    compatibility = {"pyzx_version_matches": metadata["pyzx"] == zx.__version__,
                     "pyzx_module_hash_matches": {name: value == metadata["source_hashes"]["pyzx_module_sha256"].get(name)
                                                  for name, value in hashes["pyzx_module_sha256"].items()
                                                  if name in metadata["source_hashes"]["pyzx_module_sha256"]},
                     "semantics_hash_matches": hashes["repository_files_sha256"][SEMANTICS_PATH.relative_to(ROOT).as_posix()]
                         == metadata["source_hashes"]["repository_files_sha256"].get(SEMANTICS_PATH.relative_to(ROOT).as_posix())}
    if not compatibility["pyzx_version_matches"] or not compatibility["semantics_hash_matches"] or not all(compatibility["pyzx_module_hash_matches"].values()):
        raise RuntimeError(f"Diagnostic/benchmark source mismatch: {compatibility}")
    destination = (args.output_dir or ROOT / "analysis" / args.run_id / "diagnostics").resolve()
    if destination == run_dir.resolve() or run_dir.resolve() in destination.parents:
        raise ValueError("Do not write diagnostics into the immutable raw run directory")
    destination.mkdir(parents=True, exist_ok=False)
    cap = protocol["resources"]["address_space_limit_bytes"]
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    start = datetime.now(timezone.utc)
    context = {"run_id": args.run_id, "benchmark_code_commit": metadata["code_commit"],
               "diagnostic_code_commit": args.code_commit, "protocol_id": protocol["protocol_id"],
               "benchmark_finished_utc": metadata["finished_utc"], "started_utc": start.isoformat(),
               "started_jst": start.astimezone(JST).isoformat(), "timezone": "Asia/Tokyo",
               "preselected_cases": list(CASES), "source_hashes": hashes,
               "source_compatibility": compatibility, "timed_benchmark": False,
               "extraction_settings": protocol["extraction"], "state": "running"}
    save_json(destination / "metadata.json", context)
    verification_all = reader.read_json("verification.json")
    compact_results = []
    for cid in CASES:
        try:
            result = trace_case(cid, reader, protocol, verification_all)
        except Exception as exc:
            result = {"circuit_id": cid, "status": "diagnostic_error",
                      "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
        save_json(destination / f"{cid}.json", {**context, "state": "completed", **result})
        (destination / f"{cid}.md").write_text(case_markdown(result), encoding="utf-8")
        compact_results.append({k: v for k, v in result.items()
                                if k not in {"events", "extracted_raw_qasm", "normalized_extracted_qasm", "traceback"}})
        print(json.dumps({"circuit_id": cid, "status": result["status"]}), flush=True)
    finish = datetime.now(timezone.utc)
    context.update(state="completed", finished_utc=finish.isoformat(), finished_jst=finish.astimezone(JST).isoformat(),
                   artifact_sources=reader.accessed, status_counts=dict(Counter(r["status"] for r in compact_results)))
    summary = {**context, "cases": compact_results}
    save_json(destination / "metadata.json", context)
    save_json(destination / "summary.json", summary)
    (destination / "summary.md").write_text(summary_markdown(summary), encoding="utf-8")
    print(json.dumps({"directory": str(destination), "status_counts": context["status_counts"]}), flush=True)
    return 0 if all(r["status"] == "exact_verified_replay" for r in compact_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
