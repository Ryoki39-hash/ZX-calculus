# Stage 2 extraction diagnostics

Run: `stage2-20261124T070501Z`. Benchmark source: `b309dd8f7ec1a8799b0a9a79b1ffee089d71cc97`. Diagnostic source: `b309dd8f7ec1a8799b0a9a79b1ffee089d71cc97`.

Four cases were fixed by the Stage 2 plan before observing results. Diagnostics began after the primary run completed and do not contribute to measured runtime.

| Input | Replay | Applied row XORs | Matrix CNOT | Frontier CNOT / CZ | Prefix SWAP | 2Q Gate → extracted → cleaned |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| [stage2_phase_4q_L80_s100](stage2_phase_4q_L80_s100.md) | exact_verified_replay | 0 | 0 | 0 / 11 | 3 | 38 → 20 → 17 |
| [stage2_phase_8q_L80_s100](stage2_phase_8q_L80_s100.md) | exact_verified_replay | 7 | 7 | 0 / 56 | 4 | 45 → 75 → 64 |
| [stage2_tof_ladder_5q](stage2_tof_ladder_5q.md) | exact_verified_replay | 9 | 9 | 0 / 19 | 3 | 18 → 37 → 34 |
| [stage2_qft_5q](stage2_qft_5q.md) | exact_verified_replay | 5 | 5 | 0 / 34 | 3 | 25 → 48 → 42 |

Matrix CNOTs come from actual row-XOR batches. Frontier cleanup can also emit CNOTs while factoring CZ neighborhoods. Any boundary SWAP contributes three CNOTs after normalization. Candidate elimination gates are kept separate from emitted gates.

The traces show where this implementation creates gates, and the saved stage metrics show how common cleanup changes their counts. They are diagnostic case studies, not proofs of causal effects or optimality. Full matrices and hashes are in the per-case JSON files.
