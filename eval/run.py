"""Plan-level evaluation: python -m eval.run --pack <dir> --variant gt --variant pred/seg-v1 -o reports/

Each variant is recognised through the replay adapter and compared with the same ground truth
(`labels/gt`, `openings/gt`). gt -> Plan is the post-processing limit; pred -> Plan is the whole
system; the difference is the model's contribution (EVALUATION_PLAN §3).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from app.core.config import RecognitionSettings, load_settings
from app.models.fake import NullDimensionReader
from app.models.registry import Models
from app.recognition.pipeline import RecognitionError, image_to_plan
from app.recognition.walls import estimate_thickness
from app.schemas.plan import ReviewReason
from eval import metrics
from eval.pack import PackError, iter_samples, open_variant

TYPES = ("door", "window")
CSV_FIELDS = [
    "variant", "id", "status", "error_code", "wall_iou", "length_plan_px", "length_gt_px",
    "length_error", "detections", "plan_openings",
    *(f"{t}_{k}" for t in TYPES for k in ("tp", "fp", "fn")),
    "pos_err_px_mean", "width_err_px_mean", "review_items",
    *(f"review_{r.value}" for r in ReviewReason),
]


def _mean(values):
    return statistics.fmean(values) if values else None


def _pack_call(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:  # replay validates label/opening files lazily
        raise PackError(f"평가 팩 파일 오류: {exc}") from exc


def _row(variant, sample, model, gt_mask, gt_boxes, rec: RecognitionSettings) -> dict:
    row = {"variant": variant, "id": sample.id, "_pos": [], "_wid": [], "_types": {}}
    _pack_call(model.segment, sample.image)  # a broken pack file is a pack error, not a failed image
    row["detections"] = len(_pack_call(model.detect, sample.image))
    models = Models(model, model, NullDimensionReader())
    # A failed image still has ground-truth openings: they all count as missed (FN).
    missed = {t: (0, 0, sum(b.type.value == t for b in gt_boxes)) for t in TYPES}
    failed = {**row, "status": "failed", "_types": missed}
    for t in TYPES:
        failed[f"{t}_tp"], failed[f"{t}_fp"], failed[f"{t}_fn"] = missed[t]
    try:
        plan = image_to_plan(sample.image, models, filename=sample.id, settings=rec)
    except RecognitionError as exc:
        return {**failed, "error_code": exc.code}
    except Exception as exc:  # noqa: BLE001 — same split as app/jobs/runner.py
        return {**failed, "error_code": f"internal_error:{type(exc).__name__}"}
    l_plan, l_gt, l_err = metrics.length_error(plan, gt_mask)
    m = metrics.match_openings(gt_boxes, metrics.plan_openings_px(plan), estimate_thickness(gt_mask))
    reasons = Counter(r.reason.value for r in plan.review_items)
    row.update(
        status="succeeded", error_code="",
        wall_iou=metrics.iou(
            metrics.render_plan_walls(plan, gt_mask.shape), gt_mask, sample.ignore
        ),
        length_plan_px=l_plan, length_gt_px=l_gt, length_error=l_err,
        plan_openings=len(plan.openings), review_items=len(plan.review_items),
        pos_err_px_mean=_mean(m.pos_err), width_err_px_mean=_mean(m.width_err),
        _pos=m.pos_err, _wid=m.width_err,
        _types={t: (m.tp.get(t, 0), m.fp.get(t, 0), m.fn.get(t, 0)) for t in TYPES},
    )
    for t in TYPES:
        for k, v in zip(("tp", "fp", "fn"), row["_types"][t]):
            row[f"{t}_{k}"] = v
    for r in ReviewReason:
        row[f"review_{r.value}"] = reasons[r.value]
    return row


def _aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "succeeded"]
    def totals(rs):
        sums = {t: [sum(r["_types"][t][i] for r in rs) for i in range(3)] for t in TYPES}
        sums["all"] = [sum(sums[t][i] for t in TYPES) for i in range(3)]
        return {t: {"tp": s[0], "fp": s[1], "fn": s[2], **metrics.prf(*s)} for t, s in sums.items()}

    pos = [e for r in ok for e in r["_pos"]]
    wid = [e for r in ok for e in r["_wid"]]
    errs = [r["length_error"] for r in ok if r["length_error"] is not None]
    return {
        "images": len(rows),
        "succeeded": len(ok),
        "success_rate": len(ok) / len(rows) if rows else None,
        "failures": dict(Counter(r["error_code"] for r in rows if r["status"] == "failed")),
        "wall_iou_mean": _mean([r["wall_iou"] for r in ok]),
        "length_error_mean": _mean(errs),
        # default: failed images count their gt openings as FN; the second keeps only succeeded ones
        "openings": totals(rows),
        "openings_succeeded_only": totals(ok),
        "matched_pairs": len(pos),
        "position_error_px_median": statistics.median(pos) if pos else None,
        "width_error_px_median": statistics.median(wid) if wid else None,
        "review_items_per_image": _mean([r["review_items"] for r in ok]),
        "review_by_reason_per_image": {
            r.value: _mean([row[f"review_{r.value}"] for row in ok]) for r in ReviewReason
        },
    }


def evaluate(
    pack: Path, variants: list[str], rec: RecognitionSettings | None = None
) -> tuple[list[dict], dict]:
    rec = rec or RecognitionSettings()
    variants = list(dict.fromkeys(variants))  # a repeated variant would be counted twice
    gt_model = open_variant(pack, "gt")  # ground truth always comes from the gt variant
    models = {v: gt_model if v == "gt" else open_variant(pack, v) for v in variants}
    rows, images = [], 0
    for s in iter_samples(pack):  # one image in memory at a time (17 MP images add up)
        images += 1
        truth = (_pack_call(gt_model.segment, s.image).mask, _pack_call(gt_model.detect, s.image))
        rows += [_row(v, s, models[v], *truth, rec) for v in variants]
    by_variant = {v: [r for r in rows if r["variant"] == v] for v in variants}
    summary = {
        "pack": str(pack),
        "images": images,
        "units": "px",
        "notes": [
            "wall IoU excludes ignore/gt (255) pixels when the pack has them; length and openings do not",
            "opening ground truth = openings/gt boxes (same function as serving), not gt/<id>.json",
        ],
        "variants": {v: _aggregate(rs) for v, rs in by_variant.items()},
    }
    if len(variants) > 1:  # compare on the images every variant recognised
        common = set.intersection(
            *({r["id"] for r in rs if r["status"] == "succeeded"} for rs in by_variant.values())
        )
        summary["common_succeeded"] = {
            "images": len(common),
            "variants": {
                v: _aggregate([r for r in rs if r["id"] in common]) for v, rs in by_variant.items()
            },
        }
    return rows, summary


def write_reports(out: Path, rows: list[dict], summary: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / "per_image.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.run", description="Plan 단위 시스템 평가")
    ap.add_argument("--pack", required=True, type=Path, help="평가 팩 폴더")
    ap.add_argument("--variant", action="append", help="gt 또는 pred/<번들> (반복 지정, 기본 gt)")
    ap.add_argument("--config", type=Path, help="settings.yaml의 recognition 설정을 쓴다(기본: 서버와 같은 기본 경로)")
    ap.add_argument("-o", "--out", required=True, type=Path, help="결과 폴더")
    args = ap.parse_args(argv)
    try:
        rows, summary = evaluate(
            args.pack, args.variant or ["gt"], load_settings(args.config).recognition
        )
    except PackError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    write_reports(args.out, rows, summary)
    for v, s in summary["variants"].items():
        print(f"{v}: 성공 {s['succeeded']}/{s['images']}, 렌더 벽 IoU {s['wall_iou_mean']}")
    print(f"결과: {args.out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
