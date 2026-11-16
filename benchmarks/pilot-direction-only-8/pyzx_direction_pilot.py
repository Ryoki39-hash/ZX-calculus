"""Run with: python -m pip install pyzx==0.10.8 && python pyzx_direction_pilot.py."""
import csv
import platform
import random
from pathlib import Path
from statistics import median
from time import perf_counter_ns

import numpy as np
import pyzx as zx

REPEATS = 31
OUT = Path(__file__).resolve().parent


def cases():
    for n in (3, 4, 5, 6):
        c = zx.Circuit(n)
        for k in range(n - 2):
            c.add_gate("TOF", k, k + 1, k + 2)
        yield f"tof_ladder_{n}q", c
    for seed in range(4):
        rng = random.Random(seed)
        c = zx.Circuit(5)
        for _ in range(24):
            a, b = rng.sample(range(5), 2)
            name = rng.choice(("HAD", "S", "T", "CNOT", "CZ"))
            c.add_gate(name, a, b) if name in ("CNOT", "CZ") else c.add_gate(name, a)
        yield f"clifford_t_5q_s{seed}", c


def reduce(c):
    g = c.to_graph()
    zx.full_reduce(g)
    return g


def extract(g, reverse):
    h = g.copy(adjoint=reverse)
    out = zx.extract_circuit(h, optimize_czs=True, optimize_cnots=2, up_to_perm=False)
    return (out.adjoint() if reverse else out).to_basic_gates()


def metrics(c):
    return c.tcount(), c.twoqubitcount(), c.depth()


def same_unitary(ref, actual):
    # Fit a unit-magnitude phase, not an arbitrary scalar; wire order is fixed.
    k = np.unravel_index(np.argmax(abs(ref)), ref.shape)
    ratio = actual[k] / ref[k]
    if abs(ratio) == 0:
        return False
    return bool(np.allclose(actual, ratio / abs(ratio) * ref, atol=1e-9, rtol=0))


def main():
    rows = []
    for name, initial in cases():
        c = initial.to_basic_gates()
        ref = c.to_matrix()
        reduced = reduce(c)
        candidates = {d: extract(reduced, d == "reverse") for d in ("forward", "reverse")}
        valid = {d: same_unitary(ref, c2.to_matrix()) for d, c2 in candidates.items()}
        assert all(valid.values()), (name, valid)
        reduce_ms = []
        extract_ms = {d: [] for d in candidates}
        for rep in range(REPEATS):
            start = perf_counter_ns()
            reduced = reduce(c)
            reduce_ms.append((perf_counter_ns() - start) / 1e6)
            order = ("forward", "reverse") if rep % 2 == 0 else ("reverse", "forward")
            for d in order:
                start = perf_counter_ns()
                current = extract(reduced, d == "reverse")
                extract_ms[d].append((perf_counter_ns() - start) / 1e6)
                assert metrics(current) == metrics(candidates[d]), (name, d)
        input_t, input_q, input_depth = metrics(c)
        ft, fq, fd = metrics(candidates["forward"])
        rt, rq, rd = metrics(candidates["reverse"])
        choose_reverse = valid["reverse"] and rt <= ft and rq < fq
        rows.append(dict(
            circuit=name, qubits=c.qubits, input_t=input_t, input_2q=input_q, input_depth=input_depth,
            forward_t=ft, forward_2q=fq, forward_depth=fd, forward_verified=valid["forward"],
            reverse_t=rt, reverse_2q=rq, reverse_depth=rd, reverse_verified=valid["reverse"],
            chosen="reverse" if choose_reverse else "forward",
            chosen_2q_gain=fq-rq if choose_reverse else 0,
            reduce_median_ms=round(median(reduce_ms), 4),
            forward_extract_median_ms=round(median(extract_ms["forward"]), 4),
            reverse_extract_median_ms=round(median(extract_ms["reverse"]), 4),
            median_extra_ms=round(median(extract_ms["reverse"]), 4),
            pyzx=zx.__version__, python=platform.python_version(), repeats=REPEATS,
        ))
    with (OUT / "pyzx_direction_results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
