"""Fixed gate semantics, normalization, metrics, and numerical verification.

Matrix evaluation is independent of ZX graph conversion and rewriting.  In
PyZX 0.10.8, Circuit.to_matrix() with its default strategy can call full_reduce;
this module deliberately does not use that verification path.

The basis is |q0 q1 ...>, with q0 most significant.  Gate lists are chronological
and gates multiply the circuit matrix on the left.  PyZX ZPhase(p) denotes
diag(1, exp(i*pi*p)), including its scalar convention.  Equivalence permits
only a unit-magnitude global phase and never an output-wire permutation.
"""

from __future__ import annotations

from fractions import Fraction
from numbers import Integral, Rational

import numpy as np
import pyzx as zx
from pyzx.circuit.gates import CNOT, CZ, HAD, NOT, S, T, XPhase, Z, ZPhase


CANONICAL_NAMES = frozenset({"HAD", "NOT", "Z", "S", "T", "CNOT", "CZ", "ZPhase"})
RAW_COMPOSITE_NAMES = frozenset({"SWAP", "CPhase", "Tof", "TOF", "CCX", "CCZ"})


def _phase(value) -> Fraction:
    """Require exact numerical phases; do not silently approximate floats."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, (Integral, Rational)):
        return Fraction(value)
    raise TypeError(f"Expected an exact rational phase, got {value!r}")


def _check_circuit(circuit: zx.Circuit) -> int:
    if not isinstance(circuit, zx.Circuit):
        raise TypeError("Expected pyzx.Circuit")
    if circuit.bits:
        raise ValueError("Classical bits, measurements, and hybrid circuits are unsupported")
    n = int(circuit.qubits)
    if n < 1:
        raise ValueError("At least one quantum wire is required")
    return n


def _wires(gate, n: int) -> tuple[int, ...]:
    name = gate.name
    if name in {"Tof", "TOF", "CCX", "CCZ"}:
        wires = (gate.ctrl1, gate.ctrl2, gate.target)
    elif name in {"CNOT", "CZ", "SWAP", "CPhase"}:
        wires = (gate.control, gate.target)
    elif name in {"HAD", "H", "NOT"} or isinstance(gate, (ZPhase, XPhase)):
        wires = (gate.target,)
    else:
        raise TypeError(f"Unsupported gate {name!r}")
    if any(not isinstance(q, Integral) or q < 0 or q >= n for q in wires):
        raise ValueError(f"Invalid wire indices for {name}: {wires}")
    if len(set(wires)) != len(wires):
        raise ValueError(f"A gate cannot use the same wire twice: {name}{wires}")
    return tuple(int(q) for q in wires)


def _emit_z(out: zx.Circuit, target: int, phase: Fraction, allow_general: bool) -> None:
    phase %= 2
    k = 4 * phase
    if k.denominator != 1:
        if not allow_general:
            raise ValueError(f"Phase {phase}*pi is outside the exact Clifford+T basis")
        out.gates.append(ZPhase(target, phase))
        return
    # Each odd quarter phase uses exactly one T or T-dagger.  For 3pi/4,
    # for example, Z followed by T-dagger is exact, with no scalar change.
    constructors = {
        0: (),
        1: (lambda: T(target),),
        2: (lambda: S(target),),
        3: (lambda: Z(target), lambda: T(target, adjoint=True)),
        4: (lambda: Z(target),),
        5: (lambda: Z(target), lambda: T(target)),
        6: (lambda: S(target, adjoint=True),),
        7: (lambda: T(target, adjoint=True),),
    }
    out.gates.extend(make() for make in constructors[int(k)])


def normalize(circuit: zx.Circuit, allow_general_phases: bool) -> zx.Circuit:
    """Decompose into the fixed basis, preserving gate order and wire labels.

    No cancellation, commutation, or reordering is performed.  The output is a
    new circuit with fresh gates, so neither the input nor its gates are mutated.
    General X phases are explicitly converted to H-ZPhase-H because PyZX's
    to_basic_gates() leaves them as XPhase gates.
    """
    n = _check_circuit(circuit)
    out = zx.Circuit(n, name=circuit.name)

    def visit(gate, level=0):
        if level > 8:
            raise ValueError("Unexpected recursive gate decomposition")
        wires = _wires(gate, n)
        name = gate.name
        if name in {"HAD", "H"}:
            out.gates.append(HAD(wires[0]))
        elif isinstance(gate, ZPhase):
            _emit_z(out, wires[0], _phase(gate.phase), allow_general_phases)
        elif isinstance(gate, XPhase):
            phase = _phase(gate.phase) % 2
            if phase == 0:
                return
            if phase == 1:
                out.gates.append(NOT(wires[0]))
            else:
                out.gates.append(HAD(wires[0]))
                _emit_z(out, wires[0], phase, allow_general_phases)
                out.gates.append(HAD(wires[0]))
        elif name == "CNOT":
            out.gates.append(CNOT(*wires))
        elif name == "CZ":
            out.gates.append(CZ(*wires))
        elif name in RAW_COMPOSITE_NAMES:
            for child in gate.to_basic_gates():
                visit(child, level + 1)
        else:
            raise TypeError(f"Unsupported gate {name!r}")

    for original_gate in circuit.gates:
        visit(original_gate)
    _validate_canonical(out, allow_general_phases)
    return out


def _validate_canonical(circuit: zx.Circuit, allow_general: bool) -> None:
    n = _check_circuit(circuit)
    for gate in circuit.gates:
        name = gate.name
        if name not in CANONICAL_NAMES:
            raise TypeError(f"Noncanonical gate {name!r}; normalize before counting")
        _wires(gate, n)
        if isinstance(gate, ZPhase):
            p = _phase(gate.phase) % 2
            expected = {"Z": {Fraction(1)}, "S": {Fraction(1, 2), Fraction(3, 2)},
                        "T": {Fraction(1, 4), Fraction(7, 4)}}
            if name in expected and p not in expected[name]:
                raise ValueError(f"Inconsistent {name} phase: {p}")
            if name == "ZPhase" and (not allow_general or (4*p).denominator == 1):
                raise ValueError(f"Noncanonical or disallowed general Z phase: {p}")
        elif name == "NOT" and _phase(gate.phase) % 2 != 1:
            raise ValueError("Inconsistent NOT phase")


def metrics(circuit: zx.Circuit, t_applicable: bool) -> dict:
    """Count only a validated, normalized basis, including logical wire depth.

    Depth is the earliest dependency layer of the given chronological gate list;
    it does not add architecture routing or further commute any gates.  General
    non-Clifford rotations are counted as a supplementary statistic, never
    interpreted as synthesized T cost.  QFT rows must set t_applicable=False.
    """
    _validate_canonical(circuit, allow_general=not t_applicable)
    depths = [0] * circuit.qubits
    cnot = cz = t_count = non_clifford = 0
    for gate in circuit.gates:
        wires = _wires(gate, circuit.qubits)
        layer = max(depths[q] for q in wires) + 1
        for q in wires:
            depths[q] = layer
        cnot += gate.name == "CNOT"
        cz += gate.name == "CZ"
        t_count += gate.name == "T"
        if isinstance(gate, ZPhase) and (_phase(gate.phase) % 2).denominator > 2:
            non_clifford += 1
    return {
        "t_count": int(t_count) if t_applicable else None,
        "two_q_count": int(cnot + cz),
        "cnot_count": int(cnot),
        "cz_count": int(cz),
        "depth": int(max(depths)),
        "total_gates": len(circuit.gates),
        "non_clifford_rotations": int(non_clifford),
    }


def evaluate(circuit: zx.Circuit) -> np.ndarray:
    """Evaluate a 1--8 wire raw or normalized circuit without ZX rewriting.

    Local gates update rows of the accumulated identity matrix.  No full embedded
    gate matrix is formed, and no input-state sampling or wire permutation is
    used.  CP, CCX, and SWAP are evaluated directly, independently of the PyZX
    decomposition used by normalize().
    """
    n = _check_circuit(circuit)
    if n > 8:
        raise ValueError("This full-matrix verifier is restricted to at most 8 qubits")
    dim = 1 << n
    rows = np.arange(dim)
    matrix = np.eye(dim, dtype=np.complex128)
    sqrt2 = np.sqrt(2.0)
    for gate in circuit.gates:
        wires = _wires(gate, n)
        masks = [1 << (n - 1 - q) for q in wires]
        name = gate.name
        if name in {"HAD", "H"}:
            low = rows[(rows & masks[0]) == 0]
            high = low | masks[0]
            a, b = matrix[low].copy(), matrix[high].copy()
            matrix[low], matrix[high] = (a+b)/sqrt2, (a-b)/sqrt2
        elif isinstance(gate, ZPhase):
            selected = (rows & masks[0]) != 0
            matrix[selected] *= np.exp(1j*np.pi*float(_phase(gate.phase) % 2))
        elif isinstance(gate, XPhase):
            p = _phase(gate.phase) % 2
            if p == 1:
                matrix = matrix[rows ^ masks[0]]
            elif p != 0:
                low = rows[(rows & masks[0]) == 0]
                high = low | masks[0]
                a, b = matrix[low].copy(), matrix[high].copy()
                z = np.exp(1j*np.pi*float(p))
                u, v = (1+z)/2, (1-z)/2
                matrix[low], matrix[high] = u*a+v*b, v*a+u*b
        elif name in {"CNOT", "Tof", "TOF", "CCX"}:
            selected = np.ones(dim, dtype=bool)
            for mask in masks[:-1]:
                selected &= (rows & mask) != 0
            permutation = rows.copy()
            permutation[selected] ^= masks[-1]
            matrix = matrix[permutation]
        elif name in {"CZ", "CPhase", "CCZ"}:
            selected = np.ones(dim, dtype=bool)
            for mask in masks:
                selected &= (rows & mask) != 0
            factor = np.exp(1j*np.pi*float(_phase(gate.phase) % 2)) if name == "CPhase" else -1
            matrix[selected] *= factor
        elif name == "SWAP":
            selected = ((rows & masks[0]) != 0) != ((rows & masks[1]) != 0)
            permutation = rows.copy()
            permutation[selected] ^= masks[0] | masks[1]
            matrix = matrix[permutation]
        else:
            raise TypeError(f"Unsupported gate {name!r}")
    return matrix


def verify(reference_matrix, actual_matrix, atol: float = 1e-9) -> dict:
    """Compare complete unitaries, permitting only a unit global phase.

    An invalid/nonunitary reference is inconclusive.  A nonunitary candidate
    (including a scalar-rescaled unitary) fails.  Nonfinite or malformed inputs
    are inconclusive.  All returned values are JSON safe.
    """
    result = {
        "status": "inconclusive", "reason": None,
        "atol": float(atol) if np.isfinite(atol) else None, "rtol": 0,
        "phase_unit_real": None, "phase_unit_imag": None, "max_abs_residual": None,
        "reference_unitarity_max_abs_error": None, "actual_unitarity_max_abs_error": None,
        "reference_frobenius_norm": None, "actual_frobenius_norm": None,
        "matrix_dimension": None, "wire_order": "q0_most_significant_fixed",
        "global_phase_policy": "unit_magnitude_only_no_permutation",
    }
    if not np.isfinite(atol) or atol <= 0:
        result["reason"] = "invalid_tolerance"
        return result
    try:
        reference = np.asarray(reference_matrix, dtype=np.complex128)
        actual = np.asarray(actual_matrix, dtype=np.complex128)
    except (TypeError, ValueError) as exc:
        result["reason"] = "matrix_conversion_error: " + str(exc)
        return result
    if reference.ndim != 2 or reference.shape[0] != reference.shape[1] or reference.shape[0] == 0:
        result["reason"] = "reference_not_nonempty_square_matrix"
        return result
    if actual.shape != reference.shape:
        result["reason"] = "matrix_shape_mismatch"
        return result
    if not np.isfinite(reference).all() or not np.isfinite(actual).all():
        result["reason"] = "nonfinite_matrix_entries"
        return result
    dim = reference.shape[0]
    result["matrix_dimension"] = int(dim)
    with np.errstate(over="ignore", invalid="ignore"):
        ru = float(np.max(np.abs(reference.conj().T @ reference - np.eye(dim))))
        au = float(np.max(np.abs(actual.conj().T @ actual - np.eye(dim))))
        rn, an = float(np.linalg.norm(reference)), float(np.linalg.norm(actual))
    for key, value in (("reference_unitarity_max_abs_error", ru), ("actual_unitarity_max_abs_error", au),
                       ("reference_frobenius_norm", rn), ("actual_frobenius_norm", an)):
        result[key] = value if np.isfinite(value) else None
    expected_norm = np.sqrt(dim)
    if not np.isfinite(ru) or not np.isfinite(rn) or ru > atol or abs(rn-expected_norm) > atol*expected_norm:
        result["reason"] = "reference_not_numerically_unitary"
        return result
    if not np.isfinite(au) or not np.isfinite(an):
        result.update(status="numeric_mismatch", reason="actual_norm_overflow_or_nonunitarity")
        return result
    # This fit has magnitude exactly one.  It cannot hide scalar amplification.
    overlap = complex(np.vdot(reference, actual))
    phase = overlap / abs(overlap) if abs(overlap) > 0 else 1+0j
    residual = float(np.max(np.abs(actual - phase*reference)))
    result.update(phase_unit_real=float(phase.real), phase_unit_imag=float(phase.imag),
                  max_abs_residual=residual)
    if au > atol or abs(an-expected_norm) > atol*expected_norm:
        result.update(status="numeric_mismatch", reason="actual_not_numerically_unitary")
    elif residual > atol:
        result.update(status="numeric_mismatch", reason="unit_global_phase_residual_exceeds_tolerance")
    else:
        result.update(status="passed", reason="unit_global_phase_equivalence")
    return result


def verifier_controls() -> dict:
    """Known positive/negative controls and direct normalization checks.

    These are correctness checks, not optimization or performance experiments.
    An unexpected outcome raises so that an invalid verifier cannot bless a run.
    """
    cases = []

    def record(name, reference, actual, expected="passed"):
        result = verify(reference, actual)
        cases.append({"control": name, "expected_status": expected, **result})
        if result["status"] != expected:
            raise AssertionError(f"Verifier control {name} failed: {result}")

    ident = np.eye(2, dtype=complex)
    record("accept_unit_global_phase", ident, np.exp(1j*np.pi/7)*ident)
    record("reject_relative_phase_I_vs_Z", ident, np.diag([1, -1]), "numeric_mismatch")
    record("reject_scalar_amplification_I_vs_2I", ident, 2*ident, "numeric_mismatch")
    cx01, cx10 = zx.Circuit(2), zx.Circuit(2)
    cx01.add_gate("CNOT", 0, 1)
    cx10.add_gate("CNOT", 1, 0)
    truth = np.eye(4, dtype=complex)[:, [0, 1, 3, 2]]
    record("CNOT_MSB_truth_table", truth, evaluate(cx01))
    record("reject_swapped_CNOT_control_and_target", evaluate(cx01), evaluate(cx10), "numeric_mismatch")

    qft = zx.Circuit(2)
    qft.add_gate("HAD", 0)
    qft.add_gate("CPhase", 1, 0, Fraction(1, 2))
    qft.add_gate("HAD", 1)
    no_swap = evaluate(qft)
    qft.add_gate("SWAP", 0, 1)
    indices = np.arange(4)
    dft = np.exp(2j*np.pi*np.outer(indices, indices)/4)/2
    record("QFT2_matches_positive_DFT4", dft, evaluate(qft))
    record("reject_QFT_missing_final_SWAP", dft, no_swap, "numeric_mismatch")
    record("normalize_QFT2_decomposition", dft, evaluate(normalize(qft, True)))
    cp = zx.Circuit(2)
    cp.add_gate("CPhase", 0, 1, Fraction(1, 8))
    cp_reference = np.diag([1, 1, 1, np.exp(1j*np.pi/8)])
    record("general_CP_direct_semantics", cp_reference, evaluate(cp))
    record("general_CP_decomposition", cp_reference, evaluate(normalize(cp, True)))

    quarter_metrics = []
    for k in range(8):
        c = zx.Circuit(1)
        c.add_gate("ZPhase", 0, Fraction(k, 4))
        normalized = normalize(c, False)
        expected = np.diag([1, np.exp(1j*np.pi*k/4)])
        record(f"quarter_phase_{k}_over_4", expected, evaluate(normalized))
        m = metrics(normalized, True)
        if m["t_count"] != k % 2:
            raise AssertionError(f"Incorrect T-count for quarter phase {k}: {m}")
        quarter_metrics.append({"phase_pi": f"{k}/4", **m})

    x = zx.Circuit(1)
    x.add_gate("XPhase", 0, Fraction(3, 8))
    h = np.array([[1, 1], [1, -1]], dtype=complex)/np.sqrt(2)
    expected = h @ np.diag([1, np.exp(3j*np.pi/8)]) @ h
    record("general_XPhase_direct_semantics", expected, evaluate(x))
    record("general_XPhase_H_Z_H_normalization", expected, evaluate(normalize(x, True)))
    rejected = False
    try:
        normalize(x, False)
    except ValueError:
        rejected = True
    if not rejected:
        raise AssertionError("A general angle was accepted into the Clifford+T-only basis")

    tof = zx.Circuit(3)
    tof.add_gate("TOF", 0, 1, 2)
    tof_truth = np.eye(8, dtype=complex)[:, [0, 1, 2, 3, 4, 5, 7, 6]]
    record("Toffoli_direct_truth_table", tof_truth, evaluate(tof))
    normalized_tof = normalize(tof, False)
    record("Toffoli_decomposition_truth_table", tof_truth, evaluate(normalized_tof))
    tof_metrics = metrics(normalized_tof, True)
    if tof_metrics["t_count"] != 7 or tof_metrics["two_q_count"] != 6:
        raise AssertionError(f"Unexpected fixed Toffoli decomposition counts: {tof_metrics}")

    return {"status": "passed", "scope": "known_semantics_and_verifier_controls_not_benchmarks",
            "gate_basis": "H_X_Z_S_Sdg_T_Tdg_CNOT_CZ_plus_general_ZPhase_for_QFT",
            "matrix_evaluator": "independent_numpy_gate_row_updates_no_ZX_rewrites",
            "atol": 1e-9, "rtol": 0, "checks": cases,
            "quarter_phase_metrics": quarter_metrics,
            "Toffoli_normalized_metrics": tof_metrics,
            "reject_general_angle_in_Clifford_T_basis": rejected}
