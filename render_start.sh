#!/usr/bin/env bash
set -euo pipefail

# ====== Paths ======
DB_DIR="${LOPA_DB_DIR:-/tmp/lopa_db}"
# api_server.py는 LOPA_DB_DEFAULT를 쓰고, 기존 스크립트는 LOPA_DEFAULT_DB를 쓰는 경우가 있어 둘 다 지원
DB_NAME="${LOPA_DB_DEFAULT:-${LOPA_DEFAULT_DB:-lol_graph_public.db}}"

DB_PATH="${DB_DIR}/${DB_NAME}"
GZ_PATH="${DB_PATH}.gz"
# 로컬에 "현재 설치된 gz의 sha256" 저장 (db 파일 옆에 둠)
LOCAL_SHA_PATH="${DB_PATH}.sha256"

# ====== Remote URLs ======
URL_GZ="${LOPA_PUBLIC_DB_GZ_URL:-https://github.com/sbandg0619/LOPA/releases/latest/download/lol_graph_public.db.gz}"
# sha256 파일은 기본적으로 .sha256 붙인 것으로 가정 (없으면 아래 env로 따로 지정 가능)
URL_SHA="${LOPA_PUBLIC_DB_GZ_SHA256_URL:-${URL_GZ}.sha256}"

# ====== Update check interval (seconds) ======
# 0이면 "부팅 시 1회만" (DB 없으면 다운로드, 있으면 sha 비교 후 필요 시 갱신)
# 3600이면 1시간마다 sha 비교 → 바뀌면 자동 교체
CHECK_EVERY="${LOPA_DB_UPDATE_CHECK_EVERY:-0}"

mkdir -p "$DB_DIR"

_fetch_remote_sha() {
  # sha256 파일은 한 줄에 sha만 있거나(네가 생성하는 형식), "sha  filename" 형식일 수도 있어 첫 토큰만 씀
  curl -L --fail -s "$URL_SHA" 2>/dev/null | head -n 1 | tr -d '\r' | awk '{print $1}'
}

_read_local_sha() {
  if [ -f "$LOCAL_SHA_PATH" ]; then
    head -n 1 "$LOCAL_SHA_PATH" | tr -d '\r' | awk '{print $1}'
  else
    echo ""
  fi
}

_verify_gz_sha_or_fail() {
  # args: <gz_path> <expected_sha>
  python - "$1" "$2" <<'PY'
import hashlib, sys
p = sys.argv[1]
exp = (sys.argv[2] or "").strip().lower()
if not exp:
    print("[BOOT] sha empty -> skip verify")
    sys.exit(0)

h = hashlib.sha256()
with open(p, "rb") as f:
    for chunk in iter(lambda: f.read(1024*1024), b""):
        h.update(chunk)
got = h.hexdigest().lower()
if got != exp:
    raise SystemExit(f"[BOOT] sha256 mismatch: expected={exp} got={got}")
print("[BOOT] sha256 OK")
PY
}

_download_and_swap_db() {
  # args: <remote_sha or empty>
  REMOTE_SHA="${1:-}"

  rm -f "${DB_PATH}.tmp" "${GZ_PATH}.part" "${GZ_PATH}"

  echo "[BOOT] downloading: $URL_GZ"
  curl -L --fail --retry 5 --retry-delay 2 -o "${GZ_PATH}.part" "$URL_GZ"

  # 검증(sha를 구할 수 있을 때만)
  if [ -n "$REMOTE_SHA" ]; then
    _verify_gz_sha_or_fail "${GZ_PATH}.part" "$REMOTE_SHA"
  fi

  mv -f "${GZ_PATH}.part" "${GZ_PATH}"

  # gunzip -> tmp -> atomic replace
  python - <<PY
import gzip, shutil, os
src=r'''${GZ_PATH}'''
tmp=r'''${DB_PATH}.tmp'''
dst=r'''${DB_PATH}'''
with gzip.open(src,'rb') as f_in, open(tmp,'wb') as f_out:
    shutil.copyfileobj(f_in,f_out)
os.replace(tmp,dst)
print('[BOOT] DB swapped/ready:', dst)
PY

  # 로컬 sha 기록
  if [ -n "$REMOTE_SHA" ]; then
    echo "$REMOTE_SHA" > "$LOCAL_SHA_PATH"
    echo "[BOOT] local sha updated: $LOCAL_SHA_PATH"
  fi

  ls -lh "$DB_PATH" || true
}

_update_once() {
  # 동시 실행 방지 락
  LOCKDIR="${DB_PATH}.lockdir"
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "[BOOT] updater lock busy -> skip this round"
    return 0
  fi
  trap 'rmdir "$LOCKDIR" 2>/dev/null || true' RETURN

  REMOTE_SHA="$(_fetch_remote_sha || true)"
  LOCAL_SHA="$(_read_local_sha || true)"

  if [ ! -f "$DB_PATH" ]; then
    echo "[BOOT] DB missing -> download+gunzip"
    _download_and_swap_db "$REMOTE_SHA"
    return 0
  fi

  # sha를 못 구하면(sha asset 업로드 안 했거나 네트워크 문제) 안전하게 "그냥 유지"
  if [ -z "$REMOTE_SHA" ]; then
    echo "[BOOT] remote sha unavailable -> keep existing DB"
    return 0
  fi

  # 로컬 sha가 없거나(구버전 설치), sha가 다르면 갱신
  if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "[BOOT] DB update detected -> swap to new DB"
    echo "[BOOT] local_sha=${LOCAL_SHA:-<empty>} remote_sha=$REMOTE_SHA"
    _download_and_swap_db "$REMOTE_SHA"
  else
    echo "[BOOT] DB up-to-date (sha match)"
  fi
}

# ====== updater worker ======
(
  set -euo pipefail
  echo "[BOOT] updater started. DB_PATH=$DB_PATH"
  echo "[BOOT] URL_GZ=$URL_GZ"
  echo "[BOOT] URL_SHA=$URL_SHA"
  echo "[BOOT] CHECK_EVERY=$CHECK_EVERY"

  while true; do
    _update_once || true
    if [ "${CHECK_EVERY}" -le 0 ]; then
      break
    fi
    sleep "$CHECK_EVERY"
  done
) &

# ✅ 포트 바인딩은 즉시 (Render 포트스캔 통과)
exec gunicorn -k uvicorn.workers.UvicornWorker \
  -w "${WEB_CONCURRENCY:-2}" \
  -b "0.0.0.0:${PORT}" \
  api_server:app
