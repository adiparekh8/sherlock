#!/usr/bin/env bash
# One-command demo: database (docker Postgres if available, else SQLite), seed, then the API which also serves the console.
set -euo pipefail
DATASET="${1:-synthetic_v1}"
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || { echo "No .venv. Run: make install"; exit 1; }
[ -f .env ] || cp .env.example .env

if [ -z "${SHERLOCK_FORCE_SQLITE:-}" ] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "== starting Postgres via docker compose"
  docker compose up -d db
  for _ in $(seq 1 30); do
    docker compose exec -T db pg_isready -U sherlock >/dev/null 2>&1 && break
    sleep 1
  done
  export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://sherlock:sherlock@localhost:5432/sherlock}"
else
  echo "== docker not available (or SHERLOCK_FORCE_SQLITE set): using SQLite at ./sherlock.db"
  export DATABASE_URL="sqlite:///./sherlock.db"
fi

for PORT in 8000; do
  if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $PORT is already in use ($(lsof -nP -iTCP:$PORT -sTCP:LISTEN | awk 'NR==2{print $1" pid "$2}'))."
    echo "Stop it (or run: kill \$(lsof -t -iTCP:$PORT)) and run make demo again."
    exit 1
  fi
done

echo "== seeding $DATASET into $DATABASE_URL"
"$PY" scripts/seed.py --dataset "$DATASET"

echo "== Sherlock is at http://localhost:8000  (API docs at /docs). Ctrl-C to stop."
exec .venv/bin/uvicorn sherlock.api.app:app --host 127.0.0.1 --port 8000 --log-level warning
