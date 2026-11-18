#!/usr/bin/env python3
"""Render five input-circuit illustrations; never run ZX optimization.

Run from the repository root:
    python scripts/render_circuit_diagrams.py
Optional local previews:
    python scripts/render_circuit_diagrams.py --png-dir /tmp/zx-diagram-previews

All operators use |q0 q1 q2 q3>, q0 most significant. Gate lists are
chronological, so every new gate multiplies the circuit matrix on the left.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from functools import reduce
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pyzx as zx


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs" / "circuits"
PYZX_VERSION = "0.10.8"
SOURCE_PLAN = "58bb57cafeb4c65aa649f64cfc9676673858e0f0"
ATOL = 1e-12
INK = "#182b43"
MUTED = "#53657c"
BLUE = "#e5efff"
PURPLE = "#eee5ff"
TEAL = "#e2f5ed"
matplotlib.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "path",
    "svg.hashsalt": "zx-circuit-illustrations-v1",
    "axes.unicode_minus": False,
})


def gate(kind, *qubits, angle_pi=None, pauli=None):
    item = {"kind": kind, "qubits": list(qubits)}
    if angle_pi is not None:
        item["angle_pi"] = list(angle_pi)
    if pauli is not None:
        item["pauli"] = pauli
    return item


def parity_block(qubits, sign=1):
    target = qubits[-1]
    compute = [gate("CX", control, target) for control in qubits[:-1]]
    return compute + [gate("T" if sign == 1 else "Tdg", target)] + list(reversed(compute))


def make_examples():
    if zx.__version__ != PYZX_VERSION:
        raise RuntimeError(f"Use pyzx=={PYZX_VERSION}; found {zx.__version__}")
    qft = []
    for i in range(4):
        qft.append(gate("H", i))
        for j in range(i + 1, 4):
            # CP is symmetric; the lower wire is drawn as the control.
            qft.append(gate("CP", j, i, angle_pi=(1, 2 ** (j - i))))
    qft += [gate("SWAP", 0, 3), gate("SWAP", 1, 2)]

    pauli_block = [
        gate("RP", 0, 1, angle_pi=(1, 4), pauli="ZZ"),
        gate("RP", 1, 2, angle_pi=(1, 4), pauli="XX"),
        gate("RP", 2, 3, angle_pi=(-1, 4), pauli="ZZ"),
    ]
    params = dict(qubits=4, depth=80, p_had=0.2, p_t=0.2, clifford=False, seed=0)
    random_circuit = zx.generate.CNOT_HAD_PHASE_circuit(**params)
    random_gates = []
    for item in random_circuit.gates:
        if item.name == "CNOT":
            random_gates.append(gate("CX", item.control, item.target))
        elif item.name == "HAD":
            random_gates.append(gate("H", item.target))
        elif item.name == "T":
            random_gates.append(gate("Tdg" if item.adjoint else "T", item.target))
        else:
            raise ValueError(f"Unexpected generator gate: {item}")
    if len(random_gates) != 80:
        raise AssertionError("The random figure must include all 80 gates")
    qasm = random_circuit.to_qasm()

    examples = [
        dict(id="qft_4q", title="01  Quantum Fourier transform", 
             subtitle="4 qubits / 16-point QFT / positive phase / final SWAPs included",
             status="Mathematical input example; no optimization performed",
             gates=qft, groups=[]),
        dict(id="toffoli_ladder_4q", title="02  Toffoli ladder",
             subtitle="4 qubits / two overlapping CCX gates / high-level representation",
             status="Same ladder construction as the historical pilot; not a new benchmark run",
             gates=[gate("CCX", 0, 1, 2), gate("CCX", 1, 2, 3)], groups=[]),
        dict(id="phase_parity_4q", title="03  CNOT + phase circuit",
             subtitle="Illustration: repeated parity A separated by a different parity B",
             status="Teaching example; the experimental random phase generator is not fixed here",
             gates=parity_block([0, 1, 2]) + parity_block([1, 2, 3], -1) + parity_block([0, 1, 2]),
             groups=[
                 dict(start=0, end=5, label=r"A: $x_0\oplus x_1\oplus x_2$", color=PURPLE),
                 dict(start=5, end=10, label=r"B: $x_1\oplus x_2\oplus x_3$", color=TEAL),
                 dict(start=10, end=15, label=r"A: $x_0\oplus x_1\oplus x_2$", color=PURPLE),
             ]),
        dict(id="pauli_repeated_4q", title="04  Repeated Pauli rotations",
             subtitle="Illustration: a mixed ZZ / XX / ZZ block, repeated twice",
             status="Teaching example; this does not freeze the experimental block definition",
             gates=pauli_block + pauli_block,
             groups=[dict(start=0, end=3, label="Block B / repetition 1", color=TEAL),
                     dict(start=3, end=6, label="Block B / repetition 2", color=BLUE)]),
        dict(id="random_clifford_t_4q", title="05  Random Clifford + T circuit",
             subtitle="PyZX 0.10.8 / seed 0 / p(H) = p(T) = 0.2 / ALL 80 generated gates",
             status="Generated input illustration; not an optimization or performance result",
             gates=random_gates, groups=[], generator={"function": "CNOT_HAD_PHASE_circuit",
                  "package": "pyzx", "version": zx.__version__, "parameters": params,
                  "depth_argument_means": "gate_count_not_dependency_depth",
                  "qasm_sha256": hashlib.sha256(qasm.encode()).hexdigest()}),
    ]
    for example in examples:
        example["qubits"] = 4
        example["gate_order"] = "chronological_left_to_right"
    return examples, random_circuit, qasm


I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.diag([1, -1]).astype(complex)


def angle(item):
    numerator, denominator = item["angle_pi"]
    return np.pi * numerator / denominator


def local_matrix(item):
    kind = item["kind"]
    if kind == "H":
        return np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    if kind in ("T", "Tdg"):
        return np.diag([1, np.exp(1j * np.pi / 4 * (1 if kind == "T" else -1))])
    if kind == "RZ":
        a = angle(item)
        return np.diag([np.exp(-0.5j * a), np.exp(0.5j * a)])
    if kind == "CP":
        return np.diag([1, 1, 1, np.exp(1j * angle(item))])
    if kind == "RP":
        pauli = reduce(np.kron, [{"I": I2, "X": X, "Y": Y, "Z": Z}[p] for p in item["pauli"]])
        a = angle(item)
        return np.cos(a / 2) * np.eye(len(pauli)) - 1j * np.sin(a / 2) * pauli
    size = 8 if kind == "CCX" else 4
    perm = list(range(size))
    if kind in ("CX", "CCX"):
        perm[-2], perm[-1] = perm[-1], perm[-2]
    elif kind == "SWAP":
        perm[1], perm[2] = perm[2], perm[1]
    else:
        raise ValueError(kind)
    return np.eye(size, dtype=complex)[:, perm]


def embed(local, qubits, n=4):
    """Embed a local operator; listed qubit order determines its basis order."""
    result = np.zeros((2**n, 2**n), dtype=complex)
    for column in range(2**n):
        bits = [(column >> (n - 1 - q)) & 1 for q in range(n)]
        local_column = sum(bits[q] << (len(qubits) - 1 - k) for k, q in enumerate(qubits))
        for local_row in range(2 ** len(qubits)):
            output = bits.copy()
            for k, q in enumerate(qubits):
                output[q] = (local_row >> (len(qubits) - 1 - k)) & 1
            row = sum(bit << (n - 1 - q) for q, bit in enumerate(output))
            result[row, column] = local[local_row, local_column]
    return result


def unitary(gates):
    result = np.eye(16, dtype=complex)
    for item in gates:
        result = embed(local_matrix(item), item["qubits"]) @ result
    return result


def check_examples(examples, random_circuit):
    j, k = np.meshgrid(np.arange(16), np.arange(16))
    qft_expected = np.exp(2j * np.pi * j * k / 16) / 4
    ladder_expected = np.zeros((16, 16), dtype=complex)
    phase_values = []
    for column in range(16):
        a, b, c, d = [(column >> (3 - q)) & 1 for q in range(4)]
        c1 = c ^ (a & b)
        d1 = d ^ (b & c1)
        ladder_expected[8*a + 4*b + 2*c1 + d1, column] = 1
        phase_values.append(np.exp(1j * np.pi / 4 * (2*(a ^ b ^ c) - (b ^ c ^ d))))

    # Independent gate decomposition of the joint Pauli boxes.
    expanded_pauli = []
    for _ in range(2):
        expanded_pauli += [gate("CX", 0, 1), gate("RZ", 1, angle_pi=(1, 4)), gate("CX", 0, 1)]
        expanded_pauli += [gate("H", 1), gate("H", 2), gate("CX", 1, 2),
                           gate("RZ", 2, angle_pi=(1, 4)), gate("CX", 1, 2), gate("H", 1), gate("H", 2)]
        expanded_pauli += [gate("CX", 2, 3), gate("RZ", 3, angle_pi=(-1, 4)), gate("CX", 2, 3)]
    expected = {
        "qft_4q": ("positive_phase_DFT16_including_final_swaps", qft_expected),
        "toffoli_ladder_4q": ("boolean_map_a_b_cxorab_dxor_b_times_cxorab", ladder_expected),
        "phase_parity_4q": ("diagonal_phase_pi_over_4_times_2parity012_minus_parity123", np.diag(phase_values)),
        "pauli_repeated_4q": ("expanded_CNOT_Rz_and_H_decomposition", unitary(expanded_pauli)),
        "random_clifford_t_4q": ("original_PyZX_generated_circuit_matrix", random_circuit.to_matrix()),
    }
    results = []
    for example in examples:
        matrix = unitary(example["gates"])
        reference_name, reference = expected[example["id"]]
        residual = float(np.max(np.abs(matrix - reference)))
        unitarity = float(np.max(np.abs(matrix.conj().T @ matrix - np.eye(16))))
        if residual > ATOL or unitarity > ATOL:
            raise AssertionError(f"{example['id']}: formula={residual}, unitary={unitarity}")
        results.append(dict(id=example["id"], status="passed", reference=reference_name,
                            matrix_dimension=16, max_abs_difference=residual,
                            unitarity_max_abs_difference=unitarity))
    return dict(scope="Numerical checks of documentation input diagrams only; no ZX optimization or benchmark",
                convention="q0 is MSB; fixed wire order; exact phase comparison (no fitted global phase)",
                atol=ATOL, rtol=0, pyzx=zx.__version__, numpy=np.__version__,
                matplotlib=matplotlib.__version__, checks=results)


def angle_tex(item):
    a = Fraction(*item["angle_pi"])
    sign = "-" if a < 0 else ""
    a = abs(a)
    numerator = r"\pi" if a.numerator == 1 else str(a.numerator) + r"\pi"
    if a.denominator != 1:
        numerator = r"\frac{" + numerator + "}{" + str(a.denominator) + "}"
    return sign + numerator


def draw_target(ax, x, y):
    # Point-sized markers keep controls and targets circular on wide panels.
    ax.plot([x], [y], marker="o", markersize=11, markerfacecolor="white",
            markeredgecolor=INK, markeredgewidth=1.4, zorder=5)
    ax.plot([x], [y], marker="+", markersize=8.5, markeredgewidth=1.3,
            color=INK, zorder=6)


def draw_gate(ax, item, x):
    kind, qs = item["kind"], item["qubits"]
    if kind in ("CX", "CCX", "CP", "SWAP"):
        ax.plot([x, x], [min(qs), max(qs)], color=INK, linewidth=1.25, zorder=3)
    if kind in ("CX", "CCX"):
        for q in qs[:-1]:
            ax.plot([x], [q], marker="o", markersize=4.5, color=INK, zorder=6)
        draw_target(ax, x, qs[-1])
        return
    if kind == "SWAP":
        for q in qs:
            ax.plot([x], [q], marker="x", markersize=9, markeredgewidth=1.5, color=INK, zorder=5)
        return
    if kind == "RP":
        lo, hi = min(qs), max(qs)
        if qs != list(range(lo, hi + 1)):
            raise ValueError("Joint-box renderer requires contiguous ordered wires")
        ax.add_patch(Rectangle((x-.40, lo-.24), .80, hi-lo+.48, facecolor=TEAL,
                               edgecolor="#1b705a", linewidth=1.2, zorder=4))
        ax.text(x, (lo+hi)/2, r"$R_{"+item["pauli"]+"}$"+"\n"+"$"+angle_tex(item)+"$",
                ha="center", va="center", fontsize=11, color=INK, zorder=5, linespacing=1.5)
        return
    if kind == "CP":
        ax.plot([x], [qs[0]], marker="o", markersize=4.5, color=INK, zorder=6)
        q = qs[1]
        label, width, color = "$P(" + angle_tex(item) + ")$", .82, PURPLE
    else:
        q = qs[0]
        label = {"H": "$H$", "T": "$T$", "Tdg": r"$T^\dagger$"}[kind]
        width, color = .48, BLUE if kind == "H" else PURPLE
    ax.add_patch(Rectangle((x-width/2, q-.23), width, .46,
                           facecolor=color, edgecolor=INK, linewidth=1.1, zorder=5))
    ax.text(x, q, label, ha="center", va="center", fontsize=11, color=INK, zorder=6)


def draw_example(example, png_dir=None):
    gates = example["gates"]
    per_panel = 20 if len(gates) > 20 else len(gates)
    panels = (len(gates) + per_panel - 1) // per_panel
    width = max(7.2, min(17.5, 2.0 + per_panel * .82))
    height = 4.3 if panels == 1 else 3.15 * panels + 1.0
    fig, axes = plt.subplots(panels, 1, figsize=(width, height), squeeze=False)
    fig.patch.set_facecolor("white")
    if panels == 1:
        fig.subplots_adjust(left=.055, right=.98, top=.76, bottom=.17)
        fig.text(.045, .945, example["title"], fontsize=17, fontweight="bold", color=INK)
        fig.text(.045, .875, example["subtitle"], fontsize=10, color=MUTED)
    else:
        fig.subplots_adjust(left=.055, right=.98, top=.91, bottom=.075, hspace=.34)
        fig.text(.045, .968, example["title"], fontsize=18, fontweight="bold", color=INK)
        fig.text(.045, .941, example["subtitle"], fontsize=11, color=MUTED)
    for panel, ax in enumerate(axes[:, 0]):
        start = panel * per_panel
        chunk = gates[start:start+per_panel]
        length = len(chunk)
        ax.set_xlim(-.4, length+.7)
        ax.set_ylim(3.8, -1.08)
        ax.axis("off")
        for group in example["groups"]:
            x0, x1 = group["start"]+.52, group["end"]+.48
            ax.add_patch(Rectangle((x0, -.40), x1-x0, 3.80,
                                   facecolor=group["color"], alpha=.50, edgecolor="none", zorder=0))
            ax.text((x0+x1)/2, -.72, group["label"], fontsize=9.5,
                    ha="center", va="center", color=MUTED)
        if panels > 1:
            ax.text(.0, -.69, f"{panel+1:02d} / {panels:02d}   Gates {start+1}-{start+length}",
                    fontsize=10, fontweight="bold", color=MUTED)
        for q in range(4):
            ax.plot([.37, length+.55], [q, q], color="#8998a7", linewidth=1.1, zorder=1)
            ax.text(.10, q, f"$q_{q}$", fontsize=11, ha="right", va="center", color=INK)
        for position, item in enumerate(chunk, 1):
            draw_gate(ax, item, position)
            ax.text(position, 3.60, str(start+position), fontsize=7.5, color=MUTED, ha="center")
        if panels == 1 and not example["groups"]:
            ax.annotate("time", xy=(length+.4, -.70), xytext=(max(.55, length*.67), -.70),
                        arrowprops=dict(arrowstyle="->", color=MUTED, linewidth=.9),
                        color=MUTED, fontsize=9, va="center")
    fig.text(.045, .065 if panels == 1 else .035,
             "INPUT CIRCUIT  |  time: left to right  |  wire order: q0, q1, q2, q3 (q0 = MSB)",
             fontsize=8.8, color=MUTED)
    fig.text(.045, .020 if panels == 1 else .015, example["status"], fontsize=8.1, color=MUTED)
    fig.savefig(DEST / (example["id"] + ".svg"), format="svg",
                metadata={"Date": None, "Creator": "scripts/render_circuit_diagrams.py"})
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_dir / (example["id"] + ".png"), dpi=140)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png-dir", type=Path)
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    examples, random_circuit, qasm = make_examples()
    checks = check_examples(examples, random_circuit)
    manifest = dict(schema_version=1, purpose="documentation_input_circuit_illustrations",
                    research_plan_commit=SOURCE_PLAN, basis_order="|q0 q1 q2 q3>; q0 is most significant",
                    no_measurements=True, no_input_state_assumed=True,
                    no_optimization_performed=True, examples=examples)
    for filename, data in [("circuit_examples.json", manifest), ("diagram_checks.json", checks)]:
        (DEST / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (DEST / "random_clifford_t_4q.qasm").write_text(qasm, encoding="utf-8")
    for example in examples:
        draw_example(example, args.png_dir)
    print(json.dumps({"rendered": [example["id"] for example in examples],
                      "checks": checks["checks"]}, indent=2))


if __name__ == "__main__":
    main()
