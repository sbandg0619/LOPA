# release_db.py
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


def _http_get_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LOPA-DB-Downloader/1.0",
            "Accept": "application/json,*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_base_url(manifest_url: str) -> str:
    u = (manifest_url or "").strip()
    if not u:
        return ""
    if "/" not in u:
        return u
    return u.rsplit("/", 1)[0] + "/"


def _read_manifest(manifest_url: str) -> Dict[str, Any]:
    raw = _http_get_bytes(manifest_url, timeout=60)
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("utf-8", errors="replace"))


def _extract_file_entry(manifest: Dict[str, Any], patch: str) -> Dict[str, Any]:
    # 형태 1
    if isinstance(manifest, dict):
        if manifest.get("db_gz_url") and manifest.get("db_gz_sha256"):
            return {
                "db_gz_url": str(manifest["db_gz_url"]),
                "db_gz_sha256": str(manifest["db_gz_sha256"]),
            }

    # 형태 2
    files = manifest.get("files")
    if isinstance(files, dict):
        entry = files.get(patch) or files.get(str(patch))
        if isinstance(entry, dict):
            filename = entry.get("filename")
            sha256 = entry.get("sha256")
            if filename and sha256:
                return {
                    "filename": str(filename),
                    "sha256": str(sha256),
                    "bytes": entry.get("bytes"),
                    "patch": entry.get("patch", patch),
                    "variant": entry.get("variant"),
                }

    raise ValueError("manifest missing db_gz_url/db_gz_sha256 OR files[patch].filename/files[patch].sha256")


def _download_to_tmp(url: str, tmp_dir: Path) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / ("download_" + str(int(time.time() * 1000)) + ".bin")
    data = _http_get_bytes(url, timeout=180)
    out.write_bytes(data)
    return out


def _gunzip_file(src_gz: Path, dst: Path) -> None:
    import gzip

    dst.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src_gz, "rb") as f_in, dst.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _read_first_token(path: Path) -> str:
    try:
        txt = path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return ""
    if not txt:
        return ""
    # "sha" or "sha  filename" -> first token
    return txt.split()[0].strip()


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass


def ensure_patch_db_from_manifest(
    manifest_url: str,
    variant: str,
    patch: str,
    out_dir: str,
    force: bool = False,
) -> Path:
    """
    - manifest_url에서 manifest.json을 읽고 patch에 해당하는 *.db.gz를 다운로드
    - sha256 검증 후 압축 해제하여 out_dir에 저장
    - 최종 파일명 규칙: out_dir/lol_graph_{variant}_{patch}.db

    ✅ 변경점:
    - final_db가 이미 있어도, (force=False라도) 일정 주기마다 manifest sha를 확인해서
      로컬 sha와 다르면 자동으로 재다운로드/교체 가능
    """
    v = (variant or "").strip().lower() or "public"
    p = (patch or "").strip()
    if not p or p.upper() == "ALL":
        raise ValueError("patch must be a specific patch like '16.2' (not ALL)")

    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)

    final_db = out_dir_p / f"lol_graph_{v}_{p}.db"

    # 로컬 메타(원격 gz sha 저장)
    local_sha_path = final_db.with_name(final_db.name + ".sha256")
    lastcheck_path = final_db.with_name(final_db.name + ".last_check")

    # 체크 주기(초). 기본 3600초. 0 이하이면 체크 비활성(있으면 그냥 씀)
    try:
        check_every = int(os.getenv("LOPA_PATCH_DB_UPDATE_CHECK_EVERY", "3600"))
    except Exception:
        check_every = 3600

    def should_check_now() -> bool:
        if check_every <= 0:
            return False
        try:
            if not lastcheck_path.exists():
                return True
            age = time.time() - lastcheck_path.stat().st_mtime
            return age >= check_every
        except Exception:
            return True

    # 파일이 있고 force가 아니면:
    # - 체크 주기 안 됐으면 바로 return
    # - 체크 주기 됐으면 manifest sha 확인 후 같으면 return, 다르면 교체 진행
    if final_db.exists() and not force:
        if not should_check_now():
            return final_db

        try:
            manifest = _read_manifest(manifest_url)
            entry = _extract_file_entry(manifest, p)

            db_gz_url: Optional[str] = entry.get("db_gz_url")
            db_gz_sha256: Optional[str] = entry.get("db_gz_sha256")

            if not (db_gz_url and db_gz_sha256):
                filename = entry.get("filename")
                sha256 = entry.get("sha256")
                if not (filename and sha256):
                    _touch(lastcheck_path)
                    return final_db
                base = _manifest_base_url(manifest_url)
                db_gz_url = base + str(filename)
                db_gz_sha256 = str(sha256)

            remote_sha = str(db_gz_sha256).strip().lower()
            local_sha = _read_first_token(local_sha_path).lower()

            _touch(lastcheck_path)

            if local_sha and local_sha == remote_sha:
                return final_db
            # local_sha가 없거나 다르면 아래 다운로드/교체로 진행
        except Exception:
            # 업데이트 체크 실패(네트워크/manifest 문제)면 안정적으로 기존 DB 유지
            _touch(lastcheck_path)
            return final_db

    # 여기부터는: (1) 파일이 없거나 (2) force=True거나 (3) sha가 달라서 교체 필요
    manifest = _read_manifest(manifest_url)
    entry = _extract_file_entry(manifest, p)

    db_gz_url: Optional[str] = entry.get("db_gz_url")
    db_gz_sha256: Optional[str] = entry.get("db_gz_sha256")

    if not (db_gz_url and db_gz_sha256):
        filename = entry.get("filename")
        sha256 = entry.get("sha256")
        if not (filename and sha256):
            raise ValueError("manifest missing db_gz_url or db_gz_sha256")
        base = _manifest_base_url(manifest_url)
        db_gz_url = base + str(filename)
        db_gz_sha256 = str(sha256)

    tmp_root = out_dir_p / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(tmp_root)) as td:
        td_p = Path(td)

        gz_path = _download_to_tmp(db_gz_url, td_p)

        got = _sha256_file(gz_path).lower()
        exp = str(db_gz_sha256).strip().lower()
        if got != exp:
            raise ValueError(f"sha256 mismatch for gz: expected={exp} got={got}")

        tmp_db = td_p / f"tmp_{v}_{p}.db"
        _gunzip_file(gz_path, tmp_db)

        tmp_final = out_dir_p / (final_db.name + ".tmp")
        shutil.copy2(tmp_db, tmp_final)
        os.replace(str(tmp_final), str(final_db))

        # 로컬 sha/lastcheck 갱신
        local_sha_path.write_text(exp + "\n", encoding="utf-8")
        _touch(lastcheck_path)

    return final_db
