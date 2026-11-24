# Extraction trace: stage2_phase_8q_L80_s100

Status: **exact_verified_replay**.

The trace replays the saved reduced graph with the frozen extraction settings. All values below describe an untimed diagnostic; primary runtime measurements are unchanged.

## Stage metrics

| Stage | T | 2Q | CNOT | CZ | Depth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 23 | 49 | 49 | 0 | 34 |
| Gate-only | 13 | 45 | 45 | 0 | 30 |
| ZX-before-cleanup | 13 | 75 | 19 | 56 | 83 |
| ZX | 13 | 64 | 59 | 5 | 53 |

Graph vertices/edges before simplification: 157/198; after: 49/115.

## Gate emission accounting

| Origin | CNOT | CZ | H | ZPhase | SWAP |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean_frontier | 0 | 56 | 12 | 13 | 0 |
| apply_cnots | 7 | 0 | 20 | 0 | 0 |
| permutation/boundary prefix | 0 | 0 | 8 | 0 | 4 |

Each prefix SWAP becomes three CNOTs in the common normalization. Candidate CNOT lists from trial elimination are not added to emitted-gate totals. Emission order is PyZX's internal extraction order; the library reverses the main gate list before return and prepends the permutation/boundary circuit. No alternative extraction-direction condition is introduced.

Raw gate-order accounting matches: `True`. Normalized 2Q accounting matches: `True`.

## Actual matrix batches

Rows are ordered frontier vertices; columns are the ordered interior neighbors. An extractable row has exactly one 1. A recorded XOR is an actual operation on the matrix used to update the graph, not a discarded candidate operation.

| Round | Matrix rows × columns | Unit rows before → after | Applied XOR / CNOT | Emitted H | Extracted vertices |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 8 × 8 | 0 → 1 | 1 | 1 | 1 |
| 4 | 8 × 8 | 1 → 1 | 0 | 1 | 1 |
| 6 | 8 × 8 | 0 → 1 | 1 | 1 | 1 |
| 7 | 8 × 10 | 0 → 1 | 1 | 1 | 1 |
| 9 | 8 × 10 | 1 → 1 | 0 | 1 | 1 |
| 11 | 8 × 10 | 0 → 1 | 1 | 1 | 1 |
| 12 | 8 × 12 | 1 → 1 | 0 | 1 | 1 |
| 13 | 8 × 12 | 3 → 3 | 0 | 3 | 3 |
| 14 | 8 × 10 | 2 → 2 | 0 | 2 | 2 |
| 15 | 8 × 8 | 0 → 1 | 1 | 1 | 1 |
| 16 | 7 × 7 | 0 → 1 | 1 | 1 | 1 |
| 17 | 6 × 6 | 0 → 1 | 1 | 1 | 1 |
| 18 | 5 × 5 | 1 → 1 | 0 | 1 | 1 |
| 19 | 4 × 4 | 1 → 1 | 0 | 1 | 1 |
| 20 | 3 × 3 | 1 → 1 | 0 | 1 | 1 |
| 21 | 2 × 2 | 1 → 1 | 0 | 1 | 1 |
| 22 | 1 × 1 | 1 → 1 | 0 | 1 | 1 |

First actual XOR (round 2): source row 5 `00110011` is XORed into target row 0 `00111011`, producing `00001000`. The full before/after matrices, frontier-to-wire mapping, and emitted CNOT are in the accompanying JSON.

## Replay checks

- Saved graph JSON round-trip identity: `True`.
- Normalized output QASM hash matches saved ZX-before-cleanup: `True`.
- Saved QASM SHA-256: `f5171e679914432b4763b65ae3a90fb10de084ca1a2718e7f01169afefcb840e`.
- Replayed QASM SHA-256: `f5171e679914432b4763b65ae3a90fb10de084ca1a2718e7f01169afefcb840e`.
- Independent dense verification: `passed`; maximum residual `3.688819061429085e-15`.

## Interpretation limits

These observations locate emitted gates and cleanup changes within this fixed pipeline. They do not prove a globally minimum CNOT count, that every emitted gate is necessary, or that a graph-size reduction causes a circuit-cost reduction. Simplification rewrite steps and all trial Gaussian elimination XORs are not individually logged. QFT T-count remains N/A because no approximate Clifford+T synthesis is performed.
