"""Replay evaluation-pack masks and opening boxes without a model runtime."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from app.models.base import BBox, OpeningDetection, OpeningDetector, WallMask, WallSegmenter
from app.schemas.plan import OpeningType


class ReplayModel(WallSegmenter, OpeningDetector):
    def __init__(self, pack_dir: str | Path | None, variant: str = "gt") -> None:
        if not pack_dir:
            raise ValueError("replay needs models.replay.pack_dir or AUTOBIM_REPLAY_PACK")
        if variant != "gt" and not re.fullmatch(r"pred/[^/\\]+", variant):
            raise ValueError("replay variant must be gt or pred/<bundle name>")
        if variant in {"pred/.", "pred/.."}:
            raise ValueError("replay variant must be gt or pred/<bundle name>")
        self.pack_dir = Path(pack_dir)
        self.variant = variant
        manifest = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
        self._images = {entry["sha1"]: (entry["height"], entry["width"]) for entry in manifest}

    def _key(self, image: np.ndarray) -> str:
        sha1 = hashlib.sha1(image.tobytes()).hexdigest()
        if sha1 not in self._images:
            raise ValueError(f"이미지가 평가 팩에 없음: sha1={sha1}")
        if image.shape[:2] != self._images[sha1]:
            raise ValueError(f"evaluation pack image dimensions mismatch: sha1={sha1}")
        return sha1

    def segment(self, image: np.ndarray) -> WallMask:
        sha1 = self._key(image)
        with Image.open(self.pack_dir / "labels" / self.variant / f"{sha1}.png") as source:
            labels = np.asarray(source)
        if labels.shape != image.shape[:2] or labels.dtype != np.uint8:
            raise ValueError(f"evaluation pack labels must be (H, W) uint8: sha1={sha1}")
        # Only class 1 is wall; ignore (255), doors and windows are background here.
        return WallMask(mask=labels == 1)

    def detect(self, image: np.ndarray) -> list[OpeningDetection]:
        sha1 = self._key(image)
        path = self.pack_dir / "openings" / self.variant / f"{sha1}.json"
        return [
            OpeningDetection(
                type=OpeningType(item["type"]),
                bbox=BBox(*(float(value) for value in item["bbox"])),
                confidence=float(item["conf"]),
            )
            for item in json.loads(path.read_text(encoding="utf-8"))
        ]
