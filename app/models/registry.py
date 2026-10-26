"""Builds model implementations from settings (models.* in config/settings.yaml)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import ModelSettings
from app.models.base import DimensionReader, OpeningDetector, WallSegmenter
from app.models.cubicasa import CubiCasaOpeningDetector, CubiCasaWallSegmenter
from app.models.fake import (
    FakeDimensionReader,
    FakeOpeningDetector,
    FakeWallSegmenter,
    NullDimensionReader,
)

WALL_SEGMENTERS: dict[str, Callable[[ModelSettings], WallSegmenter]] = {
    "fake": lambda s: FakeWallSegmenter(),
    "cubicasa": lambda s: CubiCasaWallSegmenter(s.cubicasa.weights_path),
}
OPENING_DETECTORS: dict[str, Callable[[ModelSettings], OpeningDetector]] = {
    "fake": lambda s: FakeOpeningDetector(),
    "cubicasa": lambda s: CubiCasaOpeningDetector(s.cubicasa.weights_path),
}
DIMENSION_READERS: dict[str, Callable[[ModelSettings], DimensionReader]] = {
    "fake": lambda s: FakeDimensionReader(),
    "none": lambda s: NullDimensionReader(),
}


@dataclass(frozen=True)
class Models:
    wall_segmenter: WallSegmenter
    opening_detector: OpeningDetector
    dimension_reader: DimensionReader


def _pick(table: dict, name: str, role: str, settings: ModelSettings):
    try:
        factory = table[name]
    except KeyError:
        raise ValueError(f"unknown {role} {name!r}; choose one of {sorted(table)}") from None
    return factory(settings)


def build_models(settings: ModelSettings) -> Models:
    return Models(
        wall_segmenter=_pick(WALL_SEGMENTERS, settings.wall_segmenter, "wall_segmenter", settings),
        opening_detector=_pick(
            OPENING_DETECTORS, settings.opening_detector, "opening_detector", settings
        ),
        dimension_reader=_pick(
            DIMENSION_READERS, settings.dimension_reader, "dimension_reader", settings
        ),
    )
