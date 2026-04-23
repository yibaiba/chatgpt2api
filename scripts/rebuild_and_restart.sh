#!/usr/bin/env bash
set -euo pipefail

# Rebuild frontend, replace web_dist, restart backend (uvicorn).
# Usage: ./scripts/rebuild_and_restart.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p logs

echo "[rebuild] Building frontend..."
cd "$ROOT_DIR/web"
if [ -f package-lock.json ] || [ -f pnpm-lock.yaml ]; then
  npm ci
else
  npm install
fi

export NEXT_PUBLIC_APP_VERSION="$(cat "$ROOT_DIR/VERSION" 2>/dev/null || echo "dev")"
npm run build

echo "[rebuild] Replacing web_dist..."
rm -rf "$ROOT_DIR/web_dist"
if [ -d out ]; then
  cp -R out "$ROOT_DIR/web_dist"
elif [ -d .next ]; then
  cp -R .next "$ROOT_DIR/web_dist"
else
  echo "[rebuild] Warning: no build output directory found (out or .next)." >&2
fi

cd "$ROOT_DIR"

echo "[rebuild] Installing backend deps (if .venv exists)..."
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  "$ROOT_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$ROOT_DIR/.venv/bin/python" -m pip install -e '.[dev]' 2>/dev/null || "$ROOT_DIR/.venv/bin/python" -m pip install curl-cffi fastapi pybase64 uvicorn pillow python-multipart
fi

echo "[rebuild] Restarting backend..."
if command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -ti tcp:8000 || true)"
else
  pids="$(lsof -ti :8000 || true)"
fi
if [ -n "$pids" ]; then
  echo "[rebuild] Killing pids: $pids"
  kill -9 $pids || true
fi

mkdir -p logs

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  nohup "$ROOT_DIR/.venv/bin/python" -m uvicorn main:app --host 127.0.0.1 --port 8000 > logs/uvicorn.log 2>&1 &
  echo $! > logs/uvicorn.pid
else
  nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 > logs/uvicorn.log 2>&1 &
  echo $! > logs/uvicorn.pid
fi

echo "[rebuild] Waiting for backend to become healthy..."
status=""
for i in $(seq 1 30); do
  status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)
  if [ "$status" = "200" ]; then
    echo "[rebuild] Backend is up (HTTP 200)."
    break
  fi
  sleep 1
done

if [ "$status" != "200" ]; then
  echo "[rebuild] Warning: backend did not return 200 after wait (last status: $status)." >&2
  exit 1
fi

echo "[rebuild] Done."
