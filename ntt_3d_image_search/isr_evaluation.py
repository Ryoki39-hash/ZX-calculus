"""Ground-truth evaluation for held-out ISR rendering viewpoints.

Retrieval scores determine rank only. Positions and orientations are used only
for evaluating those ranks; changing thresholds requires no model inference.
"""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral
from typing import Any

import numpy as np


BOUNDARY_TOLERANCE = 1e-9


def _records(records: list[dict], label: str) -> tuple[np.ndarray, np.ndarray]:
    if not records:
        raise ValueError(f"{label} must contain at least one image.")
    for key in ("id", "point_id", "sha256", "pixel_sha256"):
        if any(key not in row or row[key] is None or row[key] == "" for row in records):
            raise ValueError(f"Every {label} record needs a nonempty {key}.")
    ids = [row["id"] for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError(f"Duplicate image IDs in {label}.")
    try:
        positions = np.asarray([row["position_m"] for row in records], dtype=np.float64)
        yaws = np.asarray([row["yaw_deg"] for row in records], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid position_m or yaw_deg in {label}.") from error
    if positions.shape != (len(records), 3) or not np.isfinite(positions).all():
        raise ValueError(f"{label} position_m must contain three finite coordinates per image.")
    if yaws.shape != (len(records),) or not np.isfinite(yaws).all():
        raise ValueError(f"{label} yaw_deg must be a finite scalar per image.")
    return positions, yaws


def _stats(values: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "max": float(np.max(values)),
    }


def _thresholds(values: Sequence[float]) -> list[float]:
    try:
        thresholds = sorted(set(float(value) for value in values))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Distance thresholds must be finite nonnegative numbers.") from error
    if not thresholds or any(not np.isfinite(value) or value < 0 for value in thresholds):
        raise ValueError("Distance thresholds must be finite nonnegative numbers.")
    return thresholds


def _condition(positive: np.ndarray, order: np.ndarray, ks: list[int]) -> tuple[dict, list[dict]]:
    """Count each query once, with and without the DB coverage condition."""
    query_count, database_count = positive.shape
    ranked_positive = np.take_along_axis(positive, order, axis=1)
    positive_counts = positive.sum(axis=1)
    covered = positive_counts > 0
    covered_count = int(covered.sum())
    hits = {str(k): ranked_positive[:, :min(k, database_count)].any(axis=1) for k in ks}
    aggregate = {
        "coverage": {"count": covered_count, "total": query_count, "rate": covered_count / query_count},
        "recall": {},
    }
    for k, hit in hits.items():
        successes = int(hit.sum())
        aggregate["recall"][k] = {
            "successes": successes,
            "total": query_count,
            "rate": successes / query_count,
            "conditional_total": covered_count,
            "conditional_rate": successes / covered_count if covered_count else None,
            "effective_k": min(int(k), database_count),
        }
    details = [
        {
            "positive_count": int(positive_counts[i]),
            "first_positive_rank": int(np.flatnonzero(ranked_positive[i])[0]) + 1 if covered[i] else None,
            "hits": {k: bool(hit[i]) for k, hit in hits.items()},
        }
        for i in range(query_count)
    ]
    return aggregate, details


def evaluate_retrieval(
    database_records: list[dict],
    query_records: list[dict],
    scores: np.ndarray,
    distance_thresholds: Sequence[float] = (2.0, 3.0, 5.0),
    angle_threshold_deg: float = 30.0,
    ks: Sequence[int] = (1, 5, 10),
) -> dict[str, Any]:
    """Evaluate cosine-ranked results against known held-out rendering poses.

    Distances are Euclidean XY distances in meters. Yaw error is the shortest
    circular angular difference. Both threshold boundaries are inclusive with
    a 1e-9 numerical tolerance. No pitch/roll or visible-surface overlap is
    inferred from yaw. Queries lacking any positive DB image remain failures
    in the main Recall denominator and are reported separately via coverage.

    The DB/query split must be disjoint in image ID, point ID, file content,
    and RGB pixels. A query split may have several images at the same point.
    """
    database_positions, database_yaws = _records(database_records, "database")
    query_positions, query_yaws = _records(query_records, "queries")
    for key in ("id", "point_id", "sha256", "pixel_sha256"):
        overlap = {row[key] for row in database_records} & {row[key] for row in query_records}
        if overlap:
            raise ValueError(f"Database/query leakage: overlapping {key}: {sorted(map(str, overlap))[:5]}")
    thresholds = _thresholds(distance_thresholds)
    try:
        angle = float(angle_threshold_deg)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("angle_threshold_deg must be between 0 and 180.") from error
    if not np.isfinite(angle) or not 0 <= angle <= 180:
        raise ValueError("angle_threshold_deg must be between 0 and 180.")
    if not ks or any(isinstance(k, bool) or not isinstance(k, Integral) or k < 1 for k in ks):
        raise ValueError("ks must contain positive integers.")
    k_values = sorted(set(int(k) for k in ks))
    try:
        score_array = np.asarray(scores, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError("scores must be a finite cosine matrix.") from error
    expected_shape = (len(query_records), len(database_records))
    if score_array.shape != expected_shape or not np.isfinite(score_array).all():
        raise ValueError(f"scores must have shape {expected_shape} and contain finite values.")
    if (np.abs(score_array) > 1.0 + 1e-5).any():
        raise ValueError("scores must be cosine similarities in [-1, 1].")

    distances = np.linalg.norm(query_positions[:, None, :2] - database_positions[None, :, :2], axis=2)
    yaw_errors = np.abs((query_yaws[:, None] - database_yaws[None, :] + 180.0) % 360.0 - 180.0)
    order = np.argsort(-score_array, axis=1, kind="stable")
    query_indices = np.arange(len(query_records))
    top1_indices = order[:, 0]
    top1_distances = distances[query_indices, top1_indices]
    top1_yaws = yaw_errors[query_indices, top1_indices]
    details = []
    for i, query in enumerate(query_records):
        first = int(top1_indices[i])
        details.append({
            "query_id": query["id"],
            "point_id": query["point_id"],
            "top1_id": database_records[first]["id"],
            "top1_distance_m": float(top1_distances[i]),
            "top1_yaw_error_deg": float(top1_yaws[i]),
            "nearest_db_distance_m": float(distances[i].min()),
            "ranking": [
                {
                    "rank": rank,
                    "database_id": database_records[int(j)]["id"],
                    "similarity": float(score_array[i, j]),
                    "distance_m": float(distances[i, j]),
                    "yaw_error_deg": float(yaw_errors[i, j]),
                }
                for rank, j in enumerate(order[i, :max(k_values)], 1)
            ],
            "thresholds": [],
        })

    aggregated = []
    for distance in thresholds:
        place_positive = distances <= distance + BOUNDARY_TOLERANCE
        joint_positive = place_positive & (yaw_errors <= angle + BOUNDARY_TOLERANCE)
        place, place_details = _condition(place_positive, order, k_values)
        joint, joint_details = _condition(joint_positive, order, k_values)
        aggregated.append({"distance_m": distance, "place": place, "place_and_yaw": joint})
        for i in range(len(details)):
            details[i]["thresholds"].append({
                "distance_m": distance,
                "place": place_details[i],
                "place_and_yaw": joint_details[i],
            })

    return {
        "schema_version": 1,
        "definitions": {
            "ground_truth": "Known rendering camera position and yaw from query metadata; not model similarity.",
            "position_error": "Euclidean XY distance in meters; Z is not used.",
            "orientation_error": "Shortest circular yaw difference in degrees; pitch/roll are not evaluated.",
            "position_output": "Pose attached to a retrieved DB image; no continuous camera pose estimation.",
            "angle_threshold_deg": angle,
            "distance_thresholds_m": thresholds,
            "threshold_status": "Provisional analysis thresholds, not an approved deployment acceptance criterion.",
            "boundary_tolerance": BOUNDARY_TOLERANCE,
            "recall_denominator": "All evaluated queries, including queries without a positive database candidate.",
            "conditional_recall_denominator": "Only queries with at least one positive database candidate; null when none.",
            "coverage": "Fraction of queries with at least one positive database candidate.",
            "tie_break": "Original database row order (stable descending similarity sort).",
            "ks": k_values,
            "notes": [
                "A 30 degree yaw threshold on 90 degree sampled views is effectively a same-direction test.",
                "This evaluates rendering-to-rendering retrieval, not accuracy on real photographs.",
                "Yaw and position do not measure common visible surface area or occlusion.",
                "Threshold changes can be evaluated from saved scores without rebuilding embeddings.",
            ],
        },
        "counts": {
            "database_images": len(database_records),
            "queries": len(query_records),
            "query_points": len({row["point_id"] for row in query_records}),
        },
        "thresholds": aggregated,
        "top1": {"distance_m": _stats(top1_distances), "yaw_error_deg": _stats(top1_yaws)},
        "queries": details,
    }
