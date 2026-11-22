"""Split recognition time into model predict and post-processing (EVALUATION_PLAN §4 table 3).

    python -m eval.stages --images <folder> -n 20 [--config config/settings.yaml]

The server log only has one `plan` stage, so this runs `image_to_plan` itself with the models
from the settings and times the model calls with a wrapper: predict = time inside
segment/detect/read, recognition = the rest. Run it on the machine the numbers are for (OCI VM),
not on a laptop, with `models.*` set to the real bundle. The wrapper is the whole trick: the app
is untouched. Needs the `eval/` folder and the images on that machine (the Docker image copies
only app/ and config/).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from app.core.config import load_settings
from app.models.registry import Models, build_models
from app.preprocess.image import load_image
from app.recognition.pipeline import image_to_plan
from eval.measure_latency import _IMAGE_SUFFIXES, percentiles

_MODEL_CALLS = {"segment", "detect", "read"}


class Timed:
    """Delegates to a model and adds the seconds spent in its predict methods to `acc[0]`."""

    def __init__(self, inner, acc: list[float]) -> None:
        self._inner, self._acc = inner, acc

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in _MODEL_CALLS:
            return attr

        def timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return attr(*args, **kwargs)
            finally:
                self._acc[0] += time.perf_counter() - start

        return timed


def time_image(models: Models, image) -> tuple[float, float]:
    """(predict_s, recognition_s) for one image."""
    acc = [0.0]
    wrapped = Models(
        Timed(models.wall_segmenter, acc), Timed(models.opening_detector, acc),
        Timed(models.dimension_reader, acc),
    )
    start = time.perf_counter()
    image_to_plan(image, wrapped)
    total = time.perf_counter() - start
    return acc[0], total - acc[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.stages", description=__doc__.split("\n\n")[0])
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--config", type=Path, help="settings.yaml (기본: AUTOBIM_CONFIG 또는 기본 설정)")
    ap.add_argument("-o", "--out", type=Path, default=Path("stages.csv"))
    args = ap.parse_args(argv)
    images = sorted(p for p in args.images.glob("*") if p.suffix.lower() in _IMAGE_SUFFIXES) \
        if args.images.is_dir() else []
    if not images:
        print(f"오류: 이미지 폴더가 없거나 비었음: {args.images}", file=sys.stderr)
        return 2
    models = build_models(load_settings(args.config).models)
    rows = []
    for i in range(args.n):
        path = images[i % len(images)]
        predict, recognise = time_image(models, load_image(path.read_bytes()))
        rows.append({"image": path.name, "predict_s": predict, "recognition_s": recognise})
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["image", "predict_s", "recognition_s"])
        w.writeheader()
        w.writerows(rows)
    print("predict", percentiles([r["predict_s"] for r in rows]))
    print("recognition", percentiles([r["recognition_s"] for r in rows]))
    print(f"CSV: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
