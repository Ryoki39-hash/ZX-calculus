"""Persistent-cache and split tests without loading the 915 MB model."""

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import isr_pipeline
from megaloc_runtime import fingerprint, read_rgb, sha256_file


class FakeEncoder:
    def __init__(self, version=1):
        self.identity = {"model": "test-double", "version": version}
        self.identity_hash = fingerprint(self.identity)
        self.last_seconds = 0.25
        self.device = "cpu"
        self.calls = []

    def embed(self, paths):
        self.calls.append(list(paths))
        vectors = np.zeros((len(paths), 8448), dtype=np.float32)
        for index, path in enumerate(paths):
            feature = int(sha256_file(path)[:8], 16) % 8448
            vectors[index, feature] = 1.0
        return vectors


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "db"
        self.encoder = FakeEncoder()
        self.records = []
        for index, split in enumerate(("database", "database", "dev", "test")):
            path = self.root / f"image_{index}.png"
            Image.new("RGB", (12, 8), (index * 50, 5, 255 - index * 50)).save(path)
            rgb = read_rgb(path)
            self.records.append({
                "id": f"image_{index}", "point_id": index + 1,
                "image_path": str(path), "sha256": sha256_file(path),
                "pixel_sha256": hashlib.sha256(str(rgb.size).encode("ascii") + b"\0" + rgb.tobytes()).hexdigest(),
                "position_m": [float(index * 2), 0.0, 1.5],
                "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0, "split": split,
            })
        self.manifest = {"records": self.records, "source_zip_sha256": "fixture",
                         "dataset_root": str(self.root), "split": {"seed": 42}}

    def build(self):
        return isr_pipeline.build_database(self.manifest, self.db, self.encoder)

    def test_build_selects_only_database_rows_and_reuses_saved_vectors(self):
        first = self.build()
        second = self.build()
        metadata, vectors = isr_pipeline.load_database(self.db)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(self.encoder.calls), 1)
        self.assertEqual(self.encoder.calls[0], [Path(r["image_path"]) for r in self.records[:2]])
        self.assertEqual([r["split"] for r in metadata["records"]], ["database", "database"])
        self.assertEqual(vectors.shape, (2, 8448))
        self.assertEqual(second["embedding_seconds_this_run"], 0.0)

    def test_changed_database_image_is_rejected_before_reuse(self):
        self.build()
        Image.new("RGB", (12, 8), "red").save(self.records[0]["image_path"])
        with self.assertRaisesRegex(ValueError, "Image changed"):
            self.build()
        self.assertEqual(len(self.encoder.calls), 1)

    def test_corrupted_database_vectors_are_rejected(self):
        self.build()
        with (self.db / "embeddings.npz").open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "embeddings changed"):
            isr_pipeline.load_database(self.db)

    def test_changed_reference_pose_metadata_is_rejected(self):
        self.build()
        path = self.db / "database.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["records"][0]["position_m"][0] += 100
        path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            isr_pipeline.load_database(self.db)

    def test_changed_encoder_requires_explicit_rebuild(self):
        self.build()
        different = FakeEncoder(version=2)
        with self.assertRaisesRegex(ValueError, "model, inputs or split changed"):
            isr_pipeline.build_database(self.manifest, self.db, different)
        self.assertEqual(different.calls, [])

    def test_inconsistent_encoder_identity_metadata_is_rejected(self):
        self.build()
        path = self.db / "database.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["encoder_fingerprint"] = "wrong_fingerprint"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "encoder identity is inconsistent"):
            isr_pipeline.load_database(self.db)

    def test_query_cache_reuses_features_and_rejects_corruption(self):
        output = self.root / "evaluation"
        first, first_info = isr_pipeline.query_embeddings(self.records[2:], output, self.encoder)
        reused, second_info = isr_pipeline.query_embeddings(self.records[2:], output, self.encoder)
        self.assertFalse(first_info["reused"])
        self.assertTrue(second_info["reused"])
        self.assertEqual(len(self.encoder.calls), 1)
        np.testing.assert_array_equal(first, reused)
        with (output / "query_embeddings.npz").open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "cache is corrupted"):
            isr_pipeline.query_embeddings(self.records[2:], output, self.encoder)
        self.assertEqual(len(self.encoder.calls), 1)

    def test_evaluation_rejects_point_leak_before_embedding_queries(self):
        self.build()
        self.records[2]["point_id"] = self.records[0]["point_id"]
        with self.assertRaisesRegex(ValueError, "point_id"):
            isr_pipeline.evaluate(self.manifest, self.db, self.root / "evaluation", self.encoder,
                                  "dev", [2, 3, 5], 30)
        self.assertEqual(len(self.encoder.calls), 1)

    def test_re_evaluation_changes_thresholds_without_new_inference(self):
        self.build()
        output = self.root / "evaluation"
        with patch.object(isr_pipeline, "write_evaluation_report", return_value=output / "report.html"):
            first = isr_pipeline.evaluate(self.manifest, self.db, output, self.encoder, "dev", [2], 30)
            second = isr_pipeline.evaluate(self.manifest, self.db, output, self.encoder, "dev", [5, 5], 30)
        self.assertEqual(len(self.encoder.calls), 2)  # One DB batch, one query batch.
        self.assertEqual(first["queries"][0]["ranking"], second["queries"][0]["ranking"])
        self.assertEqual(len(second["thresholds"]), 1)
        with (output / "per_query.csv").open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        self.assertEqual(len(header), len(set(header)))
        run = json.loads((output / "run.json").read_text(encoding="utf-8"))
        self.assertTrue(run["query_cache"]["reused"])

    def test_search_excludes_pixel_identical_copy_and_labels_reference_pose(self):
        self.build()
        query = self.root / "reencoded.png"
        read_rgb(Path(self.records[0]["image_path"])).save(query, compress_level=0)
        self.assertNotEqual(sha256_file(query), self.records[0]["sha256"])
        with patch.object(isr_pipeline, "write_search_report", return_value=self.root / "report.html"):
            result = isr_pipeline.search(self.db, query, self.root / "search", self.encoder, 5)
        self.assertEqual(result["excluded_exact_copies"], 1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["database_id"], "image_1")
        self.assertEqual(result["matches"][0]["position_m"], self.records[1]["position_m"])
        self.assertIn("reference-camera", result["position_semantics"])


if __name__ == "__main__":
    unittest.main()
