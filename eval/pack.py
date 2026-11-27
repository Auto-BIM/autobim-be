"""Open an evaluation pack (docs/next-tasks.md, #11 (BE-N2)) for evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.models.replay import ReplayModel
from app.preprocess.image import load_image


class PackError(Exception):
    """The pack is missing or malformed: a user error, not a failed image."""


@dataclass
class Sample:
    id: str
    image: np.ndarray
    ignore: np.ndarray | None = None  # True where the pack has no ground truth


def open_variant(pack: Path, variant: str) -> ReplayModel:
    try:
        return ReplayModel(pack, variant)
    except ValueError as exc:
        raise PackError(f"평가 팩을 열 수 없음 ({variant}): {exc}") from exc


def _load_ignore(pack: Path, sha1: str, shape: tuple[int, int]) -> np.ndarray | None:
    """`ignore/gt/<sha1>.png` (255 = no ground truth); packs without it just have no ignore area."""
    path = pack / "ignore" / "gt" / f"{sha1}.png"
    if not path.is_file():
        return None
    try:
        with Image.open(path) as source:
            mask = np.asarray(source) == 255
    except OSError as exc:
        raise PackError(f"ignore 마스크를 읽을 수 없음: {path}: {exc}") from exc
    if mask.shape != shape:
        raise PackError(f"ignore 마스크 크기가 이미지와 다름: {path}")
    return mask


def iter_samples(pack: Path):
    """Images in manifest order, one at a time; each must hash to the manifest's sha1 like replay expects."""
    try:
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackError(f"manifest.json을 읽을 수 없음: {pack}: {exc}") from exc
    for entry in manifest:
        try:
            sid, rel, sha1 = entry["id"], entry["image"], entry["sha1"]
            image = load_image((pack / rel).read_bytes())
        except (KeyError, TypeError, OSError, ValueError) as exc:
            raise PackError(f"팩 이미지를 읽을 수 없음: {entry!r}: {exc}") from exc
        if hashlib.sha1(np.ascontiguousarray(image)).hexdigest() != sha1:
            raise PackError(
                f"이미지 {sid}의 sha1이 manifest와 다름(디코딩 결과가 팩 제작 쪽과 다름): {rel}"
            )
        yield Sample(str(sid), image, _load_ignore(pack, sha1, image.shape[:2]))
