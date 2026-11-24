# Extraction trace: stage2_phase_4q_L80_s100

Status: **exact_verified_replay**.

The trace replays the saved reduced graph with the frozen extraction settings. All values below describe an untimed diagnostic; primary runtime measurements are unchanged.

## Stage metrics

| Stage | T | 2Q | CNOT | CZ | Depth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 21 | 46 | 46 | 0 | 62 |
| Gate-only | 13 | 38 | 38 | 0 | 43 |
| ZX-before-cleanup | 3 | 20 | 9 | 11 | 28 |
| ZX | 3 | 17 | 17 | 0 | 20 |

Graph vertices/edges before simplification: 144/186; after: 18/25.

## Gate emission accounting

| Origin | CNOT | CZ | H | ZPhase | SWAP |
| --- | ---: | ---: | ---: | ---: | ---: |
| clean_frontier | 0 | 11 | 3 | 4 | 0 |
| apply_cnots | 0 | 0 | 7 | 0 | 0 |
| permutation/boundary prefix | 0 | 0 | 4 | 0 | 3 |

Each prefix SWAP becomes three CNOTs in the common normalization. Candidate CNOT lists from trial elimination are not added to emitted-gate totals. Emission order is PyZX's internal extraction order; the library reverses the main gate list before return and prepends the permutation/boundary circuit. No alternative extraction-direction condition is introduced.

Raw gate-order accounting matches: `True`. Normalized 2Q accounting matches: `True`.

## Actual matrix batches

Rows are ordered frontier vertices; columns are the ordered interior neighbors. An extractable row has exactly one 1. A recorded XOR is an actual operation on the matrix used to update the graph, not a discarded candidate operation.

| Round | Matrix rows × columns | Unit rows before → after | Applied XOR / CNOT | Emitted H | Extracted vertices |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4 × 5 | 2 → 2 | 0 | 2 | 2 |
| 2 | 4 × 4 | 2 → 2 | 0 | 2 | 2 |
| 3 | 3 × 3 | 1 → 1 | 0 | 1 | 1 |
| 4 | 2 × 2 | 1 → 1 | 0 | 1 | 1 |
| 5 | 1 × 1 | 1 → 1 | 0 | 1 | 1 |

## Replay checks

- Saved graph JSON round-trip identity: `True`.
- Normalized output QASM hash matches saved ZX-before-cleanup: `True`.
- Saved QASM SHA-256: `f9e0b3da6d6833366cd821139f348dbe51d6be063e5f2219be6ee2ddf81396ac`.
- Replayed QASM SHA-256: `f9e0b3da6d6833366cd821139f348dbe51d6be063e5f2219be6ee2ddf81396ac`.
- Independent dense verification: `passed`; maximum residual `2.036255037383895e-15`.

## Interpretation limits

These observations locate emitted gates and cleanup changes within this fixed pipeline. They do not prove a globally minimum CNOT count, that every emitted gate is necessary, or that a graph-size reduction causes a circuit-cost reduction. Simplification rewrite steps and all trial Gaussian elimination XORs are not individually logged. QFT T-count remains N/A because no approximate Clifford+T synthesis is performed.
