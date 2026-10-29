#!/usr/bin/env bash
# Usage: deploy/smoke.sh <base_url> [image]
#   deploy/smoke.sh http://localhost plan.png
# Upload -> poll -> download glb/dxf/json -> size check. Without an image a blank PNG is
# generated (the Fake models ignore the content). Needs curl and python3.
set -euo pipefail
BASE=${1:?usage: smoke.sh <base_url> [image]}
BASE=${BASE%/}
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
IMG=${2:-}
if [ -z "$IMG" ]; then
  IMG=$OUT/blank.png
  python3 - "$IMG" <<'PY'
import struct, sys, zlib
w = h = 64
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
raw = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
open(sys.argv[1], "wb").write(png)
PY
fi
json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

curl -fsS "$BASE/health"; echo
JOB=$(curl -fsS -F "file=@${IMG}" "$BASE/api/jobs" | json '["id"]')
echo "job $JOB"
STATUS=queued
for i in $(seq 1 180); do
  STATUS=$(curl -fsS "$BASE/api/jobs/$JOB" | json '["status"]')
  [ "$STATUS" = succeeded ] && break
  if [ "$STATUS" = failed ]; then curl -fsS "$BASE/api/jobs/$JOB"; echo; exit 1; fi
  sleep 1
done
[ "$STATUS" = succeeded ] || { echo "timeout after ${i}s ($STATUS)" >&2; exit 1; }

for k in glb dxf json; do
  f=$OUT/smoke.$k
  curl -fsS -o "$f" "$BASE/api/jobs/$JOB/files/$k"
  [ -s "$f" ] || { echo "$k is empty" >&2; exit 1; }
  echo "$k $(wc -c < "$f" | tr -d ' ') bytes"
done
[ "$(head -c 4 "$OUT/smoke.glb")" = glTF ] || { echo "glb has no glTF header" >&2; exit 1; }
echo "OK $JOB (${i}s)"
