#!/usr/bin/env bash
# Usage: deploy/deploy.sh [branch or tag, default develop]
# git update -> build -> restart -> health. Reads deploy/.env.
set -euo pipefail

# Everything runs inside main so bash has read the whole script before `git checkout`
# replaces this file on disk.
main() {
  cd "$(dirname "$0")/.."
  local ref=${1:-develop}
  local compose=(docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env)

  [ -f deploy/.env ] || { echo "deploy/.env missing: cp deploy/.env.example deploy/.env" >&2; exit 1; }
  set -a
  # shellcheck source=/dev/null
  . deploy/.env
  set +a

  git fetch --all --tags --prune
  if git show-ref --verify --quiet "refs/remotes/origin/$ref"; then
    git checkout "$ref" && git pull --ff-only
  else
    git checkout "tags/$ref"
  fi
  echo "deploying $(git describe --tags --always --dirty)"

  "${compose[@]}" up -d --build --remove-orphans

  # Through Caddy, the way users reach it. With a domain in SITE_ADDRESS Caddy only answers
  # that host, so ask the API container directly instead.
  local check=(curl -fsS "http://localhost:${HTTP_PORT:-80}/health")
  if [ "${SITE_ADDRESS:-:80}" != ":80" ]; then
    check=("${compose[@]}" exec -T api python -c
      "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())")
  fi
  for _ in $(seq 1 60); do
    if "${check[@]}" 2>/dev/null; then echo; exit 0; fi
    sleep 2
  done
  echo "health check failed" >&2
  "${compose[@]}" logs --tail 100 api
  exit 1
}

main "$@"
