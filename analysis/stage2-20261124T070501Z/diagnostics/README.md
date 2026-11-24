# Fixed Stage 2 extraction diagnostics

Start with [summary.md](summary.md) and the four linked case explanations. All four diagnostic replays exactly matched the saved normalized extracted QASM and passed independent numerical verification. Diagnostics ran after primary benchmarking and are excluded from optimization runtime.

The complete per-case event JSON files (frontiers, ordered binary matrices, actual row XORs, candidate and emitted gates, permutation mapping, hashes and verification) are preserved byte-for-byte in [traces.zip](traces.zip). See [trace_index.json](trace_index.json) for member paths, byte sizes and SHA-256 hashes. The summaries and case Markdown files remain directly readable.

Unpack the archive into this directory to inspect the four JSON files. The frozen tracer can regenerate them using the primary run's saved graph artifacts; it does not need this diagnostic archive as input.

```bash
python benchmarks/controlled_followup/trace_extraction.py --run-id stage2-20261124T070501Z --code-commit b309dd8f7ec1a8799b0a9a79b1ffee089d71cc97
```

Run reproduction in a fresh copy or with a fresh diagnostic output destination: completed diagnostic directories are not overwritten. See the script help for options. The package step used `python analysis/package_run_artifacts.py stage2-20261124T070501Z --diagnostics`; it changes storage packaging only, not observations.
