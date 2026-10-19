#!/usr/bin/env bash
# Local POC stack on this Mac: http://localhost:${POC_PORT:-8001}
#   ./poc.sh up                 build + start (code in web/ and config/ is live-mounted)
#   ./poc.sh seed               create/refresh the "poc" demo project
#   ./poc.sh logs [service]     follow logs
#   ./poc.sh restart [service]  e.g. restart detector after editing web/detector.py
#                               restart judge after editing web/judge.py
#   ./poc.sh ps | down
#   ./poc.sh reset              down + delete .poc/ (photos + Postgres)
set -euo pipefail
cd "$(dirname "$0")"

port="${POC_PORT:-8001}"
data="${POC_DATA_DIR:-../.poc}"
compose() { docker compose -f docker-compose.poc.yaml "$@"; }

urls() {
  local ip
  ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  echo "Local:  http://localhost:${port}/"
  [ -n "$ip" ] && echo "Phone:  http://${ip}:${port}/   (same Wi-Fi)"
  echo "Admin:  http://localhost:${port}/admin"
}

cmd="${1:-up}"
shift || true
case "$cmd" in
  up)
    mkdir -p "$data/photos/logs" "$data/postgres" "$data/models"
    compose up -d --build
    for _ in $(seq 1 30); do
      curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1 && break
      sleep 1
    done
    curl -fsS "http://localhost:${port}/health" >/dev/null || { compose logs --tail 50; exit 1; }
    urls
    ;;
  seed)
    compose exec app python poc_seed.py
    echo "Demo:   http://localhost:${port}/p/poc/"
    ;;
  logs) compose logs -f "$@" ;;
  restart) compose restart "$@" ;;
  ps) compose ps ;;
  down) compose down ;;
  reset)
    compose down -v
    rm -rf "$data"
    ;;
  *)
    sed -n '2,8p' "$0"
    exit 1
    ;;
esac
