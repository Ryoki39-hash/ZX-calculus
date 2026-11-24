"""Independent definition references and descriptive input structure.

These checks neither optimize circuits nor participate in measured runtime.
All matrices use q0 as the most significant bit.  Definition references are
derived from specification metadata, without PyZX matrix conversion, graph
rewriting, extraction, or gate decomposition.  The main runner compares them
against the independently evaluated raw circuits using the fixed verifier.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
import random
from typing import Any

import numpy as np
from pyzx.circuit.gates import ZPhase


def _phase_definition_operations(spec: dict[str, Any]):
    """Replay the specified RNG stream as abstract CNOT/quarter-phase data."""
    params = spec["generator_parameters"]
    rng = random.Random(spec["seed"])
    n = int(spec["qubits"])
    for _ in range(params["operations"]):
        if rng.random() < params["p_phase"]:
            q = rng.randrange(n)
            numerator = rng.choice(params["phase_numerators"])
            quarter_units = 4 * Fraction(numerator, params["phase_denominator"])
            if quarter_units.denominator != 1:
                raise ValueError("The Stage 2 phase reference requires quarter phases")
            yield ("phase", q, int(quarter_units))
        else:
            a, b = rng.sample(range(n), 2)
            yield ("cnot", a, b)


def _phase_polynomial(n: int, operations) -> dict[str, Any]:
    """Track GF(2) output parities and exact integer phase coefficients."""
    wire_masks = [1 << (n - 1 - q) for q in range(n)]
    coefficients: Counter[int] = Counter()
    visits: Counter[int] = Counter()
    for kind, a, b in operations:
        if kind == "cnot":
            wire_masks[b] ^= wire_masks[a]
        elif kind == "phase":
            mask = wire_masks[a]
            coefficients[mask] += b
            visits[mask] += 1
        else:
            raise ValueError(f"Unknown abstract operation {kind!r}")
    return {
        "wire_masks": wire_masks,
        "coefficients": {mask: count % 8 for mask, count in coefficients.items()},
        "visits": dict(visits),
    }


def _monomial_reference(n: int, polynomial: dict[str, Any]) -> np.ndarray:
    dim = 1 << n
    result = np.zeros((dim, dim), dtype=np.complex128)
    for x in range(dim):
        y = 0
        for mask in polynomial["wire_masks"]:
            y = (y << 1) | ((mask & x).bit_count() & 1)
        phase_quarters = sum(
            coefficient * ((mask & x).bit_count() & 1)
            for mask, coefficient in polynomial["coefficients"].items()
        ) % 8
        result[y, x] = np.exp(1j * np.pi * phase_quarters / 4)
    return result


def definition_reference(spec: dict[str, Any], raw) -> np.ndarray:
    """Build the intended unitary from the definition, independently of raw gates.

    ``raw`` is used only for the dimension check.  Phase inputs replay the
    frozen RNG rule into a GF(2) linear map and a phase polynomial; parity
    inputs use their diagonal parity function; CCX inputs use basis-bit
    permutations; QFT uses the positive discrete Fourier matrix directly.
    """
    n = int(spec["qubits"])
    if int(raw.qubits) != n or n < 1 or n > 8:
        raise ValueError("Definition/reference width mismatch or unsupported width")
    family = spec["family"]
    params = spec["generator_parameters"]
    dim = 1 << n

    if family == "qft":
        indices = np.arange(dim)
        return np.exp(2j * np.pi * np.outer(indices, indices) / dim) / np.sqrt(dim)

    if family in {"toffoli_ladder", "toffoli_overlap"}:
        result = np.zeros((dim, dim), dtype=np.complex128)
        for x in range(dim):
            y = x
            for a, b, c in params["chronological_ccx"]:
                if ((y >> (n - 1 - a)) & 1) and ((y >> (n - 1 - b)) & 1):
                    y ^= 1 << (n - 1 - c)
            result[y, x] = 1
        return result

    if family == "phase":
        return _monomial_reference(n, _phase_polynomial(n, _phase_definition_operations(spec)))

    if family == "parity_reuse":
        masks = [
            sum(1 << (n - 1 - q) for q in support)
            for support in params["chronological_supports"]
        ]
        diagonal = [
            np.exp(1j * np.pi * (sum((mask & x).bit_count() & 1 for mask in masks) % 8) / 4)
            for x in range(dim)
        ]
        return np.diag(np.asarray(diagonal, dtype=np.complex128))

    raise ValueError(f"No independent definition reference for {family!r}")


def _gate_wires(gate) -> tuple[int, ...]:
    if gate.name in {"Tof", "TOF", "CCX", "CCZ"}:
        return (int(gate.ctrl1), int(gate.ctrl2), int(gate.target))
    if gate.name in {"CNOT", "CZ", "CPhase", "SWAP"}:
        return (int(gate.control), int(gate.target))
    if hasattr(gate, "target"):
        return (int(gate.target),)
    raise ValueError(f"Cannot inspect wires for {gate.name!r}")


def _raw_phase_operations(raw):
    for gate in raw.gates:
        if gate.name == "CNOT":
            yield ("cnot", int(gate.control), int(gate.target))
        elif isinstance(gate, ZPhase):
            quarter_units = 4 * Fraction(gate.phase)
            if quarter_units.denominator != 1:
                raise ValueError("Expected exact quarter phases")
            yield ("phase", int(gate.target), int(quarter_units))
        else:
            raise ValueError(f"Non phase-polynomial gate {gate.name!r}")


def input_structure(spec: dict[str, Any], raw) -> dict[str, Any]:
    """Describe raw input features and confounds; no cost optimum is claimed."""
    n = int(spec["qubits"])
    wire_counts = [0] * n
    raw_depths = [0] * n
    gate_names: Counter[str] = Counter()
    cnot_pairs: Counter[tuple[int, int]] = Counter()
    phase_angles: Counter[Fraction] = Counter()
    for gate in raw.gates:
        wires = _gate_wires(gate)
        layer = 1 + max(raw_depths[q] for q in wires)
        for q in wires:
            wire_counts[q] += 1
            raw_depths[q] = layer
        gate_names[gate.name] += 1
        if gate.name == "CNOT":
            cnot_pairs[(int(gate.control), int(gate.target))] += 1
        if isinstance(gate, ZPhase):
            phase_angles[Fraction(gate.phase) % 2] += 1

    methods = {
        "qft": "analytic positive discrete Fourier matrix, q0 MSB",
        "toffoli_ladder": "metadata CCX sequence evaluated as basis-bit permutation",
        "toffoli_overlap": "metadata CCX sequence evaluated as basis-bit permutation",
        "phase": "specified RNG replay into GF(2) linear map and quarter-phase polynomial",
        "parity_reuse": "metadata support parity diagonal, exp(i*pi*sum(parities)/4)",
    }
    result: dict[str, Any] = {
        "definition_reference_method": methods[spec["family"]],
        "raw_gate_count": len(raw.gates),
        "raw_gate_name_counts": dict(sorted(gate_names.items())),
        "active_wires": [q for q, count in enumerate(wire_counts) if count],
        "active_wire_count": sum(count > 0 for count in wire_counts),
        "raw_gate_wire_participation_counts": wire_counts,
        "raw_gate_dependency_depth": max(raw_depths),
        "raw_depth_caveat": "raw composite gates count as one layer; not the normalized comparison depth",
        "ordered_raw_cnot_counts": [
            {"control": a, "target": b, "count": count}
            for (a, b), count in sorted(cnot_pairs.items())
        ],
        "raw_zphase_angle_counts_mod_2pi": [
            {"phase_pi": [phase.numerator, phase.denominator], "count": count}
            for phase, count in sorted(phase_angles.items())
        ],
        "distinct_raw_zphase_angles_mod_2pi": len(phase_angles),
    }

    if spec["family"] in {"phase", "parity_reuse"}:
        polynomial = _phase_polynomial(n, _raw_phase_operations(raw))
        entries = []
        for mask, visits in sorted(polynomial["visits"].items()):
            entries.append({
                "mask_q0_msb": mask,
                "input_wire_support": [q for q in range(n) if mask & (1 << (n - 1 - q))],
                "phase_placement_count": visits,
                "combined_phase_quarters_mod8": polynomial["coefficients"][mask],
            })
        result["phase_polynomial_structure"] = {
            "final_output_linear_map_masks_q0_msb": polynomial["wire_masks"],
            "phase_placement_count": sum(polynomial["visits"].values()),
            "distinct_visited_parities": len(polynomial["visits"]),
            "repeat_visits_to_existing_parities": sum(polynomial["visits"].values()) - len(polynomial["visits"]),
            "parities_with_nonzero_combined_phase": sum(c != 0 for c in polynomial["coefficients"].values()),
            "parities_with_odd_combined_quarter_phase": sum(c % 2 for c in polynomial["coefficients"].values()),
            "parity_terms": entries,
            "interpretation": (
                "descriptive exact phase combination for these input parities; "
                "not a claim of globally minimal T-count or a ZX optimization result"
            ),
        }

    if spec["family"] == "parity_reuse":
        frequencies = Counter(tuple(s) for s in spec["generator_parameters"]["chronological_supports"])
        result["gadget_support_frequencies"] = [
            {"support": list(support), "count": count}
            for support, count in sorted(frequencies.items())
        ]
        result["pair_caveat"] = "paired inputs generally have different unitaries and may differ in active wires/depth"

    if spec["family"] == "toffoli_overlap":
        result["pair_caveat"] = "disjoint uses six active wires; cascade uses four and pads two identity wires"
    return result
