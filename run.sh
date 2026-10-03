#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./scripts/install-utils.sh
install_init "$PWD" "AgentGymnasium"
install_enable_traps

action="run"
no_browser=0
for arg in "$@"; do
  case "$arg" in
    run|doctor|repair|docker|stop|logs) action="$arg" ;;
    --no-browser) no_browser=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

uv_version="0.12.5"
url="http://127.0.0.1:8765"

find_uv() {
  command -v uv 2>/dev/null || {
    [ -x "$HOME/.local/bin/uv" ] && printf '%s\n' "$HOME/.local/bin/uv" && return 0
    [ -x "$HOME/.cargo/bin/uv" ] && printf '%s\n' "$HOME/.cargo/bin/uv" && return 0
    return 1
  }
}

install_uv() {
  local installer
  installer="$(mktemp)"
  install_download "https://astral.sh/uv/${uv_version}/install.sh" "$installer" "uv download"
  sh "$installer"
  rm -f "$installer"
  find_uv
}

wait_ready() {
  local health=$1
  for _ in $(seq 1 60); do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "$health" >/dev/null 2>&1; then return 0; fi
    if command -v wget >/dev/null 2>&1 && wget -q --timeout=2 -O /dev/null "$health" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  return 1
}

open_url() {
  [ "$no_browser" -eq 1 ] && return 0
  command -v open >/dev/null 2>&1 && { open "$1" >/dev/null 2>&1 || true; return; }
  command -v xdg-open >/dev/null 2>&1 && { xdg-open "$1" >/dev/null 2>&1 || true; return; }
  command -v gio >/dev/null 2>&1 && gio open "$1" >/dev/null 2>&1 || true
}

case "$action" in
  docker|stop|logs)
    if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
      [ "$action" = stop ] && { echo "The native server runs in the foreground. Press Ctrl+C in its terminal to stop it."; exit 0; }
      [ "$action" = logs ] && { echo "The native server writes logs to its foreground terminal."; exit 0; }
      command -v docker >/dev/null 2>&1 || { echo "Docker is not installed." >&2; exit 1; }
      echo "Docker is installed but its engine is not running." >&2
      exit 1
    fi
    [ "$action" = stop ] && exec docker compose down
    [ "$action" = logs ] && exec docker compose logs --follow
    install_lock
    install_require_space "$PWD" 2
    docker compose up --detach --build
    wait_ready "$url/api/health" || { docker compose logs; echo "AgentGymnasium did not become healthy." >&2; exit 1; }
    install_complete
    echo "AgentGymnasium is ready at $url"
    open_url "$url"
    exit 0 ;;
esac

uv="$(find_uv || true)"
if [ "$action" = doctor ]; then
  [ -n "$uv" ] || { echo "uv is missing. Run ./run.sh once." >&2; exit 1; }
  "$uv" run --frozen --no-sync agentgymnasium --help >/dev/null
  [ -f backend/agentgymnasium/static/index.html ] || { echo "The prebuilt UI is missing." >&2; exit 1; }
  echo "AgentGymnasium native environment is ready."
  exit 0
fi
install_lock
install_require_space "$PWD" 2
[ -n "$uv" ] || uv="$(install_uv)"

sync_args=(sync --frozen --no-dev)
[ "$action" = repair ] && sync_args+=(--reinstall)
install_retry "dependency synchronization" "$uv" "${sync_args[@]}"

if [ ! -f backend/agentgymnasium/static/index.html ]; then
  command -v npm >/dev/null 2>&1 || { echo "The prebuilt UI is missing and Node/npm is unavailable." >&2; exit 1; }
  (cd frontend && install_retry "frontend dependency installation" npm ci && npm run build)
fi

install_complete
serve_args=(run --frozen --no-sync agentgymnasium serve --no-reload)
[ "$no_browser" -eq 0 ] && serve_args+=(--open)
exec "$uv" "${serve_args[@]}"
