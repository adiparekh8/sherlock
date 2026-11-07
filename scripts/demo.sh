#!/usr/bin/env bash
# One-command demo: database (docker Postgres if available, else SQLite), seed, API, UI.
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

echo "== seeding $DATASET into $DATABASE_URL"
"$PY" scripts/seed.py --dataset "$DATASET"

echo "== starting API on http://127.0.0.1:8000"
.venv/bin/uvicorn sherlock.api.app:app --host 127.0.0.1 --port 8000 --log-level warning &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 0.5
done

echo "== starting UI on http://localhost:8501"
export SHERLOCK_API_URL="http://127.0.0.1:8000"
.venv/bin/streamlit run ui/app.py --server.port 8501 --server.headless true
