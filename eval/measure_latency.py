"""Job latency against a running server (EVALUATION_PLAN §4):

    python -m eval.measure_latency --url https://<host> --images <folder> -n 20 [--server-log docker.log]

Uploads images one at a time, polls each job to `succeeded`/`failed`, writes one CSV row per job
and prints p50/p90. `--server-log` adds the per-stage seconds from the server's
`job <id> completed ... plan=..s` log lines (#13). `--concurrency-check` also uploads two images
at once and reports whether both succeed. Standard library only, so it runs anywhere.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

STAGES = ("wait", "decode", "plan", "supplement", "export", "total")
_LOG = re.compile(r"job (\S+) (?:completed|failed) code=\S+ (.*)")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def parse_server_log(text: str) -> dict[str, dict[str, float]]:
    """job id -> {stage: seconds} from the final log line of each job."""
    out = {}
    for line in text.splitlines():
        m = _LOG.search(line)
        if m:
            out[m.group(1)] = {k: float(v) for k, v in re.findall(r"(\w+)=([\d.]+)s", m.group(2))}
    return out


def percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p90": None}
    return {"p50": float(np.percentile(values, 50)), "p90": float(np.percentile(values, 90))}


def _request(url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _upload(base: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return _request(
        f"{base}/api/jobs", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )


def run_job(base: str, path: Path, timeout: float, poll: float = 0.2) -> dict:
    """Upload, poll, and time one job. `client_s` includes up to `poll` seconds of polling lag."""
    start = time.perf_counter()
    row = {"image": path.name, "job_id": "", "status": "", "error_code": "", "client_s": None,
           "server_s": None}
    try:
        job = _upload(base, path)
        row["job_id"] = job["id"]
        while job["status"] not in ("succeeded", "failed"):
            if time.perf_counter() - start > timeout:
                row["status"], row["error_code"] = "timeout", "timeout"
                return row
            time.sleep(poll)
            job = _request(f"{base}/api/jobs/{job['id']}")
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        row["status"], row["error_code"] = "error", type(exc).__name__
        return row
    row["client_s"] = time.perf_counter() - start
    row["status"] = job["status"]
    row["error_code"] = (job.get("error") or {}).get("code", "")
    created = datetime.fromisoformat(job["created_at"])
    row["server_s"] = (datetime.fromisoformat(job["updated_at"]) - created).total_seconds()
    return row


def concurrency_check(base: str, images: list[Path], timeout: float) -> list[dict]:
    """Two uploads at once: the second should wait its turn and still succeed."""
    rows: list[dict] = [{}, {}]

    def go(i: int) -> None:
        rows[i] = run_job(base, images[i % len(images)], timeout)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.measure_latency", description=__doc__)
    ap.add_argument("--url", required=True, help="서버 기준 URL (예: https://host)")
    ap.add_argument("--images", required=True, type=Path, help="이미지 폴더 (png/jpg)")
    ap.add_argument("-n", type=int, default=20, help="올릴 작업 수 (이미지는 순환)")
    ap.add_argument("-o", "--out", type=Path, default=Path("latency.csv"))
    ap.add_argument("--server-log", type=Path, help="서버 로그 파일(job … completed … 줄)")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--concurrency-check", action="store_true", help="두 장 동시 업로드 확인")
    args = ap.parse_args(argv)
    images = sorted(p for p in args.images.glob("*") if p.suffix.lower() in _IMAGE_SUFFIXES) \
        if args.images.is_dir() else []
    if not images:
        print(f"오류: 이미지 폴더가 없거나 비었음: {args.images}", file=sys.stderr)
        return 2
    base = args.url.rstrip("/")
    rows = [run_job(base, images[i % len(images)], args.timeout) for i in range(args.n)]
    if args.server_log:
        try:
            stages = parse_server_log(args.server_log.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            print(f"오류: 서버 로그를 읽을 수 없음: {exc}", file=sys.stderr)
            return 2
        for r in rows:
            for k in STAGES:
                r[f"log_{k}_s"] = stages.get(r["job_id"], {}).get(k)
    fields = ["image", "job_id", "status", "error_code", "client_s", "server_s",
              *(f"log_{k}_s" for k in STAGES if args.server_log)]
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r["status"] == "succeeded"]
    print(f"성공 {len(ok)}/{len(rows)}  전체(클라이언트) {percentiles([r['client_s'] for r in ok])}")
    if args.server_log:
        print(f"서버 로그 plan {percentiles([r['log_plan_s'] for r in ok if r.get('log_plan_s') is not None])}")
    if args.concurrency_check:
        pair = concurrency_check(base, images, args.timeout)
        print("동시 2장:", [(r["status"], r["client_s"]) for r in pair])
    print(f"CSV: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
