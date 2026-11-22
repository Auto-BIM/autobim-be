"""Open an evaluation pack (docs/next-tasks.md, #11 (BE-N2)) for evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.models.replay import ReplayModel
from app.preprocess.image import load_image


class PackError(Exception):
    """The pack is missing or malformed: a user error, not a failed image."""


@dataclass
class Sample:
    id: str
    image: np.ndarray


def open_variant(pack: Path, variant: str) -> ReplayModel:
    try:
        return ReplayModel(pack, variant)
    except ValueError as exc:
        raise PackError(f"평가 팩을 열 수 없음 ({variant}): {exc}") from exc


def load_samples(pack: Path) -> list[Sample]:
    """Images in manifest order; each must hash to the manifest's sha1 like replay expects."""
    try:
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackError(f"manifest.json을 읽을 수 없음: {pack}: {exc}") from exc
    samples = []
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
        samples.append(Sample(str(sid), image))
    return samples
