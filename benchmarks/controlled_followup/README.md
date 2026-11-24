# Stage 2 — Controlled follow-up

This implementation executes the frozen [Stage 2 plan](../../docs/stage2_followup_plan.md) at commit `4dbe91ceb5055b9c682d7bfc501879eed34c6925`. It uses 66 inputs, with Original / Gate-only / ZX for each input (198 primary rows). Backward / Reverse is excluded. Stage 1 source and results remain historical records.

## Fixed inputs and decisions

| Batch | Inputs | Count | Prespecified question |
| --- | --- | ---: | --- |
| A | Phase 4q/8q, L80, seeds 100–109; Toffoli ladders 5q/7q; QFT 5q/7q | 24 | H1–H3: do the exploratory effects recur? |
| B1 | Phase 4q/8q, L160, seeds 100–109 | 20 | H4: does extending the 8q inputs improve their relative 2Q reduction? |
| B2 | 6q parity reuse / unique, ten seed-matched pairs | 20 | H5: is the absolute additional 2Q saving larger with reuse? |
| B3 | Two disjoint CCX / a two-CCX cascade, both on 6 declared wires | 2 | H6: is the cascade's additional 2Q burden larger? |
| C | Four fixed inputs already counted above | 0 additional | Where do graph simplification, extraction and cleanup change the cost? |

The hypotheses and thresholds are defined before outcomes in the plan and `analysis/summarize_stage2.py`. An 8/10 threshold is a descriptive replication rule, not a significance test. Failed or unverified inputs are retained. Ten runtime repetitions do not make ten independent inputs.

## Reproduction

Use Python 3.12 with the pinned versions in [the Stage 1 requirements](../broad_screening/requirements.txt), notably PyZX 0.10.8 and NumPy 2.3.5. Install matplotlib for the analysis. Run from the repository root:

```bash
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
python benchmarks/controlled_followup/run.py --prepare
python benchmarks/controlled_followup/run.py --smoke --code-commit SOURCE_COMMIT_SHA
python benchmarks/controlled_followup/run.py --code-commit SOURCE_COMMIT_SHA
python analysis/summarize_stage2.py RUN_ID
python benchmarks/controlled_followup/trace_extraction.py --run-id RUN_ID --code-commit SOURCE_COMMIT_SHA
```

Use the source commit recorded in a published run's metadata. The code SHA argument is provenance, not a working-tree integrity check: verify the recorded source hashes as well. `--prepare` freezes all raw and normalized input QASM hashes without optimization; it refuses to replace a different existing manifest. Each run creates a new directory. The eight-case smoke run checks coverage and is kept separately from the primary 66-input run. Diagnostic extraction is performed only after primary timing is complete.

## Measurement and verification

The common normalizer, gate counter and independent dense evaluator are reused unchanged from `benchmarks/broad_screening/semantics.py`. Gate-only runs one `basic_optimization(do_swaps=False)` call. ZX uses `full_reduce`, standard extraction (`optimize_cnots=2`, `optimize_czs=True`, `up_to_perm=False`), and the same cleanup. The gate-count comparison uses ZX against Gate-only and also retains Original.

Each input is checked against an independently constructed mathematical reference: analytic positive QFT, CCX basis-state permutation, parity diagonal or phase-polynomial/linear-map evaluation from the input specification. All outputs, including extracted output before cleanup, are compared with the raw reference for every computational basis input, in fixed wire order, permitting only a unit-modulus global phase (`atol=1e-9`, `rtol=0`). This is numerical evidence, not a symbolic proof.

T-count means normalized literal T plus T-dagger gates. General-angle QFT does not have approximate Clifford+T synthesis, so its T-count is null (N/A). 2Q counts CNOT plus CZ, and depth counts logical dependency layers in the shared basis. These are logical circuit costs without routing or hardware error calibration.

Timing uses one warmup and ten repetitions per optimized method, alternating method order within an input. Timed output hashes must match the independently verified quality output; a mismatch is separately verified. Gate counting, dense verification, hashing, file output and diagnostic traces are excluded from optimization runtime. All 66 inputs execute serially in a single process, in A/B1/B2/B3 order; timing remains sensitive to environment noise and this fixed batch order.

## Artifacts and publication

Directly readable files under `runs/RUN_ID/` are `results.csv`, `metadata.json`, `protocol.json`, `verifier_controls.json`, and `artifact_index.json`. The remaining raw artifacts are published in `artifacts.zip`:

| ZIP member | Meaning |
| --- | --- |
| `inputs/CIRCUIT_ID.json` | Frozen specification, raw/normalized QASM strings, definition check, structural features |
| `graphs/CIRCUIT_ID.json` | Exact saved graph JSON before and after simplification, graph counts |
| `outputs/CIRCUIT_ID.json` | All output QASM strings, hashes, pre-cleanup metrics |
| `records/CIRCUIT_ID.json` | Per-input result rows, including failures |
| `timings.json` | All timed repetitions, stage durations, hashes and validation status |
| `verification.json` | Numerical output checks and residuals |

Archive members are byte-identical copies of the local run artifacts. The index records each member's byte count and SHA-256, and the archive's SHA-256. The analysis and extraction diagnostic tools read either unpacked files or the archive. To inspect every raw file, download the ZIP and unpack it into the same run directory. Do not mistake a ZIP member path for an individually hosted GitHub file.

Readable analysis tables and figures are under `analysis/RUN_ID/`; the report is under `reports/`. Input structure, paired seed changes, all failures, runtime components and all H1–H6 decisions are retained. Large full diagnostic event traces may be archived with a separate hash index while their summaries remain directly readable.

## Interpretation limits

B2 reuse and unique circuits usually implement different unitaries and each is verified against its own input. Their active wires, support frequencies, connectivity and depths are recorded, not assumed equal. B3 has six active wires in the disjoint case and four in the cascade; overlap is therefore not isolated from active width. The cascade repeats a historical 4q ladder with idle wires. Toffoli 5q also appeared in the old pilot. L/n is only a density proxy; changing length changes other structure as well. Claims are restricted to the tested inputs, cost definitions and fixed PyZX pipeline.
