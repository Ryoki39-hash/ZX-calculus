"""Build a persistent MegaLoc database, search images and evaluate held-out ISR renders."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from megaloc_runtime import MegaLocEncoder, fingerprint, read_rgb, sha256_file, validate_vectors
from isr_dataset import prepare_dataset
from isr_evaluation import evaluate_retrieval
from isr_report import write_evaluation_report, write_search_report


ROOT = Path(__file__).resolve().parent


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def save_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(path)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_images(records: list[dict]) -> None:
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("Empty image list or duplicate record IDs")
    for record in records:
        if sha256_file(Path(record["image_path"])) != record["sha256"]:
            raise ValueError(f"Image changed since preparation: {record['id']}. Prepare a new dataset directory.")


def load_database(directory: Path) -> tuple[dict, np.ndarray]:
    metadata = read_json(directory / "database.json")
    if fingerprint(metadata["encoder"]) != metadata["encoder_fingerprint"]:
        raise ValueError("Database encoder identity is inconsistent; rebuild the database.")
    vector_path = directory / "embeddings.npz"
    if sha256_file(vector_path) != metadata["embeddings_sha256"]:
        raise ValueError("Database embeddings changed or are incomplete; rebuild the database.")
    with np.load(vector_path, allow_pickle=False) as stored:
        vectors = stored["vectors"]
        ids = stored["ids"].tolist()
    if ids != [r["id"] for r in metadata["records"]]:
        raise ValueError("Database record/vector IDs do not match")
    validate_vectors(vectors, len(metadata["records"]))
    check_images(metadata["records"])
    expected = fingerprint({"encoder": metadata["encoder"], "records": metadata["records"]})
    if expected != metadata["fingerprint"]:
        raise ValueError("Database metadata changed; rebuild the database.")
    return metadata, vectors


def build_database(manifest: dict, directory: Path, encoder: MegaLocEncoder, rebuild: bool = False) -> dict:
    records = [r for r in manifest["records"] if r["split"] == "database"]
    check_images(records)
    key = fingerprint({"encoder": encoder.identity, "records": records})
    if (directory / "database.json").is_file() and not rebuild:
        existing, _ = load_database(directory)
        if existing["fingerprint"] != key:
            raise ValueError("Database model, inputs or split changed. Use a different --db directory or --rebuild.")
        print(f"Reusing database: {len(records)} images (no inference).", flush=True)
        return {"reused": True, "count": len(records), "embedding_seconds_this_run": 0.0}
    vectors = encoder.embed([Path(r["image_path"]) for r in records])
    save_npz(directory / "embeddings.npz", vectors=vectors, ids=np.array([r["id"] for r in records]))
    metadata = {
        "schema_version": 1, "created_at": timestamp(), "fingerprint": key,
        "encoder": encoder.identity, "encoder_fingerprint": encoder.identity_hash,
        "records": records, "database_count": len(records), "dimensions": int(vectors.shape[1]),
        "source_zip_sha256": manifest["source_zip_sha256"], "split": manifest["split"],
        "embeddings_sha256": sha256_file(directory / "embeddings.npz"),
        "timing": {"embedding_seconds": encoder.last_seconds, "device": encoder.device},
        "position_output": "Coordinates belong to retrieved reference cameras; no continuous pose estimation.",
    }
    save_json(directory / "database.json", metadata)
    print(f"Built database: {len(records)} images -> {directory}", flush=True)
    return {"reused": False, "count": len(records), "embedding_seconds_this_run": encoder.last_seconds}


def query_embeddings(records: list[dict], directory: Path, encoder: MegaLocEncoder) -> tuple[np.ndarray, dict]:
    check_images(records)
    key = fingerprint({"encoder": encoder.identity, "records": records})
    directory.mkdir(parents=True, exist_ok=True)
    vector_path, metadata_path = directory / "query_embeddings.npz", directory / "query_embeddings.json"
    if vector_path.is_file() and metadata_path.is_file():
        metadata = read_json(metadata_path)
        if metadata.get("fingerprint") == key:
            if sha256_file(vector_path) != metadata["embeddings_sha256"]:
                raise ValueError("Query embedding cache is corrupted. Use a new --out directory.")
            with np.load(vector_path, allow_pickle=False) as stored:
                vectors, ids = stored["vectors"], stored["ids"].tolist()
            if ids != [r["id"] for r in records]:
                raise ValueError("Query cache ID mismatch")
            validate_vectors(vectors, len(records))
            print(f"Reusing {len(records)} query embeddings (no inference).", flush=True)
            return vectors, {"reused": True, "embedding_seconds_this_run": 0.0,
                             "original_embedding_seconds": metadata["embedding_seconds"]}
    vectors = encoder.embed([Path(r["image_path"]) for r in records])
    save_npz(vector_path, vectors=vectors, ids=np.array([r["id"] for r in records]))
    save_json(metadata_path, {"fingerprint": key, "encoder": encoder.identity,
                             "ids": [r["id"] for r in records], "embedding_seconds": encoder.last_seconds,
                             "embeddings_sha256": sha256_file(vector_path), "device": encoder.device})
    return vectors, {"reused": False, "embedding_seconds_this_run": encoder.last_seconds,
                     "original_embedding_seconds": encoder.last_seconds}


def evaluate(manifest: dict, db_dir: Path, out: Path, encoder: MegaLocEncoder,
             split: str, distances: list[float], angle: float) -> dict:
    distances = sorted(set(distances))
    db, vectors = load_database(db_dir)
    if encoder.identity_hash != db["encoder_fingerprint"]:
        raise ValueError("Encoder differs from the database. Rebuild the database with the same model and preprocessing.")
    expected_records = [r for r in manifest["records"] if r["split"] == "database"]
    if fingerprint(expected_records) != fingerprint(db["records"]):
        raise ValueError("Manifest database split differs from this database")
    records = [r for r in manifest["records"] if r["split"] in ({"dev", "test"} if split == "all" else {split})]
    # Reject leakage before running inference, using the same validation as actual evaluation.
    evaluate_retrieval(db["records"], records, np.zeros((len(records), len(vectors))), distances, angle)
    features, cache_info = query_embeddings(records, out, encoder)
    started = time.perf_counter()
    scores = features @ vectors.T
    search_seconds = time.perf_counter() - started
    metrics = evaluate_retrieval(db["records"], records, scores, distances, angle)
    metrics["by_split"] = {}
    for name in ("dev", "test"):
        indices = [i for i, r in enumerate(records) if r["split"] == name]
        if indices:
            metrics["by_split"][name] = evaluate_retrieval(db["records"], [records[i] for i in indices],
                                                          scores[indices], distances, angle)
    run = {"created_at": timestamp(), "dataset": manifest["dataset_root"], "source_zip_sha256": manifest["source_zip_sha256"],
           "database_fingerprint": db["fingerprint"], "encoder": encoder.identity, "split": split,
           "split_definition": manifest["split"], "distance_thresholds_m": distances, "angle_threshold_deg": angle,
           "query_cache": cache_info, "ranking_seconds_total": search_seconds,
           "ranking_seconds_per_query": search_seconds / len(records),
           "timing_note": "Ranking time is matrix multiplication only; embedding time excludes model loading. Report generation and I/O are separate.",
           "scope": "Synthetic-to-synthetic baseline. Real-photo performance untested. No training or geometric pose refinement.",
           "test_policy": "Initial baseline may include test; use dev only for later improvement decisions. Do not tune on test."}
    save_npz(out / "scores.npz", scores=scores, query_ids=np.array([r["id"] for r in records]),
             database_ids=np.array([r["id"] for r in db["records"]]))
    save_json(out / "metrics.json", metrics)
    save_json(out / "run.json", run)
    with (out / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["query_id", "split", "point_id", "top1_id", "top1_distance_m", "top1_yaw_error_deg", "nearest_db_distance_m"]
        for threshold in distances:
            for mode in ("place", "place_and_yaw"):
                fields += [f"{mode}_{threshold:g}m_positive_count"] + [f"{mode}_{threshold:g}m_hit_at_{k}" for k in (1, 5, 10)]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record, result in zip(records, metrics["queries"]):
            row = {field: result[field] for field in fields[:7] if field != "split"}
            row["split"] = record["split"]
            for threshold in result["thresholds"]:
                for mode in ("place", "place_and_yaw"):
                    prefix = f"{mode}_{threshold['distance_m']:g}m"
                    row[prefix + "_positive_count"] = threshold[mode]["positive_count"]
                    row.update({f"{prefix}_hit_at_{k}": threshold[mode]["hits"][str(k)] for k in (1, 5, 10)})
            writer.writerow(row)
    report = write_evaluation_report(out, metrics, db["records"], records, run)
    print(f"Evaluation complete: {report}", flush=True)
    for result in metrics["thresholds"]:
        r1 = result["place"]["recall"]["1"]
        print(f"Position <= {result['distance_m']:g} m: R@1 {r1['successes']}/{r1['total']} ({r1['rate']:.1%})", flush=True)
    return metrics


def search(db_dir: Path, query: Path, out: Path, encoder: MegaLocEncoder, top_k: int) -> dict:
    if top_k < 1:
        raise ValueError("top-k must be positive")
    db, vectors = load_database(db_dir)
    if db["encoder_fingerprint"] != encoder.identity_hash:
        raise ValueError("Query encoder and database encoder differ; rebuild the database.")
    query = query.resolve()
    byte_hash = sha256_file(query)
    query_rgb = read_rgb(query)
    pixel_hash = hashlib.sha256(str(query_rgb.size).encode("ascii") + b"\0" + query_rgb.tobytes()).hexdigest()
    indices = [i for i, r in enumerate(db["records"])
               if r["sha256"] != byte_hash and r["pixel_sha256"] != pixel_hash and Path(r["image_path"]).resolve() != query]
    if not indices:
        raise ValueError("No database images remain after excluding exact query copies")
    feature = encoder.embed([query])[0]
    started = time.perf_counter()
    scores = vectors[indices] @ feature
    order = np.argsort(-scores, kind="stable")[:top_k]
    search_seconds = time.perf_counter() - started
    matches = []
    for rank, local_index in enumerate(order, 1):
        record = db["records"][indices[local_index]]
        matches.append({"rank": rank, "database_id": record["id"], "image_path": record["image_path"],
                        "similarity": float(scores[local_index]), "position_m": record["position_m"],
                        "yaw_deg": record["yaw_deg"], "point_id": record["point_id"]})
    result = {"created_at": timestamp(), "query_path": str(query), "query_sha256": byte_hash,
              "encoder": encoder.identity, "database_fingerprint": db["fingerprint"],
              "database_count": len(indices), "excluded_exact_copies": len(vectors) - len(indices),
              "embedding_seconds": encoder.last_seconds, "ranking_seconds": search_seconds,
              "position_semantics": "Returned coordinates are reference-camera locations, not a solved query camera pose.",
              "matches": matches}
    save_json(out / "results.json", result)
    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["rank", "database_id", "similarity", "x_m", "y_m", "z_m", "yaw_deg", "point_id", "image_path"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for match in matches:
            row = {k: match[k] for k in fields if k in match}
            row.update(dict(zip(("x_m", "y_m", "z_m"), match["position_m"])))
            writer.writerow(row)
    report = write_search_report(out, query, matches, result)
    print(f"Search complete: {report}", flush=True)
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("prepare", "build", "evaluate", "search", "run"):
        command = commands.add_parser(name)
        if name in {"prepare", "run"}:
            command.add_argument("--archive", required=True, type=Path)
            command.add_argument("--dataset", type=Path, default=ROOT / "data/isr_20261112")
            command.add_argument("--seed", type=int, default=42)
        if name in {"build", "evaluate"}:
            command.add_argument("--manifest", type=Path, default=ROOT / "data/isr_20261112/manifest.json")
        if name != "prepare":
            command.add_argument("--db", type=Path, default=ROOT / "output/isr_pipeline/db")
            command.add_argument("--model-cache", type=Path, default=ROOT / "models")
            command.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
            command.add_argument("--batch-size", type=int, default=1)
        if name in {"build", "run"}:
            command.add_argument("--rebuild", action="store_true")
        if name in {"evaluate", "run"}:
            command.add_argument("--out", type=Path, default=ROOT / "output/isr_pipeline/evaluation")
            command.add_argument("--split", choices=["all", "dev", "test"], default="all")
            command.add_argument("--distance-thresholds", nargs="+", type=float, default=[2.0, 3.0, 5.0])
            command.add_argument("--angle-threshold", type=float, default=30.0)
        if name == "search":
            command.add_argument("--query", required=True, type=Path)
            command.add_argument("--out", type=Path, default=ROOT / "output/isr_search")
            command.add_argument("--top-k", type=int, default=5)
    return cli


def main() -> None:
    args = parser().parse_args()
    if args.command in {"prepare", "run"}:
        manifest = prepare_dataset(args.archive, args.dataset, args.seed)
        print(f"Dataset ready: {args.dataset / 'manifest.json'}", flush=True)
        if args.command == "prepare":
            return
    elif args.command != "search":
        manifest = read_json(args.manifest)
    encoder = MegaLocEncoder(args.model_cache, args.device, args.batch_size)
    if args.command in {"build", "run"}:
        build_database(manifest, args.db, encoder, args.rebuild)
    if args.command in {"evaluate", "run"}:
        evaluate(manifest, args.db, args.out, encoder, args.split, args.distance_thresholds, args.angle_threshold)
    if args.command == "search":
        search(args.db, args.query, args.out, encoder, args.top_k)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
