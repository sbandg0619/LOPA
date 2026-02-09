#!/usr/bin/env bash
set -euo pipefail

# Render에서 /health가 보여준 기본값이 /tmp/lopa_db 였음
DB_DIR="${LOPA_DB_DIR:-/tmp/lopa_db}"
DB_NAME="${LOPA_DEFAULT_DB:-lol_graph_public.db}"

DB_PATH="${DB_DIR}/${DB_NAME}"
GZ_PATH="${DB_PATH}.gz"

# GitHub Releases 최신 alias 파일(네가 말한 “별칭 파일”)
URL="${LOPA_PUBLIC_DB_GZ_URL:-https://github.com/sbandg0619/LOPA/releases/latest/download/lol_graph_public.db.gz}"

mkdir -p "$DB_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "[BOOT] DB missing -> download+gunzip in background"
  echo "[BOOT] URL=$URL"
  echo "[BOOT] DB_PATH=$DB_PATH"

  (
    set -euo pipefail
    rm -f "$GZ_PATH" "${DB_PATH}.tmp"

    curl -L --fail --retry 5 --retry-delay 2 -o "$GZ_PATH" "$URL"

    python -c "import gzip,shutil,os
src=r'$GZ_PATH'
tmp=r'${DB_PATH}.tmp'
dst=r'$DB_PATH'
with gzip.open(src,'rb') as f_in, open(tmp,'wb') as f_out:
    shutil.copyfileobj(f_in,f_out)
os.replace(tmp,dst)
print('[BOOT] DB ready:', dst)
"

    ls -lh "$DB_PATH" || true
  ) &
else
  echo "[BOOT] DB exists: $DB_PATH"
fi

# ✅ 포트 바인딩은 즉시 (Render 포트스캔 통과)
exec gunicorn -k uvicorn.workers.UvicornWorker \
  -w "${WEB_CONCURRENCY:-2}" \
  -b "0.0.0.0:${PORT}" \
  api_server:app
