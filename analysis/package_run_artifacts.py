#!/usr/bin/env python3
"""Package immutable benchmark artifacts without modifying any measured bytes.

Usage: python analysis/package_run_artifacts.py RUN_ID
       python analysis/package_run_artifacts.py RUN_ID --diagnostics
The fixed timestamp and sorted member order make the ZIP deterministic.
This postprocessing step is outside benchmark timing and does not optimize.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DIRECT = {"results.csv", "metadata.json", "protocol.json", "verifier_controls.json"}


def digest(data):
    return sha256(data).hexdigest()


def package(run_id, diagnostics=False):
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in run_id):
        raise ValueError("Invalid run ID")
    run = ROOT / "runs" / run_id
    metadata = json.loads((run / "metadata.json").read_text())
    if metadata["state"] != "completed":
        raise ValueError("Only a completed run can be packaged")
    direct = DIRECT
    archive_name, index_name = "artifacts.zip", "artifact_index.json"
    if diagnostics:
        run = ROOT / "analysis" / run_id / "diagnostics"
        archive_name, index_name = "traces.zip", "trace_index.json"
        members = sorted(run.glob("stage2_*.json"))
        if len(members) != 4:
            raise AssertionError("Expected four diagnostic event JSON files")
        direct = {"metadata.json", "summary.json", "summary.md"}
    else:
        members = sorted(p for p in run.rglob("*") if p.is_file()
                         and p.relative_to(run).as_posix() not in direct
                         and p.name not in {archive_name, index_name, archive_name + ".tmp"})
    if not members:
        raise ValueError("No unpacked artifacts to archive")
    before = {p.relative_to(run).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
              for p in members}
    temporary = run / (archive_name + ".tmp")
    archive = run / archive_name
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as z:
        for p in members:
            info = ZipInfo(p.relative_to(run).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes(), compresslevel=9)
    with ZipFile(temporary) as z:
        if z.testzip() is not None or set(z.namelist()) != set(before):
            raise AssertionError("ZIP member/CRC validation failed")
        for name, expected in before.items():
            data = z.read(name)
            if len(data) != expected["bytes"] or digest(data) != expected["sha256"]:
                raise AssertionError(f"ZIP member mismatch: {name}")
    for name, expected in before.items():
        if digest((run / name).read_bytes()) != expected["sha256"]:
            raise AssertionError(f"Source artifact changed: {name}")
    if archive.exists() and digest(archive.read_bytes()) != digest(temporary.read_bytes()):
        temporary.unlink()
        raise RuntimeError("Refusing to replace a different existing archive")
    temporary.replace(archive)
    index = {
        "format": "zx-run-artifact-index-v1", "run_id": run_id,
        "code_commit": metadata["code_commit"], "archive": archive_name,
        "archive_sha256": digest(archive.read_bytes()), "archive_bytes": archive.stat().st_size,
        "member_count": len(before), "uncompressed_bytes": sum(v["bytes"] for v in before.values()),
        "members": before,
        "direct_files": {name: {"bytes": (run/name).stat().st_size, "sha256": digest((run/name).read_bytes())}
                         for name in sorted(direct)},
        "preservation": "All ZIP members are byte-identical copies; no measured artifacts were changed.",
        "access": "Members are relative to runs/RUN_ID. Analysis and diagnostics read the ZIP directly; unpack beside metadata.json for manual inspection.",
    }
    if diagnostics:
        index["format"] = "zx-diagnostic-artifact-index-v1"
        index["access"] = "Members are relative to analysis/RUN_ID/diagnostics. Unpack beside summary.json to inspect full event traces."
    path = run / index_name
    content = json.dumps(index, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text() != content:
        raise RuntimeError("Refusing to replace a different existing index")
    path.write_text(content)
    return {key: index[key] for key in ("run_id", "member_count", "archive_bytes", "archive_sha256", "uncompressed_bytes")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    print(json.dumps(package(args.run_id, diagnostics=args.diagnostics), indent=2))
