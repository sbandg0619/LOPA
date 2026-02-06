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


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _manifest_base_url(manifest_url: str) -> str:
    # "https://.../manifest.json" -> "https://.../"
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
        # 혹시 BOM/기타 이슈가 있어도 최대한 파싱
        return json.loads(raw.decode("utf-8", errors="replace"))


def _extract_file_entry(manifest: Dict[str, Any], patch: str) -> Dict[str, Any]:
    """
    지원하는 manifest 형태:

    1) (구형/단순형)
      { "db_gz_url": "...", "db_gz_sha256": "..." }

    2) (현재 너의 형태)
      {
        "files": {
          "16.2": { "filename": "...db.gz", "sha256": "...", ... }
        }
      }
    """
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


def ensure_patch_db_from_manifest(
    manifest_url: str,
    variant: str,
    patch: str,
    out_dir: str,
    force: bool = False,
) -> Path:
    """
    - manifest_url 에서 manifest.json을 읽고
    - patch에 해당하는 *.db.gz 를 다운로드
    - sha256 검증 후 압축 해제하여 out_dir에 저장
    - 최종 파일명 규칙: out_dir/lol_graph_{variant}_{patch}.db

    return: 생성/존재하는 db 경로(Path)
    """
    v = (variant or "").strip().lower() or "public"
    p = (patch or "").strip()
    if not p or p.upper() == "ALL":
        raise ValueError("patch must be a specific patch like '16.2' (not ALL)")

    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)

    final_db = out_dir_p / f"lol_graph_{v}_{p}.db"
    if final_db.exists() and not force:
        return final_db

    manifest = _read_manifest(manifest_url)
    entry = _extract_file_entry(manifest, p)

    # URL/sha 추출
    db_gz_url: Optional[str] = entry.get("db_gz_url")
    db_gz_sha256: Optional[str] = entry.get("db_gz_sha256")

    if not (db_gz_url and db_gz_sha256):
        # files[patch] 형태 -> base_url + filename
        filename = entry.get("filename")
        sha256 = entry.get("sha256")
        if not (filename and sha256):
            raise ValueError("manifest missing db_gz_url or db_gz_sha256")
        base = _manifest_base_url(manifest_url)
        db_gz_url = base + str(filename)
        db_gz_sha256 = str(sha256)

    # 다운로드 + 검증 + 압축해제는 원자적으로 처리
    tmp_root = out_dir_p / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(tmp_root)) as td:
        td_p = Path(td)

        gz_path = _download_to_tmp(db_gz_url, td_p)

        # sha256 검증 (gz 파일 기준)
        got = _sha256_file(gz_path).lower()
        exp = str(db_gz_sha256).strip().lower()
        if got != exp:
            raise ValueError(f"sha256 mismatch for gz: expected={exp} got={got}")

        tmp_db = td_p / f"tmp_{v}_{p}.db"
        _gunzip_file(gz_path, tmp_db)

        # 최종 파일로 이동(원자적 교체)
        # Windows/리눅스 모두 고려: replace 사용
        tmp_final = out_dir_p / (final_db.name + ".tmp")
        shutil.copy2(tmp_db, tmp_final)
        os.replace(str(tmp_final), str(final_db))

    return final_db
