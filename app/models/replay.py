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


def _read_json(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read evaluation pack JSON {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"evaluation pack JSON must be a list: {path}")
    return data


class ReplayModel(WallSegmenter, OpeningDetector):
    def __init__(self, pack_dir: str | Path | None, variant: str = "gt") -> None:
        if not pack_dir:
            raise ValueError("replay needs models.replay.pack_dir or AUTOBIM_REPLAY_PACK")
        if variant != "gt" and not re.fullmatch(r"pred/[^\s/\\]+", variant):
            raise ValueError("replay variant must be gt or pred/<bundle name> without whitespace")
        if variant in {"pred/.", "pred/.."}:
            raise ValueError("replay variant must be gt or pred/<bundle name>")
        self.pack_dir = Path(pack_dir)
        self.variant = variant
        manifest_path = self.pack_dir / "manifest.json"
        manifest = _read_json(manifest_path)
        for folder in ("labels", "openings"):
            path = self.pack_dir / folder / variant
            if not path.is_dir():
                raise ValueError(f"evaluation pack variant directory missing: {path}")
        self._images: dict[str, tuple[int, int]] = {}
        for index, entry in enumerate(manifest):
            context = f"{manifest_path}, entry {index}"
            if not isinstance(entry, dict):
                raise ValueError(f"evaluation pack manifest entry must be an object: {context}")
            missing = {"sha1", "height", "width"} - entry.keys()
            if missing:
                raise ValueError(f"evaluation pack manifest missing {sorted(missing)}: {context}")
            sha1, height, width = entry["sha1"], entry["height"], entry["width"]
            if not isinstance(sha1, str) or not re.fullmatch(r"[0-9a-f]{40}", sha1):
                raise ValueError(f"evaluation pack manifest sha1 must be 40 lowercase hex: {context}")
            if any(type(value) is not int or value <= 0 for value in (height, width)):
                raise ValueError(f"evaluation pack dimensions must be positive integers: {context}")
            if sha1 in self._images and self._images[sha1] != (height, width):
                raise ValueError(f"evaluation pack has conflicting dimensions for sha1={sha1}: {context}")
            self._images[sha1] = (height, width)
            for folder, suffix in (("labels", "png"), ("openings", "json")):
                path = self.pack_dir / folder / variant / f"{sha1}.{suffix}"
                if not path.is_file():
                    raise ValueError(f"evaluation pack file missing: {path} ({context})")

    def _key(self, image: np.ndarray) -> str:
        # Hash the buffer directly; normal RGB arrays need no tobytes() allocation.
        sha1 = hashlib.sha1(np.ascontiguousarray(image)).hexdigest()
        if sha1 not in self._images:
            raise ValueError(f"이미지가 평가 팩에 없음: sha1={sha1}")
        if image.shape[:2] != self._images[sha1]:
            raise ValueError(f"evaluation pack image dimensions mismatch: sha1={sha1}")
        return sha1

    def segment(self, image: np.ndarray) -> WallMask:
        sha1 = self._key(image)
        path = self.pack_dir / "labels" / self.variant / f"{sha1}.png"
        try:
            with Image.open(path) as source:
                labels = np.asarray(source)
        except OSError as exc:
            raise ValueError(f"cannot read evaluation pack labels {path}: {exc}") from exc
        if labels.shape != image.shape[:2] or labels.dtype != np.uint8:
            raise ValueError(f"evaluation pack labels must be (H, W) uint8: {path}")
        # Only class 1 is wall; ignore (255), doors and windows are background here.
        # Packs contain no wall probabilities, so both gt/pred use WallMask's default 1.0.
        return WallMask(mask=labels == 1)

    def detect(self, image: np.ndarray) -> list[OpeningDetection]:
        sha1 = self._key(image)
        path = self.pack_dir / "openings" / self.variant / f"{sha1}.json"
        detections = []
        for index, item in enumerate(_read_json(path)):
            try:
                if not isinstance(item, dict):
                    raise ValueError("opening must be an object")
                bbox = item["bbox"]
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError("bbox must contain four coordinates")
                coords = tuple(float(value) for value in bbox)
                confidence = float(item["conf"])
                if not all(np.isfinite(value) for value in (*coords, confidence)):
                    raise ValueError("bbox and confidence must be finite")
                if coords[0] >= coords[2] or coords[1] >= coords[3]:
                    raise ValueError("bbox must have positive width and height")
                if not 0 <= confidence <= 1:
                    raise ValueError("confidence must be between 0 and 1")
                detections.append(
                    OpeningDetection(OpeningType(item["type"]), BBox(*coords), confidence)
                )
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"invalid evaluation pack opening: {path}, entry {index}: {exc}") from exc
        return detections
