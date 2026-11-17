"""Download 15 reference images and one query from OpenCV's public samples."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from PIL import Image


REFERENCE_FILES = [
    "graf3.png", "building.jpg", "fruits.jpg", "baboon.jpg", "messi5.jpg",
    "left01.jpg", "right01.jpg", "box.png", "box_in_scene.png",
    "basketball1.png", "basketball2.png", "blox.jpg", "home.jpg",
    "sudoku.png", "smarties.png",
]
QUERY_FILE = "graf1.png"
BASE_URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/opencv_demo"))
    args = parser.parse_args()
    root = args.out.resolve()
    records = []
    for filename in [QUERY_FILE, *REFERENCE_FILES]:
        role = "query" if filename == QUERY_FILE else "reference"
        destination = root / role / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = BASE_URL + filename
        if not destination.exists():
            print(f"Downloading {filename}", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "MegaLoc-PoC/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                contents = response.read()
            temporary = destination.with_suffix(destination.suffix + ".part")
            temporary.write_bytes(contents)
            with Image.open(temporary) as image:
                image.verify()
            temporary.replace(destination)
        with Image.open(destination) as image:
            image.verify()
        records.append({
            "role": role, "filename": filename, "source_url": url,
            "local_path": destination.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        })
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://github.com/opencv/opencv/tree/4.x/samples/data",
        "purpose": "Pipeline smoke test; not a place-recognition accuracy benchmark",
        "query_count": 1, "reference_count": len(REFERENCE_FILES), "images": records,
    }
    (root / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(records)} images in {root}", flush=True)


if __name__ == "__main__":
    main()
