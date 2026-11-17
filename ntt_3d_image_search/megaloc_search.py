"""Folder-based MegaLoc retrieval: one query, five results, one report image."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MODEL_REPO = "gmberton/MegaLoc"
TOP_K = 5
PROJECT_ROOT = Path(__file__).resolve().parent


def read_image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect_images(database: Path, query: Path) -> tuple[list[Path], int]:
    """Exclude the query itself, including byte-identical copies in the database."""
    query_hash = digest(query)
    candidates = sorted(
        (p for p in database.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS),
        key=lambda p: p.as_posix().casefold(),
    )
    paths = [p for p in candidates if p.resolve() != query and digest(p) != query_hash]
    if len(paths) < TOP_K:
        raise ValueError(f"Need at least {TOP_K} database images after excluding the query; found {len(paths)}.")
    for path in [query, *paths]:
        try:
            read_image(path)
        except (OSError, ValueError) as error:
            raise ValueError(f"Cannot read image: {path}: {error}") from error
    return paths, len(candidates) - len(paths)


def rank_images(database_vectors: np.ndarray, query_vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    scores = database_vectors @ query_vector
    if not np.isfinite(scores).all():
        raise ValueError("Model produced non-finite similarity scores.")
    order = np.argsort(-scores, kind="stable")[:TOP_K]
    return order, scores


def font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/meiryo.ttc", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def fit_label(draw: ImageDraw.ImageDraw, label: str, text_font: ImageFont.ImageFont, width: int) -> str:
    while draw.textlength(label, font=text_font) > width and len(label) > 4:
        label = label[:-4] + "..."
    return label


def write_report(out: Path, query: Path, rows: list[dict], metadata: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (1500, 1000), "#eef2f6")
    draw = ImageDraw.Draw(canvas)
    title_font, body_font = font(26), font(19)
    draw.text((24, 16), "MegaLoc | Query + Top 5", font=font(32), fill="#183049")
    draw.text((24, 64), "Cosine similarity | Retrieval only | No geometric verification", font=body_font, fill="#526578")
    cards = [("QUERY", query)] + [
        (f"#{row['rank']}  |  cosine {row['similarity']:.4f}", Path(row["path"])) for row in rows
    ]
    for index, (label, path) in enumerate(cards):
        x, y = 24 + (index % 3) * 492, 114 + (index // 3) * 434
        draw.rounded_rectangle((x, y, x + 468, y + 408), radius=12, fill="white")
        draw.text((x + 14, y + 10), label, font=title_font, fill="#183049")
        preview = ImageOps.contain(read_image(path), (440, 310))
        canvas.paste(preview, (x + 14 + (440 - preview.width) // 2, y + 54 + (310 - preview.height) // 2))
        draw.text((x + 14, y + 374), fit_label(draw, path.name, body_font, 440), font=body_font, fill="#526578")
    canvas.save(out / "top5.png")

    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["rank", "filename", "similarity", "path"])
        writer.writeheader()
        writer.writerows(rows)
    (out / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    table = "".join(
        f"<tr><td>{r['rank']}</td><td>{html.escape(r['filename'])}</td><td>{r['similarity']:.6f}</td></tr>"
        for r in rows
    )
    (out / "report.html").write_text(
        '<!doctype html><html lang="ja"><meta charset="utf-8"><title>MegaLoc 検索結果</title>'
        '<style>body{font:16px sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#183049}'
        'img{width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style>'
        '<h1>MegaLoc：クエリ1枚と上位5件</h1>'
        f'<p>クエリ：{html.escape(query.name)} ／ 検索対象：{metadata["database_count"]}枚</p>'
        '<p>学習済みモデル・コサイン類似度・幾何検証なし。類似度は正解確率ではありません。</p>'
        '<img src="top5.png" alt="クエリ画像と検索上位5件">'
        '<table><tr><th>順位</th><th>ファイル名</th><th>コサイン類似度</th></tr>' + table + '</table>'
        '<p>Notionには top5.png をアップロードし、この条件と表を添付してください。</p></html>',
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="Folder of reference images (recursive)")
    parser.add_argument("--query", required=True, type=Path, help="One query image")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "output" / "megaloc")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / "models",
                        help="Model directory (default: project/models)")
    args = parser.parse_args()
    database, query, out = args.database.resolve(), args.query.resolve(), args.out.resolve()
    if not database.is_dir() or not query.is_file():
        parser.error("--database must be a directory and --query must be an existing image file.")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive.")
    if out.is_relative_to(database):
        parser.error("--out must be outside --database so exported images cannot enter future searches.")
    paths, excluded = collect_images(database, query)

    cache = args.cache_dir.resolve()
    os.environ["HF_HOME"] = str(cache / "huggingface")
    os.environ["TORCH_HOME"] = str(cache / "torch")
    os.environ["HF_HUB_CACHE"] = str(cache / "huggingface" / "hub")
    local_repo = cache / "torch" / "hub" / "gmberton_MegaLoc_main"
    weight_repo = cache / "huggingface" / "hub" / "models--gberton--MegaLoc"
    main_ref = weight_repo / "refs" / "main"
    cached_weights = False
    if main_ref.is_file():
        revision = main_ref.read_text(encoding="utf-8").strip()
        cached_weights = (weight_repo / "snapshots" / revision / "model.safetensors").is_file()
    use_local_model = (local_repo / "hubconf.py").is_file() and cached_weights
    if use_local_model:
        # Read the existing official source and weights without contacting the network.
        os.environ["HF_HUB_OFFLINE"] = "1"
    import torch
    import torch.nn.functional as functional
    import torchvision.transforms as transforms

    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA is unavailable; use --device cpu or install a suitable CUDA-enabled PyTorch.")
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    if use_local_model:
        print(f"Loading pretrained MegaLoc on {device} from {cache} (offline).", flush=True)
        model = torch.hub.load(str(local_repo), "get_trained_model", source="local").eval().to(device)
    else:
        print(f"Loading pretrained MegaLoc on {device}. First run downloads source and weights to {cache}.", flush=True)
        model = torch.hub.load(MODEL_REPO, "get_trained_model", trust_repo=True).eval().to(device)
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        transforms.Resize(size=[322, 322], antialias=True),
    ])
    vectors = []
    image_paths = [query, *paths]
    with torch.inference_mode():
        for start in range(0, len(image_paths), args.batch_size):
            batch_paths = image_paths[start:start + args.batch_size]
            batch = torch.stack([transform(read_image(p)) for p in batch_paths]).to(device)
            vectors.append(functional.normalize(model(batch).float(), dim=1).cpu().numpy())
            print(f"Embedded {min(start + args.batch_size, len(image_paths))}/{len(image_paths)} images", flush=True)
    descriptors = np.concatenate(vectors)
    order, scores = rank_images(descriptors[1:], descriptors[0])
    rows = [
        {"rank": rank, "filename": paths[index].relative_to(database).as_posix(),
         "similarity": float(scores[index]), "path": str(paths[index])}
        for rank, index in enumerate(order, 1)
    ]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_REPO, "model_entrypoint": "get_trained_model", "device": device,
        "model_cache": str(cache), "model_loaded_offline": use_local_model,
        "torch_version": torch.__version__, "descriptor_dimensions": int(descriptors.shape[1]),
        "preprocessing": "EXIF orientation, RGB, ImageNet normalization, resize 322x322",
        "database": str(database), "query": str(query), "database_count": len(paths),
        "excluded_query_copies": excluded, "similarity": "cosine", "top_k": TOP_K,
        "geometric_verification": False, "results": rows,
        "inputs": [{"path": str(p), "sha256": digest(p)} for p in image_paths],
    }
    write_report(out, query, rows, metadata)
    np.savez_compressed(out / "embeddings.npz", query=descriptors[0], database=descriptors[1:],
                        paths=np.array([str(p) for p in paths]))
    print(f"Done: {out / 'report.html'}\nNotion image: {out / 'top5.png'}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
