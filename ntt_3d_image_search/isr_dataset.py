"""Validate ISR renders and make a reproducible, point-disjoint evaluation split.

Metadata is used to prepare ground truth and the split, never as model input.
The prepared image directory contains all splits; consumers must select records
by ``split`` rather than recursively indexing that directory.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import random
import stat
from zipfile import ZipFile, ZipInfo

from PIL import Image


COORDINATE_SYSTEM = "UE world (left-handed, Z-up, X-forward, cm)"
SPLITS = ("database", "dev", "test")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _safe_entry(entry: ZipInfo) -> None:
    """Reject unsafe names even for archive files that will not be extracted."""
    # ZipInfo.filename normalizes backslashes on Windows; orig_filename keeps
    # the archive's raw name, including NULs and platform-specific separators.
    name = entry.orig_filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or ":" in name
        or path.is_absolute()
        or ".." in path.parts
        or any(part.endswith((".", " ")) for part in path.parts)
        or any(PureWindowsPath(part).is_reserved() for part in path.parts)
    ):
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    mode = entry.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError(f"ZIP symbolic links are not supported: {name}")
    if entry.flag_bits & 1:
        raise ValueError(f"Encrypted ZIP entries are not supported: {name}")


def _check_output_path(path: Path) -> None:
    """Do not write through a pre-existing link or Windows junction."""
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError(f"Output must not traverse a link or junction: {item}")


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _metadata_record(meta: dict, stem: str, image_name: str) -> dict:
    if meta.get("image_file") != image_name:
        raise ValueError(f"Metadata image_file does not match image: {stem}")
    if meta.get("coordinate_system") != COORDINATE_SYSTEM:
        raise ValueError(f"Unsupported coordinate system in {stem}")
    point = meta.get("point_id")
    if isinstance(point, bool) or not isinstance(point, int) or point < 1:
        raise ValueError(f"Invalid point_id in {stem}")
    position = meta.get("location_cm", {})
    rotation = meta.get("rotation_deg", {})
    if not isinstance(position, dict) or not isinstance(rotation, dict):
        raise ValueError(f"Position and rotation must be objects in {stem}")
    record = {
        "id": stem,
        "point_id": point,
        "position_m": [_finite_number(position.get(a), f"{stem}.location_cm.{a}") / 100 for a in "xyz"],
        "yaw_deg": _finite_number(rotation.get("yaw"), f"{stem}.yaw") % 360,
        "pitch_deg": _finite_number(rotation.get("pitch"), f"{stem}.pitch"),
        "roll_deg": _finite_number(rotation.get("roll"), f"{stem}.roll"),
    }
    camera = meta.get("camera", {})
    if not isinstance(camera, dict):
        raise ValueError(f"Camera must be an object in {stem}")
    for key in ("width", "height"):
        value = camera.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"Invalid camera {key} in {stem}")
    for key in ("fx", "fy", "cx", "cy", "fov_h_deg"):
        _finite_number(camera.get(key), f"{stem}.camera.{key}")
    if camera["fx"] <= 0 or camera["fy"] <= 0 or not 0 < camera["fov_h_deg"] < 180:
        raise ValueError(f"Invalid camera intrinsics in {stem}")
    record["camera"] = camera
    record["coordinate_system"] = COORDINATE_SYSTEM
    record["area_label"] = meta.get("area_label")
    return record


def _distance_xy(a: list[float], b: list[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_split(records: list[dict], seed: int) -> dict:
    by_point: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        by_point[record["point_id"]].append(record)
    if len(by_point) != 25:
        raise ValueError(f"This ISR protocol requires 25 points; found {len(by_point)}")
    positions: dict[int, list[float]] = {}
    for point, group in by_point.items():
        if len(group) != 4 or {r["yaw_deg"] for r in group} != {0.0, 90.0, 180.0, 270.0}:
            raise ValueError(f"Point {point} must have exactly four views at yaw 0/90/180/270")
        positions[point] = group[0]["position_m"]
        if any(r["position_m"] != positions[point] for r in group):
            raise ValueError(f"Different coordinates are assigned to point {point}")
        if any(r["pitch_deg"] != 0 or r["roll_deg"] != 0 for r in group):
            raise ValueError("This protocol requires level cameras (pitch = roll = 0)")
    if len({tuple(p) for p in positions.values()}) != 25:
        raise ValueError("Different point IDs must not use the same camera coordinates")
    if len({p[2] for p in positions.values()}) != 1:
        raise ValueError("This XY evaluation protocol requires a shared camera height")

    points = sorted(positions)
    rng = random.Random(seed)
    for attempt in range(1, 20001):
        candidate = points.copy()
        rng.shuffle(candidate)
        database = sorted(candidate[:15])
        held_out = candidate[15:]
        nearest = {
            p: min(_distance_xy(positions[p], positions[d]) for d in database)
            for p in held_out
        }
        if all(distance <= 3.0 + 1e-9 for distance in nearest.values()):
            return {
                "seed": seed,
                "database_points": database,
                "dev_points": sorted(held_out[:5]),
                "test_points": sorted(held_out[5:]),
                "strategy": "point-disjoint seeded shuffle; first 15/5/5 split with all held-out points covered within 3 m XY",
                "coverage_radius_m": 3.0,
                "candidate_attempts": attempt,
                "selection_uses": "camera coordinates only; no image features or retrieval results",
            }
    raise ValueError("No 15/5/5 split with 3 m held-out coverage was found in 20000 seeded candidates")


def _duplicate_groups(records: list[dict], key: str) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[record[key]].append(record["id"])
    return sorted((sorted(ids) for ids in groups.values() if len(ids) > 1), key=lambda ids: ids[0])


def prepare_dataset(zip_path: Path, out_dir: Path, seed: int = 42) -> dict:
    """Validate an ISR archive and prepare images plus a fixed evaluation manifest.

    Existing outputs are reused only when their bytes and the full manifest agree.
    Validation and all overwrite checks finish before any new output is written.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    zip_path = Path(zip_path).resolve(strict=True)
    out_dir = Path(out_dir).absolute()
    _check_output_path(out_dir)
    out_dir = out_dir.resolve()
    image_dir = out_dir / "images"
    manifest_path = out_dir / "manifest.json"
    for path in (image_dir, manifest_path):
        _check_output_path(path)
    source_hash = _file_hash(zip_path)

    records: list[dict] = []
    sources: dict[str, tuple[ZipInfo, str]] = {}
    with ZipFile(zip_path) as archive:
        entries: dict[str, ZipInfo] = {}
        for entry in archive.infolist():
            _safe_entry(entry)
            if entry.is_dir():
                continue
            key = PurePosixPath(entry.filename).name.casefold()
            if key in entries:
                raise ValueError(f"Duplicate flattened ZIP filename: {entry.filename}")
            entries[key] = entry
        pngs = {Path(name).stem: entry for name, entry in entries.items() if name.endswith(".png")}
        jsons = {Path(name).stem: entry for name, entry in entries.items() if name.endswith(".json")}
        if not pngs or pngs.keys() != jsons.keys():
            raise ValueError("Each PNG must have one matching JSON metadata file, with no orphan files")

        for key in sorted(pngs):
            image_entry, metadata_entry = pngs[key], jsons[key]
            image_name = PurePosixPath(image_entry.filename).name
            metadata_name = PurePosixPath(metadata_entry.filename).name
            stem = Path(image_name).stem
            if Path(metadata_name).stem != stem:
                raise ValueError(f"Image/metadata stem case mismatch: {image_name}")
            image_data, metadata_data = archive.read(image_entry), archive.read(metadata_entry)
            try:
                metadata = json.loads(metadata_data.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid JSON metadata: {metadata_name}") from error
            if not isinstance(metadata, dict):
                raise ValueError(f"Metadata must be an object: {metadata_name}")
            record = _metadata_record(metadata, stem, image_name)
            with Image.open(io.BytesIO(image_data)) as image:
                image.load()
                if image.format != "PNG":
                    raise ValueError(f"Expected PNG content: {image_name}")
                expected_size = (record["camera"]["width"], record["camera"]["height"])
                if image.size != expected_size:
                    raise ValueError(f"Image dimensions do not match metadata: {image_name}")
                pixel_bytes = str(image.size).encode("ascii") + b"\0" + image.convert("RGB").tobytes()
                record["pixel_sha256"] = _sha256(pixel_bytes)
            record.update({
                "image_path": str(image_dir / image_name),
                "metadata_path": str(image_dir / metadata_name),
                "sha256": _sha256(image_data),
                "metadata_sha256": _sha256(metadata_data),
            })
            records.append(record)
            sources[image_name] = (image_entry, record["sha256"])
            sources[metadata_name] = (metadata_entry, record["metadata_sha256"])

        split = _point_split(records, seed)
        point_to_split = {point: name for name in SPLITS for point in split[f"{name}_points"]}
        for record in records:
            record["split"] = point_to_split[record["point_id"]]
        duplicate_files = _duplicate_groups(records, "sha256")
        duplicate_pixels = _duplicate_groups(records, "pixel_sha256")
        by_id = {r["id"]: r for r in records}
        for group in duplicate_pixels:
            if len({by_id[item]["split"] for item in group}) > 1:
                raise ValueError(f"Identical images span database/dev/test splits: {', '.join(group)}")

        db = [r for r in records if r["split"] == "database"]
        held_out = [r for r in records if r["split"] != "database"]
        nearest = {
            r["id"]: min(_distance_xy(r["position_m"], d["position_m"]) for d in db)
            for r in held_out
        }
        coverage = []
        for threshold in (2.0, 3.0, 5.0):
            item = {"distance_m": threshold}
            for name in ("dev", "test", "all_holdout"):
                selected = [r for r in held_out if name == "all_holdout" or r["split"] == name]
                covered = sum(nearest[r["id"]] <= threshold + 1e-9 for r in selected)
                item[name] = {"covered_queries": covered, "total_queries": len(selected), "rate": covered / len(selected)}
            coverage.append(item)
        manifest = {
            "schema_version": 1,
            "dataset_root": str(out_dir),
            "source_zip_sha256": source_hash,
            "coordinate_system": COORDINATE_SYSTEM,
            "records": records,
            "split": split,
            "audit": {
                "image_count": len(records),
                "point_count": len(point_to_split),
                "split_image_counts": {name: sum(r["split"] == name for r in records) for name in SPLITS},
                "duplicate_file_groups": duplicate_files,
                "duplicate_pixel_groups": duplicate_pixels,
                "nearest_database_distance_m": nearest,
                "coverage_by_threshold_m": coverage,
                "distance_metric": "Euclidean XY distance in meters; camera height is constant",
                "scope": "render-to-render evaluation; real-photo localization is not validated",
            },
        }

        # Preflight every destination before creating directories or writing files.
        if out_dir.exists() and not out_dir.is_dir():
            raise ValueError(f"Output is not a directory: {out_dir}")
        if image_dir.exists() and not image_dir.is_dir():
            raise ValueError(f"Image output is not a directory: {image_dir}")
        for name, (_, expected_hash) in sources.items():
            destination = image_dir / name
            _check_output_path(destination)
            if destination.exists() and (not destination.is_file() or _file_hash(destination) != expected_hash):
                raise ValueError(f"Refusing to overwrite changed existing file: {destination}")
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Existing manifest is invalid: {manifest_path}") from error
            if existing != manifest:
                raise ValueError("Existing manifest differs; use a new output directory for a different source or seed")

        image_dir.mkdir(parents=True, exist_ok=True)
        for name, (entry, _) in sources.items():
            destination = image_dir / name
            if not destination.exists():
                with destination.open("xb") as stream:
                    stream.write(archive.read(entry))
        if not manifest_path.exists():
            with manifest_path.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
    return manifest
