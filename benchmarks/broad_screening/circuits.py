"""Frozen input definitions for the 33-input Stage 1 benchmark.

This module constructs inputs only: no simplification, extraction, cleanup,
performance measurement, candidate selection, or direction reversal occurs here.
The public API is ``get_specs()`` and ``build_circuit(spec)``.  All specification
metadata is JSON serializable and records the generation rules before results
are inspected.  PyZX 0.10.8 is the reference implementation.

Conventions
-----------
* Wire q0 is the most significant bit in independent matrix references.
* QFT has positive Fourier phases and explicit final reversal SWAPs.
* Every phase parameter passed to PyZX is a rational multiple of pi.
* Pauli rotations mean R_P(theta) = exp(-i theta P / 2).  The implemented
  CNOT/ZPhase/CNOT gadget differs from that rotation by exp(i theta / 2),
  because PyZX ZPhase(theta/pi) = diag(1, exp(i theta)).  The known total
  global phase is recorded; verification must allow only a unit-modulus global
  phase, not an arbitrary scalar.
* Seeds identify generated inputs; timing repetitions never create new inputs.
"""

from __future__ import annotations

from fractions import Fraction
import random
from typing import Any

import pyzx as zx


DEFINITION_VERSION = "broad-screening-circuits-v1"
QUBIT_COUNTS = (4, 6, 8)
SEEDS = (0, 1, 2)
PAULI_REPETITIONS = (2, 4, 8)
PHASE_NUMERATORS = (-3, -2, -1, 1, 2, 3)


def _base_spec(
    circuit_id: str,
    family: str,
    qubits: int,
    generator_parameters: dict[str, Any],
    *,
    seed: int | None = None,
    repetitions: int | None = None,
) -> dict[str, Any]:
    return {
        "circuit_id": circuit_id,
        "family": family,
        "qubits": qubits,
        "seed": seed,
        "repetitions": repetitions,
        "definition_version": DEFINITION_VERSION,
        "generator_parameters": generator_parameters,
        "t_count_applicable": family != "qft",
        "convention": {
            "wire_order": "q0 is the most significant bit; fixed input/output order",
            "pyzx_phase_unit": "pi",
            "input_status": "raw generated input; no optimizer applied",
        },
    }


def _pauli_block(qubits: int) -> list[dict[str, Any]]:
    """Return the chronological list of joint rotations in one block."""
    return [
        {
            "qubits": [k, k + 1],
            "axis": "ZZ" if k % 2 == 0 else "XX",
            "theta_pi": [1 if (k // 2) % 2 == 0 else -1, 4],
        }
        for k in range(qubits - 1)
    ]


def get_specs() -> list[dict[str, Any]]:
    """Return fresh metadata dictionaries for exactly 33 planned inputs.

    Order is QFT, Toffoli ladder, phase circuits, repeated Pauli rotations,
    random Clifford+T; within each family, qubit count then seed/repetition.
    This fixed enumeration performs no outcome-dependent input selection.
    """
    specs: list[dict[str, Any]] = []

    for n in QUBIT_COUNTS:
        specs.append(_base_spec(
            f"qft_{n}q", "qft", n,
            {
                "generator": "positive_phase_qft_v1",
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
        ))

    for n in QUBIT_COUNTS:
        specs.append(_base_spec(
            f"tof_ladder_{n}q", "toffoli_ladder", n,
            {
                "generator": "overlapping_toffoli_ladder_v1",
                "chronological_ccx": [[k, k + 1, k + 2] for k in range(n - 2)],
                "pyzx_raw_gate": "TOF",
                "arithmetic_representativeness": "synthetic ladder only",
            },
        ))

    for n in QUBIT_COUNTS:
        for seed in SEEDS:
            specs.append(_base_spec(
                f"phase_{n}q_s{seed}", "phase", n,
                {
                    "generator": "random_cnot_zphase_v1",
                    "operations": 80,
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
                },
                seed=seed,
            ))

    for n in QUBIT_COUNTS:
        for repetitions in PAULI_REPETITIONS:
            block = _pauli_block(n)
            global_phase_pi = repetitions * sum(
                (Fraction(*term["theta_pi"]) / 2 for term in block), Fraction(0)
            )
            specs.append(_base_spec(
                f"pauli_{n}q_r{repetitions}", "pauli", n,
                {
                    "generator": "repeated_mixed_pauli_block_v1",
                    "rotation_definition": "R_P(theta)=exp(-i*theta*P/2)",
                    "chronological_block": block,
                    "block_repetitions": repetitions,
                    "block_order": "increasing adjacent-pair index k; repeat whole block",
                    "decomposition": (
                        "ZZ: CNOT(a,b), ZPhase(b,theta/pi), CNOT(a,b); "
                        "XX: H(a),H(b),ZZ-gadget,H(a),H(b)"
                    ),
                    "implemented_unitary": "exp(i*pi*global_phase_relative_to_RP_product_pi)*RP_product",
                    "global_phase_relative_to_RP_product_pi": [
                        global_phase_pi.numerator, global_phase_pi.denominator,
                    ],
                    "chemistry_representativeness": "synthetic mixed-axis block only",
                },
                repetitions=repetitions,
            ))

    for n in QUBIT_COUNTS:
        for seed in SEEDS:
            specs.append(_base_spec(
                f"clifford_t_{n}q_s{seed}", "clifford_t", n,
                {
                    "generator": "pyzx.generate.CNOT_HAD_PHASE_circuit",
                    "reference_pyzx_version": "0.10.8",
                    "depth_argument": 80,
                    "depth_argument_meaning": "number of sampled gate placements, not circuit depth",
                    "p_had": 0.2,
                    "p_t": 0.2,
                    "clifford": False,
                    "sigma": None,
                    "input_filtering": "none; accidental repetitions/cancellations retained",
                },
                seed=seed,
            ))

    return specs


def build_circuit(spec: dict[str, Any]) -> zx.Circuit:
    """Construct the raw input described by one dictionary from get_specs()."""
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

    elif family == "toffoli_ladder":
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

    elif family == "pauli":
        for _ in range(params["block_repetitions"]):
            for term in params["chronological_block"]:
                a, b = term["qubits"]
                axis = term["axis"]
                if axis not in ("ZZ", "XX"):
                    raise ValueError(f"Unsupported Pauli axis {axis!r}")
                if axis == "XX":
                    circuit.add_gate("HAD", a)
                    circuit.add_gate("HAD", b)
                circuit.add_gate("CNOT", a, b)
                circuit.add_gate("ZPhase", b, Fraction(*term["theta_pi"]))
                circuit.add_gate("CNOT", a, b)
                if axis == "XX":
                    circuit.add_gate("HAD", a)
                    circuit.add_gate("HAD", b)

    elif family == "clifford_t":
        circuit = zx.generate.CNOT_HAD_PHASE_circuit(
            qubits=n,
            depth=params["depth_argument"],
            p_had=params["p_had"],
            p_t=params["p_t"],
            clifford=params["clifford"],
            seed=spec["seed"],
            sigma=params["sigma"],
        )

    else:
        raise ValueError(f"Unknown circuit family {family!r}")

    return circuit
