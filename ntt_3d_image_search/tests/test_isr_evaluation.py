"""Tests for evaluation failure modes that can silently inflate results."""

import json
import unittest

import numpy as np

from isr_evaluation import evaluate_retrieval


def record(name, point, x, y=0.0, yaw=0.0, z=1.5):
    return {
        "id": name, "point_id": point, "position_m": [x, y, z], "yaw_deg": yaw,
        "pitch_deg": 0.0, "roll_deg": 0.0,
        "sha256": "file_" + name, "pixel_sha256": "pixel_" + name,
    }


class EvaluationTests(unittest.TestCase):
    def test_recall_counts_queries_once_and_keeps_uncovered_queries(self):
        database = [record("near", 1, 2), record("also_near", 2, 1), record("far", 3, 8)]
        queries = [record("covered", 11, 0), record("uncovered", 12, 20)]
        scores = np.array([[0.8, 0.7, 0.9], [0.2, 0.1, 0.9]])
        result = evaluate_retrieval(database, queries, scores, distance_thresholds=(2,), ks=(1, 2, 5))
        stats = result["thresholds"][0]["place"]
        self.assertEqual(stats["coverage"], {"count": 1, "total": 2, "rate": 0.5})
        self.assertEqual(stats["recall"]["1"]["rate"], 0.0)
        self.assertEqual(stats["recall"]["2"]["successes"], 1)
        self.assertEqual(stats["recall"]["5"]["rate"], 0.5)
        self.assertEqual(stats["recall"]["5"]["conditional_rate"], 1.0)
        self.assertEqual(stats["recall"]["5"]["effective_k"], 3)
        self.assertEqual(result["queries"][0]["thresholds"][0]["place"]["positive_count"], 2)
        self.assertEqual(result["queries"][0]["thresholds"][0]["place"]["first_positive_rank"], 2)
        self.assertIsNone(result["queries"][1]["thresholds"][0]["place"]["first_positive_rank"])
        self.assertEqual(result["queries"][0]["top1_distance_m"], 8.0)
        self.assertEqual(result["queries"][0]["nearest_db_distance_m"], 1.0)

    def test_yaw_wrap_and_joint_condition_use_same_candidate(self):
        database = [record("near_wrong_yaw", 1, 1, yaw=180), record("near_wrapped", 2, 2, yaw=10)]
        queries = [record("q", 11, 0, yaw=350)]
        result = evaluate_retrieval(database, queries, [[0.9, 0.8]], distance_thresholds=(2,), angle_threshold_deg=20, ks=(1, 2))
        stats = result["thresholds"][0]
        self.assertEqual(stats["place"]["recall"]["1"]["rate"], 1.0)
        self.assertEqual(stats["place_and_yaw"]["recall"]["1"]["rate"], 0.0)
        self.assertEqual(stats["place_and_yaw"]["recall"]["2"]["rate"], 1.0)
        self.assertEqual(result["queries"][0]["ranking"][1]["yaw_error_deg"], 20.0)

    def test_no_coverage_reports_null_conditional_recall_and_is_json_safe(self):
        result = evaluate_retrieval([record("d", 1, 10)], [record("q", 11, 0)], [[0.5]], distance_thresholds=(1,))
        stats = result["thresholds"][0]["place"]
        self.assertEqual(stats["coverage"]["rate"], 0.0)
        self.assertEqual(stats["recall"]["1"]["rate"], 0.0)
        self.assertIsNone(stats["recall"]["1"]["conditional_rate"])
        json.dumps(result, allow_nan=False)

    def test_boundaries_are_inclusive_and_distance_is_xy(self):
        result = evaluate_retrieval(
            [record("d", 1, 2.0 + 1e-12, yaw=30.0, z=50)], [record("q", 11, 0)], [[1.0]],
            distance_thresholds=(2.0,), angle_threshold_deg=30.0,
        )
        self.assertEqual(result["thresholds"][0]["place_and_yaw"]["recall"]["1"]["rate"], 1.0)

    def test_stable_ranking_and_threshold_changes_do_not_change_rank(self):
        database = [record("first", 1, 5), record("second", 2, 1)]
        query = [record("q", 11, 0)]
        scores = [[0.8, 0.8]]
        a = evaluate_retrieval(database, query, scores, distance_thresholds=(2,))
        b = evaluate_retrieval(database, query, scores, distance_thresholds=(5,))
        self.assertEqual(a["queries"][0]["top1_id"], "first")
        self.assertEqual(a["queries"][0]["ranking"], b["queries"][0]["ranking"])
        self.assertEqual(a["thresholds"][0]["place"]["recall"]["1"]["rate"], 0.0)
        self.assertEqual(b["thresholds"][0]["place"]["recall"]["1"]["rate"], 1.0)

    def test_rejects_identity_point_and_content_leakage(self):
        for key in ("id", "point_id", "sha256", "pixel_sha256"):
            with self.subTest(key=key):
                database = [record("d", 1, 1)]
                queries = [record("q", 11, 0)]
                queries[0][key] = database[0][key]
                with self.assertRaisesRegex(ValueError, "leakage"):
                    evaluate_retrieval(database, queries, [[0.5]])

    def test_rejects_invalid_inputs(self):
        database, queries = [record("d", 1, 1)], [record("q", 11, 0)]
        for scores in ([[float("nan")]], [[float("inf")]], [[0.1, 0.2]], [[1.1]]):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                evaluate_retrieval(database, queries, scores)
        for options in ({"ks": (0,)}, {"ks": (1.5,)}, {"ks": ()}, {"angle_threshold_deg": 181},
                        {"distance_thresholds": ()}, {"distance_thresholds": (-1,)}, {"distance_thresholds": (float("inf"),)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                evaluate_retrieval(database, queries, [[0.1]], **options)
        with self.assertRaises(ValueError):
            evaluate_retrieval([], queries, np.empty((1, 0)))
        with self.assertRaises(ValueError):
            evaluate_retrieval(database, [], np.empty((0, 1)))
        invalid_query = record("q", 11, float("nan"))
        with self.assertRaises(ValueError):
            evaluate_retrieval(database, [invalid_query], [[0.1]])


if __name__ == "__main__":
    unittest.main()
