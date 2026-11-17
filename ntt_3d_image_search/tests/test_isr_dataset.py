from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image

from isr_dataset import COORDINATE_SYSTEM, prepare_dataset


def make_archive(path: Path, *, wrong_size: bool = False, extra: tuple[str, bytes] | None = None) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for point in range(1, 26):
            for direction, yaw in enumerate((0, 90, 180, 270)):
                stem = f"p{point:02d}_yaw{yaw:03d}"
                pixels = io.BytesIO()
                Image.new("RGB", (8, 8), (point * 7, direction * 50, point + direction)).save(pixels, format="PNG")
                metadata = {
                    "image_file": stem + ".png",
                    "point_id": point,
                    "coordinate_system": COORDINATE_SYSTEM,
                    "location_cm": {"x": ((point - 1) % 5) * 200, "y": ((point - 1) // 5) * 200, "z": 150},
                    "rotation_deg": {"yaw": yaw, "pitch": 0, "roll": 0},
                    "camera": {"width": 9 if wrong_size else 8, "height": 8, "fx": 4, "fy": 4, "cx": 4, "cy": 4, "fov_h_deg": 90},
                }
                archive.writestr("dataset/" + stem + ".png", pixels.getvalue())
                archive.writestr("dataset/" + stem + ".json", json.dumps(metadata))
        if extra:
            entry = ZipInfo(extra[0])
            # ZipInfo normalizes backslashes on Windows; restore the malicious
            # name to exercise validation of an archive made on another OS.
            entry.filename = extra[0]
            archive.writestr(entry, extra[1])


class DatasetPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "input.zip"
        make_archive(self.archive)

    def tearDown(self):
        self.temp.cleanup()

    def test_split_is_point_disjoint_reproducible_and_covered(self):
        result = prepare_dataset(self.archive, self.root / "prepared")
        again = prepare_dataset(self.archive, self.root / "prepared")
        self.assertEqual(result, again)
        self.assertEqual(result["audit"]["split_image_counts"], {"database": 60, "dev": 20, "test": 20})
        point_sets = [set(result["split"][name + "_points"]) for name in ("database", "dev", "test")]
        self.assertEqual([len(s) for s in point_sets], [15, 5, 5])
        self.assertEqual(len(set.union(*point_sets)), 25)
        for point in range(1, 26):
            self.assertEqual(len({r["split"] for r in result["records"] if r["point_id"] == point}), 1)
        self.assertLessEqual(max(result["audit"]["nearest_database_distance_m"].values()), 3.0)
        self.assertEqual(result["records"][0]["position_m"][2], 1.5)
        self.assertEqual(prepare_dataset(self.archive, self.root / "second")["split"], result["split"])

    def test_traversal_rejected_before_output(self):
        for index, name in enumerate(("../escape.txt", "/escape.txt", "folder\\escape.txt", "C:/escape.txt", "dataset/CON.txt")):
            with self.subTest(name=name):
                bad = self.root / "bad.zip"
                make_archive(bad, extra=(name, b"bad"))
                with self.assertRaisesRegex(ValueError, "Unsafe ZIP path"):
                    prepare_dataset(bad, self.root / f"bad-output-{index}")
                self.assertFalse((self.root / f"bad-output-{index}").exists())

    def test_symbolic_link_rejected(self):
        with ZipFile(self.archive, "a") as archive:
            entry = ZipInfo("dataset/link")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "../../outside")
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            prepare_dataset(self.archive, self.root / "prepared")

    def test_changed_existing_image_is_not_overwritten(self):
        result = prepare_dataset(self.archive, self.root / "prepared")
        image = Path(result["records"][0]["image_path"])
        image.write_bytes(b"user modification")
        manifest = (self.root / "prepared" / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
            prepare_dataset(self.archive, self.root / "prepared")
        self.assertEqual(image.read_bytes(), b"user modification")
        self.assertEqual((self.root / "prepared" / "manifest.json").read_bytes(), manifest)

    def test_changed_split_seed_requires_new_output(self):
        prepare_dataset(self.archive, self.root / "prepared")
        with self.assertRaisesRegex(ValueError, "Existing manifest differs"):
            prepare_dataset(self.archive, self.root / "prepared", seed=43)

    def test_metadata_dimensions_must_match_before_writing(self):
        bad = self.root / "bad-size.zip"
        make_archive(bad, wrong_size=True)
        with self.assertRaisesRegex(ValueError, "dimensions do not match"):
            prepare_dataset(bad, self.root / "prepared")
        self.assertFalse((self.root / "prepared").exists())

    def test_identical_pixels_across_splits_are_rejected(self):
        reference = prepare_dataset(self.archive, self.root / "reference")
        database = next(r for r in reference["records"] if r["split"] == "database")
        query = next(r for r in reference["records"] if r["split"] == "test")
        bad = self.root / "duplicate.zip"
        with ZipFile(self.archive) as source, ZipFile(bad, "w") as target:
            duplicate = source.read(f"dataset/{database['id']}.png")
            for info in source.infolist():
                data = duplicate if info.filename == f"dataset/{query['id']}.png" else source.read(info)
                target.writestr(info, data)
        with self.assertRaisesRegex(ValueError, "Identical images span"):
            prepare_dataset(bad, self.root / "duplicate-output")
        self.assertFalse((self.root / "duplicate-output").exists())


if __name__ == "__main__":
    unittest.main()
