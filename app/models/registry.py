"""Builds model implementations from settings (models.* in config/settings.yaml)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import ModelSettings
from app.models.base import DimensionReader, OpeningDetector, WallSegmenter
from app.models.fake import (
    FakeDimensionReader,
    FakeOpeningDetector,
    FakeWallSegmenter,
    NullDimensionReader,
)

# Factories get the settings and a per-build cache (see `_shared_seg`).
Cache = dict[str, object]


def _shared_seg(s: ModelSettings, cache: Cache):
    """One `SegModel` per `build_models` call, shared by every role set to `seg`."""
    if "seg" not in cache:
        from app.models.seg import SegModel  # lazy: only `seg` needs autobim_seg

        cache["seg"] = SegModel(s.seg.bundle_dir, s.seg.threads)
    return cache["seg"]


def _shared_replay(s: ModelSettings, cache: Cache):
    """Share one evaluation-pack adapter across the two recognition roles."""
    if "replay" not in cache:
        from app.models.replay import ReplayModel

        cache["replay"] = ReplayModel(s.replay.pack_dir, s.replay.variant)
    return cache["replay"]


WALL_SEGMENTERS: dict[str, Callable[[ModelSettings, Cache], WallSegmenter]] = {
    "fake": lambda s, c: FakeWallSegmenter(),
    "seg": _shared_seg,
    "replay": _shared_replay,
}
OPENING_DETECTORS: dict[str, Callable[[ModelSettings, Cache], OpeningDetector]] = {
    "fake": lambda s, c: FakeOpeningDetector(),
    "seg": _shared_seg,
    "replay": _shared_replay,
}
DIMENSION_READERS: dict[str, Callable[[ModelSettings, Cache], DimensionReader]] = {
    "fake": lambda s, c: FakeDimensionReader(),
    "none": lambda s, c: NullDimensionReader(),
}


@dataclass(frozen=True)
class Models:
    wall_segmenter: WallSegmenter
    opening_detector: OpeningDetector
    dimension_reader: DimensionReader


def _pick(table: dict, name: str, role: str, settings: ModelSettings, cache: Cache):
    try:
        factory = table[name]
    except KeyError:
        raise ValueError(f"unknown {role} {name!r}; choose one of {sorted(table)}") from None
    return factory(settings, cache)


def build_models(settings: ModelSettings) -> Models:
    if "replay" in (settings.wall_segmenter, settings.opening_detector):
        if settings.dimension_reader == "fake":
            raise ValueError("replay cannot use dimension_reader='fake'; set dimension_reader='none'")
    cache: Cache = {}
    return Models(
        wall_segmenter=_pick(
            WALL_SEGMENTERS, settings.wall_segmenter, "wall_segmenter", settings, cache
        ),
        opening_detector=_pick(
            OPENING_DETECTORS, settings.opening_detector, "opening_detector", settings, cache
        ),
        dimension_reader=_pick(
            DIMENSION_READERS, settings.dimension_reader, "dimension_reader", settings, cache
        ),
    )
