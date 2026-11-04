#!/usr/bin/env bash
# 本机调试后端：不经过 fnOS，监听 http://127.0.0.1:8080。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

export MONTUBE_DB_PATH="${MONTUBE_DB_PATH:-$ROOT/.devdata/montube.db}"
export MONTUBE_DOWNLOAD_DIR="${MONTUBE_DOWNLOAD_DIR:-$ROOT/.devdata/downloads}"
export MONTUBE_HOST="${MONTUBE_HOST:-127.0.0.1}"
export MONTUBE_PORT="${MONTUBE_PORT:-8080}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$(dirname "$MONTUBE_DB_PATH")" "$MONTUBE_DOWNLOAD_DIR"

if ! "$PYTHON_BIN" -c 'import fastapi, uvicorn, pydantic, yt_dlp' 2>/dev/null; then
  cat >&2 <<'EOF'
Montube 本机调试需要当前 Python 环境安装 fastapi、uvicorn、pydantic 和 yt-dlp。
请先执行：
  python3 -m pip install -r requirements.txt
EOF
  exit 1
fi

echo "Montube 调试服务：http://${MONTUBE_HOST}:${MONTUBE_PORT}"
echo "数据目录：$(dirname "$MONTUBE_DB_PATH")"
echo "下载目录：${MONTUBE_DOWNLOAD_DIR}"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host "$MONTUBE_HOST" --port "$MONTUBE_PORT" --reload
