"""Predeclared Stage 2 inputs; construction only, with no optimization.

The 66 inputs implement docs/stage2_followup_plan.md at PLAN_SOURCE_SHA.
Enumeration is A (24), B1 (20), B2 (20), B3 (2).  Repeated input hashes,
should any occur, must be reported rather than removed.  Seeds describe
inputs; timing repetitions do not create additional inputs.

The QFT, Toffoli ladder, and random phase construction loops are copied
unchanged in meaning from the frozen Stage 1 definitions.  The separate
module leaves those historical definitions and results untouched.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import combinations
import random
from typing import Any

import pyzx as zx


DEFINITION_VERSION = "controlled-followup-circuits-v1"
PROTOCOL_ID = "stage2-followup-v1"
PLAN_SOURCE_SHA = "4dbe91ceb5055b9c682d7bfc501879eed34c6925"
PLAN_SOURCE_PATH = "docs/stage2_followup_plan.md"
SEEDS = tuple(range(100, 110))
PHASE_WIDTHS = (4, 8)
PHASE_NUMERATORS = (-3, -2, -1, 1, 2, 3)


def _base_spec(
    circuit_id: str,
    family: str,
    qubits: int,
    generator_parameters: dict[str, Any],
    *,
    batch: str,
    condition: str,
    seed: int | None = None,
    pair_id: str | None = None,
) -> dict[str, Any]:
    return {
        "circuit_id": circuit_id,
        "family": family,
        "qubits": qubits,
        "seed": seed,
        "repetitions": None,
        "batch": batch,
        "condition": condition,
        "pair_id": pair_id,
        "definition_version": DEFINITION_VERSION,
        "protocol_id": PROTOCOL_ID,
        "plan_source": {"path": PLAN_SOURCE_PATH, "commit_sha": PLAN_SOURCE_SHA},
        "generator_parameters": generator_parameters,
        "t_count_applicable": family != "qft",
        "convention": {
            "wire_order": "q0 is the most significant bit; fixed input/output order",
            "pyzx_phase_unit": "pi",
            "input_status": "raw generated input; no optimizer applied",
            "reference_pyzx_version": "0.10.8",
            "input_filtering": "none; repetitions and duplicate hashes retained",
        },
    }


def _phase_spec(n: int, operations: int, seed: int, batch: str) -> dict[str, Any]:
    spec = _base_spec(
        f"stage2_phase_{n}q_L{operations}_s{seed}", "phase", n,
        {
            "generator": "random_cnot_zphase_v1",
            "inherited_definition_path": "benchmarks/broad_screening/circuits.py",
            "inherited_definition_commit": PLAN_SOURCE_SHA,
            "operations": operations,
            "p_phase": 0.4,
            "p_cnot": 0.6,
            "phase_numerators": list(PHASE_NUMERATORS),
            "phase_denominator": 4,
            "rng": "random.Random(seed)",
            "draw_order": (
                "per operation draw rng.random(); if <0.4 draw "
                "target=rng.randrange(n), then numerator="
                "rng.choice([-3,-2,-1,1,2,3]); otherwise draw "
                "[control,target]=rng.sample(range(n),2)"
            ),
            "cnot_connectivity": "uniform ordered distinct qubit pair; all-to-all",
            "input_filtering": "none; accidental repetitions/cancellations retained",
            "prefix_pair": f"stage2_phase_{n}q_L80_s{seed}",
            "prefix_length": 80,
            "cross_width_pairing_caveat": (
                "the same seed at different widths does not fix the gate placement"
            ),
        },
        batch=batch, condition=f"L{operations}", seed=seed,
        pair_id=f"stage2_phase_{n}q_s{seed}",
    )
    spec["operations"] = operations
    return spec


def get_specs() -> list[dict[str, Any]]:
    """Return fresh JSON-serializable dictionaries for all 66 fixed inputs.

    A enumerates phase (width, seed), Toffoli (5q, 7q), QFT (5q, 7q).
    B1 enumerates phase (width, seed); B2 enumerates seed then reuse/unique;
    B3 enumerates disjoint then cascade.  No results affect this order.
    """
    specs: list[dict[str, Any]] = []
    for n in PHASE_WIDTHS:
        for seed in SEEDS:
            specs.append(_phase_spec(n, 80, seed, "A"))

    for n in (5, 7):
        specs.append(_base_spec(
            f"stage2_tof_ladder_{n}q", "toffoli_ladder", n,
            {
                "generator": "overlapping_toffoli_ladder_v1",
                "inherited_definition_path": "benchmarks/broad_screening/circuits.py",
                "inherited_definition_commit": PLAN_SOURCE_SHA,
                "chronological_ccx": [[k, k + 1, k + 2] for k in range(n - 2)],
                "pyzx_raw_gate": "TOF",
                "arithmetic_representativeness": "synthetic ladder only",
                "historical_input_caveat": (
                    "5q occurred in the old pilot; new evaluation protocol, not globally unseen"
                    if n == 5 else "new size relative to the frozen Stage 1 inputs"
                ),
            },
            batch="A", condition="ladder",
        ))

    for n in (5, 7):
        specs.append(_base_spec(
            f"stage2_qft_{n}q", "qft", n,
            {
                "generator": "positive_phase_qft_v1",
                "inherited_definition_path": "benchmarks/broad_screening/circuits.py",
                "inherited_definition_commit": PLAN_SOURCE_SHA,
                "chronological_rule": (
                    "for i=0..n-1: H(i), then CP(control=j,target=i,"
                    "phase_pi=1/2**(j-i)) for j=i+1..n-1"
                ),
                "final_swaps": [[i, n - 1 - i] for i in range(n // 2)],
                "fourier_sign": 1,
                "t_count_reason": (
                    "general-angle exact QFT; no approximate Clifford+T synthesis"
                ),
            },
            batch="A", condition="positive_qft_with_final_swaps",
        ))

    for n in PHASE_WIDTHS:
        for seed in SEEDS:
            specs.append(_phase_spec(n, 160, seed, "B1"))

    support_population = list(combinations(range(6), 3))
    for seed in SEEDS:
        sampled = random.Random(seed).sample(support_population, 8)
        for condition in ("reuse", "unique"):
            selected = sampled[:4] * 2 if condition == "reuse" else sampled
            specs.append(_base_spec(
                f"stage2_parity6_{condition}_s{seed}", "parity_reuse", 6,
                {
                    "generator": "paired_weight3_parity_gadgets_v1",
                    "rng": "random.Random(seed)",
                    "sampling_rule": (
                        "sample 8 without replacement from "
                        "list(combinations(range(6),3)) in lexicographic order"
                    ),
                    "support_population": [list(s) for s in support_population],
                    "sampled_supports_A_to_H": [list(s) for s in sampled],
                    "support_order": "ABCDABCD" if condition == "reuse" else "ABCDEFGH",
                    "chronological_supports": [list(s) for s in selected],
                    "gadgets": 8,
                    "phase_pi": [1, 4],
                    "chronological_gadget_rule": (
                        "for sorted a<b<c: CNOT(a,c), CNOT(b,c), T(c), "
                        "CNOT(b,c), CNOT(a,c)"
                    ),
                    "expected_normalized_input_t_count": 8,
                    "expected_normalized_input_two_q_count": 32,
                    "pair_semantics": (
                        "different unitaries in general; verify each against its own Original"
                    ),
                    "representativeness": "synthetic parity-reuse mechanism diagnostic",
                    "unmatched_features": (
                        "support frequencies, active wires, connectivity and depth are recorded, "
                        "not assumed to match"
                    ),
                },
                batch="B2", condition=condition, seed=seed,
                pair_id=f"stage2_parity6_s{seed}",
            ))

    for condition, sequence in (
        ("disjoint", [[0, 1, 2], [3, 4, 5]]),
        ("cascade", [[0, 1, 2], [1, 2, 3]]),
    ):
        specs.append(_base_spec(
            f"stage2_tof6_{condition}2", "toffoli_overlap", 6,
            {
                "generator": "paired_toffoli_overlap_v1",
                "chronological_ccx": sequence,
                "pyzx_raw_gate": "TOF",
                "expected_normalized_input_t_count": 14,
                "expected_normalized_input_two_q_count": 12,
                "declared_active_wires": sorted({q for gate in sequence for q in gate}),
                "unmatched_features": "active wire count: disjoint=6, cascade=4",
                "historical_input_caveat": (
                    "cascade is the Stage 1 4q ladder padded with two identity wires"
                    if condition == "cascade" else "two independent CCX gates"
                ),
                "representativeness": "diagnostic pair, not independent algorithm samples",
            },
            batch="B3", condition=condition, pair_id="stage2_tof6_overlap_pair",
        ))
    return specs


def build_circuit(spec: dict[str, Any]) -> zx.Circuit:
    """Construct one raw input, without normalization or optimization."""
    n = int(spec["qubits"])
    family = spec["family"]
    params = spec["generator_parameters"]
    circuit = zx.Circuit(n)

    if family == "qft":
        for i in range(n):
            circuit.add_gate("HAD", i)
            for j in range(i + 1, n):
                circuit.add_gate("CPhase", j, i, Fraction(1, 2 ** (j - i)))
        for a, b in params["final_swaps"]:
            circuit.add_gate("SWAP", a, b)

    elif family in {"toffoli_ladder", "toffoli_overlap"}:
        for a, b, target in params["chronological_ccx"]:
            circuit.add_gate("TOF", a, b, target)

    elif family == "phase":
        rng = random.Random(spec["seed"])
        for _ in range(params["operations"]):
            if rng.random() < params["p_phase"]:
                target = rng.randrange(n)
                numerator = rng.choice(params["phase_numerators"])
                circuit.add_gate("ZPhase", target,
                                 Fraction(numerator, params["phase_denominator"]))
            else:
                control, target = rng.sample(range(n), 2)
                circuit.add_gate("CNOT", control, target)

    elif family == "parity_reuse":
        for a, b, c in params["chronological_supports"]:
            circuit.add_gate("CNOT", a, c)
            circuit.add_gate("CNOT", b, c)
            circuit.add_gate("T", c)
            circuit.add_gate("CNOT", b, c)
            circuit.add_gate("CNOT", a, c)

    else:
        raise ValueError(f"Unknown Stage 2 circuit family {family!r}")
    return circuit
