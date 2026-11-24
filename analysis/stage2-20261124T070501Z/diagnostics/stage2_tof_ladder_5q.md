# Extraction trace: stage2_tof_ladder_5q

Status: **exact_verified_replay**.

The trace replays the saved reduced graph with the frozen extraction settings. All values below describe an untimed diagnostic; primary runtime measurements are unchanged.

## Stage metrics

| Stage | T | 2Q | CNOT | CZ | Depth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 21 | 18 | 18 | 0 | 29 |
| Gate-only | 21 | 18 | 17 | 1 | 30 |
| ZX-before-cleanup | 17 | 37 | 18 | 19 | 63 |
| ZX | 17 | 34 | 29 | 5 | 42 |

Graph vertices/edges before simplification: 73/86; after: 44/70.

## Gate emission accounting

| Origin | CNOT | CZ | H | ZPhase | SWAP |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean_frontier | 0 | 19 | 12 | 18 | 0 |
| apply_cnots | 9 | 0 | 22 | 0 | 0 |
| permutation/boundary prefix | 0 | 0 | 4 | 0 | 3 |

Each prefix SWAP becomes three CNOTs in the common normalization. Candidate CNOT lists from trial elimination are not added to emitted-gate totals. Emission order is PyZX's internal extraction order; the library reverses the main gate list before return and prepends the permutation/boundary circuit. No alternative extraction-direction condition is introduced.

Raw gate-order accounting matches: `True`. Normalized 2Q accounting matches: `True`.

## Actual matrix batches

Rows are ordered frontier vertices; columns are the ordered interior neighbors. An extractable row has exactly one 1. A recorded XOR is an actual operation on the matrix used to update the graph, not a discarded candidate operation.

| Round | Matrix rows × columns | Unit rows before → after | Applied XOR / CNOT | Emitted H | Extracted vertices |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 4 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 6 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 8 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 9 | 5 × 7 | 2 → 2 | 0 | 2 | 2 |
| 10 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 12 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 14 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 15 | 4 × 5 | 0 → 1 | 1 | 1 | 1 |
| 17 | 4 × 5 | 0 → 1 | 1 | 1 | 1 |
| 18 | 4 × 5 | 1 → 1 | 0 | 1 | 1 |
| 19 | 4 × 5 | 0 → 1 | 1 | 1 | 1 |
| 20 | 4 × 4 | 0 → 1 | 1 | 1 | 1 |
| 21 | 3 × 3 | 0 → 1 | 1 | 1 | 1 |
| 23 | 3 × 3 | 1 → 1 | 0 | 1 | 1 |
| 25 | 3 × 3 | 1 → 1 | 0 | 1 | 1 |
| 26 | 3 × 4 | 1 → 1 | 0 | 1 | 1 |
| 27 | 3 × 4 | 1 → 1 | 0 | 1 | 1 |
| 28 | 3 × 3 | 1 → 1 | 0 | 1 | 1 |
| 29 | 2 × 2 | 1 → 1 | 0 | 1 | 1 |
| 30 | 1 × 1 | 1 → 1 | 0 | 1 | 1 |

First actual XOR (round 2): source row 0 `0000110` is XORed into target row 1 `0000111`, producing `0000001`. The full before/after matrices, frontier-to-wire mapping, and emitted CNOT are in the accompanying JSON.

## Replay checks

- Saved graph JSON round-trip identity: `True`.
- Normalized output QASM hash matches saved ZX-before-cleanup: `True`.
- Saved QASM SHA-256: `628e77b415882803d2810a03180f50ced096587a00bff84a5598a0c70234906e`.
- Replayed QASM SHA-256: `628e77b415882803d2810a03180f50ced096587a00bff84a5598a0c70234906e`.
- Independent dense verification: `passed`; maximum residual `3.4467298567554505e-15`.

## Interpretation limits

These observations locate emitted gates and cleanup changes within this fixed pipeline. They do not prove a globally minimum CNOT count, that every emitted gate is necessary, or that a graph-size reduction causes a circuit-cost reduction. Simplification rewrite steps and all trial Gaussian elimination XORs are not individually logged. QFT T-count remains N/A because no approximate Clifford+T synthesis is performed.
