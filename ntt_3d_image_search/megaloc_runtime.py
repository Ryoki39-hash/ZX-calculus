"""Frozen MegaLoc inference with an explicit, content-addressed encoder identity."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageOps


PREPROCESSING = "EXIF transpose; RGB; ToTensor; ImageNet normalize; resize 322x322 antialias; output L2 normalize"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_rgb(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


class MegaLocEncoder:
    def __init__(self, cache_dir: Path, device: str = "cpu", batch_size: int = 1):
        if batch_size < 1:
            raise ValueError("batch-size must be positive")
        self.cache_dir = cache_dir.resolve()
        self.source = self.cache_dir / "torch/hub/gmberton_MegaLoc_main/megaloc_model.py"
        weight_repo = self.cache_dir / "huggingface/hub/models--gberton--MegaLoc"
        ref = weight_repo / "refs/main"
        if not self.source.is_file() or not ref.is_file():
            raise ValueError("MegaLoc cache is missing. Use --model-cache with an existing models folder, or run megaloc_search.py once to download it.")
        revision = ref.read_text(encoding="utf-8").strip()
        self.weights = (weight_repo / "snapshots" / revision / "model.safetensors").resolve()
        if not self.weights.is_relative_to(weight_repo.resolve()) or not self.weights.is_file():
            raise ValueError("Invalid or missing cached MegaLoc checkpoint")
        self.identity = {
            "model": "gmberton/MegaLoc", "weights_revision": revision,
            "weights_sha256": sha256_file(self.weights), "source_sha256": sha256_file(self.source),
            "preprocessing": PREPROCESSING, "torch_version": importlib.metadata.version("torch"),
            "torchvision_version": importlib.metadata.version("torchvision"),
            "pillow_version": importlib.metadata.version("Pillow"), "training": False,
        }
        self.identity_hash = fingerprint(self.identity)
        self.requested_device = device
        self.batch_size = batch_size
        self.model = None
        self.device = device
        self.last_seconds = 0.0

    def _load(self) -> None:
        if self.model is not None:
            return
        import torch
        from safetensors.torch import load_file
        import torchvision.transforms as transforms

        self.device = "cuda" if self.requested_device == "auto" and torch.cuda.is_available() else self.requested_device
        if self.device == "auto":
            self.device = "cpu"
        if self.device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable; use --device cpu")
        torch.set_num_threads(min(8, os.cpu_count() or 1))
        spec = importlib.util.spec_from_file_location("isr_frozen_megaloc", self.source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(f"Loading frozen MegaLoc ({self.device}, offline).", flush=True)
        model = module.MegaLoc()
        model.load_state_dict(load_file(str(self.weights)), strict=True)
        self.model = model.eval().to(self.device)
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            transforms.Resize([322, 322], antialias=True),
        ])

    def embed(self, paths: list[Path]) -> np.ndarray:
        if not paths:
            raise ValueError("No images to embed")
        self._load()
        import torch
        import torch.nn.functional as functional

        chunks = []
        started = time.perf_counter()
        with torch.inference_mode():
            for start in range(0, len(paths), self.batch_size):
                batch = torch.stack([self.transform(read_rgb(path)) for path in paths[start:start + self.batch_size]])
                features = functional.normalize(self.model(batch.to(self.device)).float(), dim=1)
                chunks.append(features.cpu().numpy())
                print(f"Embedded {min(start + self.batch_size, len(paths))}/{len(paths)}", flush=True)
        self.last_seconds = time.perf_counter() - started
        vectors = np.concatenate(chunks).astype(np.float32)
        validate_vectors(vectors, len(paths))
        return vectors


def validate_vectors(vectors: np.ndarray, count: int) -> None:
    if vectors.ndim != 2 or vectors.shape[0] != count or vectors.shape[1] != 8448:
        raise ValueError("Invalid MegaLoc descriptor shape (expected N x 8448)")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4):
        raise ValueError("Descriptors must be finite and L2 normalized")
