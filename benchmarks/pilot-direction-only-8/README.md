# PyZX extraction-direction pilot

**Run ID:** `pilot-direction-only-8` · **Status:** Executed November 15, 2026 UTC.

[Observed results (CSV)](pyzx_direction_results.csv) · [Reproduction script](pyzx_direction_pilot.py) · [Separate earlier pilot and planned 30-seed run](../../research_log/2026-11-16.md)

**Question.** With the same reduced ZX graph, can adjoint-based reverse extraction lower the two-qubit gate count relative to the standard extraction, without increasing T-count?

**Inputs.** Four overlapping Toffoli ladders (3–6 qubits) and four seeded 5-qubit Clifford+T circuits (24 sampled gate placements each). These are synthetic pilot inputs, not the thesis benchmark suite.

**Protocol.** Convert each input to basic gates and call PyZX `full_reduce` once per trial. The forward candidate extracts directly from a copy of the reduced graph, using PyZX's native sweep. The reverse candidate extracts from the adjoint graph and adjoints the resulting circuit back. Both use `optimize_czs=True, optimize_cnots=2, up_to_perm=False`. Gates in the output are counted after basic-gate conversion; there is no post-extraction cancellation pass or hardware routing. Candidate selection switches to reverse only if it passes equivalence, its T-count is no higher than forward, and its two-qubit gate count is strictly lower.

**Verification and timing.** All 16 outputs matched the input unitary matrices numerically up to global phase, with wire order preserved (absolute tolerance 1e-9). Times are paired medians of 31 repetitions, with order alternated. The reduction times include conversion from circuit to graph. Extraction times include graph copy, extraction, output adjoint when applicable, and basic-gate conversion. They exclude matrix verification and metric calculation. The incremental cost of trying both directions after shared reduction is approximately the reverse extraction time. This is a smoke test, not a large-scale runtime study.

**Results.** Reverse extraction had the same T-count on all 8 inputs. Its two-qubit count was higher on 4 and tied on 4, so the selection rule kept forward on all inputs. On the 6-qubit Toffoli ladder, reverse reduced depth from 91 to 83 but increased the two-qubit count from 58 to 63 (T-count 22 in both). Compared with the unoptimized input, forward increased two-qubit count on all four Toffoli ladders but decreased it on all four random circuits. These observations do not establish a general trend.

**Next experiment.** Compare both directions at each supported CNOT optimization level 0–3 on these same inputs, then use a predefined held-out benchmark set to evaluate whether any improvements generalize. Keep the standard forward level-2 candidate as the reference and report the additional wall-clock cost of multi-candidate selection.

## Reproduce
Tested with CPython 3.12.14, PyZX 0.10.8, NumPy 2.3.5, Linux cloud VM (AMD EPYC 9V74).
```sh
python -m pip install pyzx==0.10.8 numpy==2.3.5
OPENBLAS_NUM_THREADS=1 python pyzx_direction_pilot.py
```
This writes `pyzx_direction_results.csv` next to the script. Re-running replaces the CSV with fresh timing measurements.

[PyZX API documentation](https://pyzx.readthedocs.io/en/latest/api.html)
