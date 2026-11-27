import csv
import hashlib
import io
import json
import math
import socket
import threading
import time

import numpy as np
import pytest
import uvicorn
from PIL import Image

from app.core.config import Settings, StorageSettings
from app.main import create_app
from app.models.base import BBox, OpeningDetection
from app.models.fake import FakeWallSegmenter
from app.models.registry import Models, build_models
from app.schemas.plan import (
    Opening,
    OpeningType,
    Plan,
    PlanSource,
    Point2D,
    Scale,
    ScaleSource,
    Wall,
)
from eval import measure_latency, metrics, run, stages
from eval.pack import PackError

W, H, T = 120, 90, 4


def _frame(gaps=()):
    """Closed 4 px frame; `gaps` = (class, y0, y1, x0, x1) regions relabelled as door/window."""
    labels = np.zeros((H, W), np.uint8)
    labels[10:80, 10:110] = 1
    labels[10 + T:80 - T, 10 + T:110 - T] = 0
    for cls, y0, y1, x0, x1 in gaps:
        labels[y0:y1, x0:x1] = cls
    return labels


DOOR_GAP = (2, 10, 10 + T, 40, 60)  # top wall, x 40..60
WINDOW_GAP = (3, 30, 50, 10, 10 + T)  # left wall, y 30..50
DOOR_BOX = {"type": "door", "bbox": [40, 8, 60, 16], "conf": 1.0}
WINDOW_BOX = {"type": "window", "bbox": [8, 30, 16, 50], "conf": 1.0}


def _window_moved(dy):
    g = (3, 30 + dy, 50 + dy, 10, 10 + T)
    return g, {"type": "window", "bbox": [8, 30 + dy, 16, 50 + dy], "conf": 1.0}


def make_pack(root, variants, n=2):
    """variants: name -> (labels, boxes). Images differ by one noise pixel so sha1s differ."""
    (root / "images").mkdir(parents=True)
    manifest = []
    for i in range(n):
        arr = np.full((H, W, 3), 255, np.uint8)
        arr[0, 0] = (i, 0, 0)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        (root / "images" / f"{i}.png").write_bytes(buf.getvalue())
        sha1 = hashlib.sha1(arr.tobytes()).hexdigest()
        manifest.append(dict(id=f"img{i}", image=f"images/{i}.png", sha1=sha1,
                             width=W, height=H, split="tune"))
        for variant, (labels, boxes) in variants.items():
            for folder in ("labels", "openings"):
                (root / folder / variant).mkdir(parents=True, exist_ok=True)
            Image.fromarray(labels).save(root / "labels" / variant / f"{sha1}.png")
            (root / "openings" / variant / f"{sha1}.json").write_text(json.dumps(boxes))
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


GT = (_frame([DOOR_GAP, WINDOW_GAP]), [DOOR_BOX, WINDOW_BOX])


def test_identical_pack_scores_perfect(tmp_path):
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": GT})
    rows, summary = run.evaluate(pack, ["gt", "pred/seg-v1"])
    for v in ("gt", "pred/seg-v1"):
        s = summary["variants"][v]
        assert s["success_rate"] == 1.0
        assert s["wall_iou_mean"] == pytest.approx(1.0)
        assert s["openings"]["all"]["f1"] == 1.0
        assert s["length_error_mean"] == pytest.approx(0.0, abs=1e-9)
    assert summary["common_succeeded"]["images"] == 2


def test_removed_and_moved_opening_end_to_end(tmp_path):
    """pred drops the door (gap closed, box gone) and moves the window 6 px down."""
    gap, box = _window_moved(6)
    pred = (_frame([gap]), [box])
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": pred})
    _, summary = run.evaluate(pack, ["pred/seg-v1"])
    o = summary["variants"]["pred/seg-v1"]["openings"]
    assert (o["door"]["tp"], o["door"]["fp"], o["door"]["fn"]) == (0, 0, 2)
    assert (o["window"]["tp"], o["window"]["fp"], o["window"]["fn"]) == (2, 0, 0)
    assert o["all"]["precision"] == 1.0 and o["all"]["recall"] == 0.5
    s = summary["variants"]["pred/seg-v1"]
    assert s["position_error_px_median"] == pytest.approx(6)
    assert s["width_error_px_median"] == pytest.approx(0)


def _plan(openings, scale=2.0):
    """Hand-made Plan: one 100 px (200 mm) wall along the top of a 100x100 px image."""
    wall = Wall(id="w1", start=Point2D(x=0, y=190), end=Point2D(x=200 * 2, y=190),
                thickness=8, height=2400)
    return Plan(
        source=PlanSource(type="image", width_px=100, height_px=100),
        scale=Scale(source=ScaleSource.assumed_wall_thickness, estimated=True, mm_per_px=scale),
        walls=[wall], openings=openings,
    )


def _op(oid, kind, position_mm, width_mm):
    return Opening(id=oid, type=kind, wall_id="w1", position=position_mm, width=width_mm,
                   height=2100)


def _box(kind, cx, cy, w, h):
    return OpeningDetection(OpeningType(kind), BBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 1)


def test_matching_by_hand():
    # scale 2 mm/px, wall at y_px = 100 - 190/2 = 5, runs x 0..200 px
    plan = _plan([
        _op("o1", "door", 2 * 50, 2 * 20),     # centre x=50, width 20 px   -> matches gt door 1
        _op("o2", "window", 2 * 120, 2 * 16),  # centre x=120, width 16 px  -> matches gt window (moved 5)
        _op("o3", "door", 2 * 180, 2 * 20),    # no gt door nearby           -> false positive
    ])
    gt = [
        _box("door", 54, 5, 24, 6),     # 4 px off, width 24 vs 20
        _box("door", 150, 5, 20, 6),    # unmatched                   -> false negative
        _box("window", 125, 5, 16, 6),  # 5 px off, width 16 vs 16
    ]
    m = metrics.match_openings(gt, metrics.plan_openings_px(plan), t_med=4)
    assert m.tp == {"door": 1, "window": 1} and m.fp == {"door": 1, "window": 0}
    assert m.fn == {"door": 1, "window": 0}
    assert sorted(m.pos_err) == pytest.approx([4, 5])
    assert sorted(m.width_err) == pytest.approx([0, 4])
    assert metrics.prf(2, 1, 1) == {"precision": 2 / 3, "recall": 2 / 3, "f1": 2 / 3}
    # 200 px of wall minus the three opening widths (20 + 16 + 20)
    assert metrics.plan_length_px(plan) == pytest.approx(200 - 56)


def test_different_type_or_far_box_does_not_match():
    plan = _plan([_op("o1", "door", 100, 40)])
    far = metrics.match_openings([_box("door", 50 + 40, 5, 20, 6)], metrics.plan_openings_px(plan), 4)
    other = metrics.match_openings([_box("window", 50, 5, 20, 6)], metrics.plan_openings_px(plan), 4)
    assert far.tp == {"door": 0} and other.tp == {"window": 0, "door": 0}


def test_render_cuts_openings_and_skeleton_ignores_thickness():
    plan = _plan([_op("o1", "door", 2 * 50, 2 * 20)])
    mask = metrics.render_plan_walls(plan, (100, 100))
    assert not mask[3:7, 41:59].any() and mask[3:7, 20].all()
    for t in (4, 10):  # length of a 90 px long band is 90 whatever its thickness
        band = np.zeros((60, 120), bool)
        band[20:20 + t, 10:100] = True
        assert metrics.skeleton_length(band) == pytest.approx(90, abs=1)
    assert math.isclose(metrics.iou(mask, mask), 1.0)


def test_missing_pack_is_a_friendly_error(tmp_path, capsys):
    code = run.main(["--pack", str(tmp_path / "nope"), "-o", str(tmp_path / "out")])
    assert code != 0
    assert "평가 팩" in capsys.readouterr().err


def test_missing_variant_is_a_friendly_error(tmp_path, capsys):
    pack = make_pack(tmp_path / "pack", {"gt": GT})
    code = run.main(["--pack", str(pack), "--variant", "pred/none", "-o", str(tmp_path / "out")])
    assert code == 2 and "pred/none" in capsys.readouterr().err


def test_sha1_mismatch_is_a_pack_error(tmp_path):
    pack = make_pack(tmp_path / "pack", {"gt": GT}, n=1)
    manifest = json.loads((pack / "manifest.json").read_text())
    Image.fromarray(np.zeros((H, W, 3), np.uint8)).save(pack / manifest[0]["image"])
    with pytest.raises(PackError, match="sha1"):
        run.evaluate(pack, ["gt"])


def test_failed_image_is_counted_not_fatal(tmp_path):
    empty = (np.zeros((H, W), np.uint8), [])
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": empty})
    rows, summary = run.evaluate(pack, ["gt", "pred/seg-v1"])
    s = summary["variants"]["pred/seg-v1"]
    assert s["success_rate"] == 0 and s["failures"] == {"no_walls": 2}
    assert summary["common_succeeded"]["images"] == 0


def test_cli_writes_reports(tmp_path):
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": GT})
    out = tmp_path / "reports"
    assert run.main(["--pack", str(pack), "--variant", "gt", "--variant", "pred/seg-v1",
                     "-o", str(out)]) == 0
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["images"] == 2
    lines = (out / "per_image.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 1 + 4 and lines[0].startswith("variant,id,status")


def test_skeleton_closes_corners():
    # 4 px frame whose centreline is 96 x 66 px: perimeter 324
    assert metrics.skeleton_length(_frame() == 1) == pytest.approx(324, rel=0.01)


@pytest.fixture
def live_server(tmp_path):
    """Real uvicorn on a free port with the Fake models (urllib needs a socket)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    settings = Settings(storage=StorageSettings(data_dir=str(tmp_path / "jobs")))
    server = uvicorn.Server(uvicorn.Config(create_app(settings), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def test_measure_latency_against_server(live_server, tmp_path):
    images = tmp_path / "imgs"
    images.mkdir()
    Image.new("RGB", (40, 30), "white").save(images / "a.png")
    out = tmp_path / "lat.csv"
    code = measure_latency.main(
        ["--url", live_server, "--images", str(images), "-n", "3", "-o", str(out)]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 1 + 3 and all(",succeeded," in line for line in lines[1:])
    row = measure_latency.run_job(live_server, images / "a.png", timeout=30)
    assert row["status"] == "succeeded" and row["server_s"] >= 0 and row["client_s"] > 0
    pair = measure_latency.concurrency_check(live_server, [images / "a.png"], timeout=30)
    assert [r["status"] for r in pair] == ["succeeded", "succeeded"]


def test_measure_latency_without_images_is_a_friendly_error(tmp_path, capsys):
    code = measure_latency.main(["--url", "http://x", "--images", str(tmp_path / "none")])
    assert code == 2 and "이미지" in capsys.readouterr().err


def test_parse_server_log_and_percentiles():
    log = "\n".join([
        "INFO job abc started revision=0 wait=0.000100s",
        "INFO job abc completed code=none wait=0.1s decode=0.2s plan=1.5s supplement=0.0s "
        "export=0.3s total=2.1s",
        "INFO job def failed code=no_walls wait=0s decode=0.1s plan=0.4s supplement=0s "
        "export=0s total=0.5s",
    ])
    parsed = measure_latency.parse_server_log(log)
    assert parsed["abc"]["plan"] == 1.5 and parsed["abc"]["total"] == 2.1
    assert parsed["def"]["plan"] == 0.4 and set(parsed) == {"abc", "def"}
    assert measure_latency.percentiles([1, 2, 3, 4, 5]) == {"p50": 3.0, "p90": 4.6}
    assert measure_latency.percentiles([]) == {"p50": None, "p90": None}


def test_stage_wrapper_splits_predict_from_recognition():
    class SlowSegmenter(FakeWallSegmenter):
        def segment(self, image):
            time.sleep(0.5)
            return super().segment(image)

    fakes = build_models(Settings().models)
    models = Models(SlowSegmenter(), fakes.opening_detector, fakes.dimension_reader)
    predict, recognition = stages.time_image(models, np.zeros((60, 80, 3), np.uint8))
    assert predict == pytest.approx(0.5, abs=0.1)
    assert recognition < 0.4  # the sleep is not counted twice


def test_skeleton_mixed_thickness():
    m = np.zeros((200, 300), bool)
    for y in (20, 60, 100):
        m[y:y + 4, 10:290] = True  # three 4 px walls, 280 long
    m[150:160, 10:110] = True  # one 10 px wall, 100 long: thicker than 1.5 x the median
    assert metrics.skeleton_length(m) == pytest.approx(940, abs=2)


def test_repeated_variant_is_counted_once(tmp_path):
    pack = make_pack(tmp_path / "pack", {"gt": GT})
    _, summary = run.evaluate(pack, ["gt", "gt"])
    assert summary["variants"]["gt"]["images"] == 2


def _stub_jobs(monkeypatch):
    """Fixed job ids, so a server log can name them without a real server."""
    counter = iter(range(100))
    monkeypatch.setattr(
        measure_latency, "run_job",
        lambda base, path, timeout: {
            "image": path.name, "job_id": f"job{next(counter)}", "status": "succeeded",
            "error_code": "", "client_s": 2.0, "server_s": 1.9,
        },
    )


def _latency_args(tmp_path, out):
    images = tmp_path / "imgs"
    images.mkdir(exist_ok=True)
    Image.new("RGB", (40, 30), "white").save(images / "a.png")
    return ["--url", "http://x", "--images", str(images), "-n", "2", "-o", str(out)]


def test_server_log_is_merged_by_job_id(tmp_path, monkeypatch):
    _stub_jobs(monkeypatch)
    log = tmp_path / "server.log"
    log.write_text("\n".join(
        f"INFO job job{i} completed code=none wait=0.1s decode=0.2s plan=1.5s "
        "supplement=0.0s export=0.3s total=2.1s" for i in range(2)
    ), encoding="utf-8")
    out = tmp_path / "lat.csv"
    assert measure_latency.main([*_latency_args(tmp_path, out), "--server-log", str(log)]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert [r["log_plan_s"] for r in rows] == ["1.5", "1.5"]
    assert [r["log_total_s"] for r in rows] == ["2.1", "2.1"]


def test_server_log_without_matching_jobs_warns(tmp_path, monkeypatch, capsys):
    _stub_jobs(monkeypatch)
    log = tmp_path / "server.log"
    log.write_text("", encoding="utf-8")
    out = tmp_path / "lat.csv"
    assert measure_latency.main([*_latency_args(tmp_path, out), "--server-log", str(log)]) == 0
    assert "서버 로그에 없는 작업 2/2" in capsys.readouterr().err


def test_unreadable_server_log_keeps_the_csv(tmp_path, monkeypatch, capsys):
    _stub_jobs(monkeypatch)
    out = tmp_path / "lat.csv"
    args = [*_latency_args(tmp_path, out), "--server-log", str(tmp_path / "missing.log")]
    assert measure_latency.main(args) == 0
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 3 and "log_plan_s" not in lines[0]
    assert "경고" in capsys.readouterr().err


def test_failed_image_counts_its_openings_as_missed(tmp_path):
    ok = GT
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": ok}, n=2)
    # second image: empty prediction -> recognition fails
    sha = json.loads((pack / "manifest.json").read_text())[1]["sha1"]
    Image.fromarray(np.zeros((H, W), np.uint8)).save(pack / "labels/pred/seg-v1" / f"{sha}.png")
    _, summary = run.evaluate(pack, ["pred/seg-v1"])
    s = summary["variants"]["pred/seg-v1"]
    assert s["success_rate"] == 0.5
    assert (s["openings"]["all"]["tp"], s["openings"]["all"]["fn"]) == (2, 2)
    assert s["openings"]["all"]["recall"] == 0.5
    assert s["openings"]["all"]["f1"] == pytest.approx(2 / 3)
    assert s["openings_succeeded_only"]["all"]["f1"] == 1.0


def test_ignore_mask_is_excluded_from_iou(tmp_path):
    gt_labels = _frame([DOOR_GAP, WINDOW_GAP])
    pred_labels = gt_labels.copy()
    pred_labels[50:60, 10:110] = 1  # a wall the ground truth knows nothing about
    pack = make_pack(tmp_path / "pack", {"gt": GT, "pred/seg-v1": (pred_labels, GT[1])}, n=1)
    sha = json.loads((pack / "manifest.json").read_text())[0]["sha1"]
    before = run.evaluate(pack, ["pred/seg-v1"])[1]["variants"]["pred/seg-v1"]["wall_iou_mean"]
    ignore = np.zeros((H, W), np.uint8)
    ignore[48:62, :] = 255
    (pack / "ignore" / "gt").mkdir(parents=True)
    Image.fromarray(ignore).save(pack / "ignore" / "gt" / f"{sha}.png")
    after = run.evaluate(pack, ["pred/seg-v1"])[1]["variants"]["pred/seg-v1"]["wall_iou_mean"]
    assert before < 0.99 and after > before
    assert metrics.iou(np.ones((4, 4), bool), np.zeros((4, 4), bool), np.ones((4, 4), bool)) == 1.0
