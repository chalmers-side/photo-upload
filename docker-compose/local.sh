#!/usr/bin/env bash
# Event-day private server on this Mac: http://localhost:${LOCAL_PORT:-8000}
# Files stay on the internal disk at /opt/app/photo-upload (no OWC SSD).
#   ./local.sh doctor            Docker, File Sharing, disk, /health
#   ./local.sh up                build from source + start (restart: unless-stopped)
#   ./local.sh backup            pg_dump into /opt/app/photo-upload/backups
#   ./local.sh logs [service]    follow logs
#   ./local.sh restart [service] e.g. nginx after a 502
#   ./local.sh ps | down
set -euo pipefail
cd "$(dirname "$0")"

port="${LOCAL_PORT:-8000}"
data="${HOST_PHOTO_DIR:-/opt/app/photo-upload}"
export HOST_PHOTO_DIR="$data"
compose() { docker compose -f docker-compose.local.yaml "$@"; }

urls() {
  local ip
  ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  echo "Local:  http://localhost:${port}/"
  [ -n "$ip" ] && echo "Phone:  http://${ip}:${port}/   (same Wi-Fi)"
  echo "Admin:  http://localhost:${port}/admin"
  echo "Data:   ${data}"
}

ensure_data() {
  if [[ ! -d "$data" ]]; then
    mkdir -p "$data" 2>/dev/null || {
      sudo mkdir -p "$data"
      sudo chown "$(id -un):$(id -gn)" "$data"
    }
  fi
  mkdir -p "$data/logs" "$data/postgres" "$data/models" "$data/backups"
}

ensure_secret() {
  if [[ -f secret.env ]]; then
    return
  fi
  python3 - <<'PY'
import secrets
from pathlib import Path
Path("secret.env").write_text(
    "ADMIN_USERNAME=root\n"
    f"ADMIN_PASSWORD={secrets.token_urlsafe(8)}\n"
    f"SECRET_KEY={secrets.token_hex(32)}\n"
)
PY
  echo "wrote docker-compose/secret.env (gitignored). Read ADMIN_PASSWORD from that file."
}

docker_ok() {
  docker info >/dev/null 2>&1
}

wait_docker() {
  local i
  for i in $(seq 1 60); do
    docker_ok && return 0
    sleep 2
  done
  echo "Docker Desktop did not become ready. Whale menu → Restart." >&2
  return 1
}

# Docker Desktop does not share /opt/app by default ("Mounts denied").
ensure_file_sharing() {
  local settings="$HOME/Library/Group Containers/group.com.docker/settings-store.json"
  python3 - "$settings" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
need = "/opt/app"
defaults = ["/Users", "/Volumes", "/private", "/tmp", "/var/folders"]
if not path.exists():
    print("missing")
    raise SystemExit(2)
data = json.loads(path.read_text())
dirs = list(data.get("filesharingDirectories") or defaults)
covered = any(
    need == d.rstrip("/") or need.startswith(d.rstrip("/") + "/")
    for d in dirs
)
if covered:
    print("ok")
    raise SystemExit(0)
dirs.append(need)
data["filesharingDirectories"] = dirs
path.write_text(json.dumps(data, indent=2) + "\n")
print("added")
PY
}

mount_ok() {
  docker run --rm -v "${data}:/mnt/data:ro" alpine:3.20 ls /mnt/data >/dev/null
}

ensure_mount() {
  ensure_data
  if ! docker_ok; then
    echo "Docker Desktop is not running. Open Docker, then retry." >&2
    return 1
  fi
  if mount_ok 2>/dev/null; then
    return 0
  fi
  local result
  result="$(ensure_file_sharing)" || true
  if [[ "$result" == "missing" ]]; then
    echo "Could not find Docker settings-store.json." >&2
    echo "Docker Desktop → Settings → Resources → File sharing → add /opt/app → Apply & Restart." >&2
    return 1
  fi
  echo "Docker Desktop did not share ${data}. Updating File Sharing and restarting Docker Desktop..."
  docker desktop restart
  wait_docker
  if mount_ok; then
    echo "File Sharing ok: ${data}"
    return 0
  fi
  echo "Still Mounts denied for ${data} after restart." >&2
  echo "Docker Desktop → Settings → Resources → File sharing → add /opt/app → Apply & Restart." >&2
  return 1
}

wait_health() {
  local i
  for i in $(seq 1 45); do
    curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

doctor() {
  echo "== Docker"
  if docker_ok; then
    echo "ok"
  else
    echo "not ready (paused or stopped). Whale menu → Resume / Restart." >&2
    return 1
  fi
  echo "== Data dir ${data}"
  ensure_data
  df -h "$data" | tail -1
  local avail_kb
  avail_kb="$(df -k "$data" | awk 'NR==2 {print $4}')"
  if [[ "${avail_kb:-0}" -lt 2097152 ]]; then
    echo "warn: less than 2GiB free on the data disk" >&2
  fi
  echo "== File Sharing"
  ensure_mount
  echo "== Port ${port}"
  if curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1; then
    echo "health ok"
  else
    echo "no /health yet (stack not up, or nginx 502)"
  fi
  echo "== Compose"
  compose ps
  echo "== Sleep"
  echo "Keep this Mac plugged in. System Settings → Energy → prevent sleep on power."
  echo "If the whale icon says paused: Resume from the menu, then ./local.sh up"
  echo "If guests see 502 after an app recreate: ./local.sh restart nginx"
  echo "Redis is cache; detector/judge re-queue pending photos after a Redis bounce."
}

cmd="${1:-up}"
shift || true
case "$cmd" in
  up)
    ensure_secret
    ensure_mount
    compose up -d --build
    if wait_health; then
      urls
    else
      echo "health check failed" >&2
      compose logs --tail 80
      echo "If nginx 502: ./local.sh restart nginx" >&2
      exit 1
    fi
    ;;
  doctor) doctor ;;
  backup)
    ensure_data
    stamp="$(date +%Y%m%d-%H%M%S)"
    out="${data}/backups/photo-${stamp}.sql"
    compose exec -T postgres pg_dump -U photo photo >"$out"
    echo "wrote ${out}"
    echo "JPEGs stay in ${data}/<project-id>/"
    ;;
  logs) compose logs -f "$@" ;;
  restart) compose restart "$@" ;;
  ps) compose ps ;;
  down) compose down ;;
  *)
    sed -n '2,10p' "$0"
    exit 1
    ;;
esac
