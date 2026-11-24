# Extraction trace: stage2_qft_5q

Status: **exact_verified_replay**.

The trace replays the saved reduced graph with the frozen extraction settings. All values below describe an untimed diagnostic; primary runtime measurements are unchanged.

## Stage metrics

| Stage | T | 2Q | CNOT | CZ | Depth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | N/A | 26 | 26 | 0 | 32 |
| Gate-only | N/A | 25 | 21 | 4 | 26 |
| ZX-before-cleanup | N/A | 48 | 14 | 34 | 69 |
| ZX | N/A | 42 | 37 | 5 | 55 |

Graph vertices/edges before simplification: 97/118; after: 40/56.

## Gate emission accounting

| Origin | CNOT | CZ | H | ZPhase | SWAP |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean_frontier | 0 | 34 | 12 | 18 | 0 |
| apply_cnots | 5 | 0 | 21 | 0 | 0 |
| permutation/boundary prefix | 0 | 0 | 2 | 0 | 3 |

Each prefix SWAP becomes three CNOTs in the common normalization. Candidate CNOT lists from trial elimination are not added to emitted-gate totals. Emission order is PyZX's internal extraction order; the library reverses the main gate list before return and prepends the permutation/boundary circuit. No alternative extraction-direction condition is introduced.

Raw gate-order accounting matches: `True`. Normalized 2Q accounting matches: `True`.

## Actual matrix batches

Rows are ordered frontier vertices; columns are the ordered interior neighbors. An extractable row has exactly one 1. A recorded XOR is an actual operation on the matrix used to update the graph, not a discarded candidate operation.

| Round | Matrix rows × columns | Unit rows before → after | Applied XOR / CNOT | Emitted H | Extracted vertices |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 5 × 7 | 1 → 1 | 0 | 1 | 1 |
| 4 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 5 | 5 × 6 | 0 → 1 | 1 | 1 | 1 |
| 7 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 9 | 5 × 7 | 2 → 2 | 0 | 2 | 2 |
| 11 | 5 × 6 | 2 → 2 | 0 | 2 | 2 |
| 13 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 14 | 5 × 7 | 0 → 1 | 1 | 1 | 1 |
| 15 | 5 × 6 | 0 → 1 | 1 | 1 | 1 |
| 16 | 5 × 6 | 1 → 1 | 0 | 1 | 1 |
| 17 | 5 × 5 | 1 → 1 | 0 | 1 | 1 |
| 18 | 5 × 5 | 0 → 1 | 1 | 1 | 1 |
| 19 | 5 × 5 | 1 → 1 | 0 | 1 | 1 |
| 20 | 5 × 5 | 2 → 2 | 0 | 2 | 2 |
| 21 | 4 × 4 | 3 → 3 | 0 | 3 | 3 |
| 22 | 1 × 1 | 1 → 1 | 0 | 1 | 1 |

First actual XOR (round 4): source row 0 `0101000` is XORed into target row 3 `0101010`, producing `0000010`. The full before/after matrices, frontier-to-wire mapping, and emitted CNOT are in the accompanying JSON.

## Replay checks

- Saved graph JSON round-trip identity: `True`.
- Normalized output QASM hash matches saved ZX-before-cleanup: `True`.
- Saved QASM SHA-256: `fd8069b052e70494cb5ba58e82ee92fab6db83e3618b8daf07c3feffbd295201`.
- Replayed QASM SHA-256: `fd8069b052e70494cb5ba58e82ee92fab6db83e3618b8daf07c3feffbd295201`.
- Independent dense verification: `passed`; maximum residual `6.532886618304434e-16`.

## Interpretation limits

These observations locate emitted gates and cleanup changes within this fixed pipeline. They do not prove a globally minimum CNOT count, that every emitted gate is necessary, or that a graph-size reduction causes a circuit-cost reduction. Simplification rewrite steps and all trial Gaussian elimination XORs are not individually logged. QFT T-count remains N/A because no approximate Clifford+T synthesis is performed.
