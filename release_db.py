# release_db.py
from __future__ import annotations

import os
import io
import json
import time
import shutil
import hashlib
import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# -------------------------
# Security defaults
# -------------------------
DEFAULT_ALLOWED_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
}

DEFAULT_MAX_BYTES = int(os.getenv("LOPA_DB_MAX_BYTES") or (3 * 1024 * 1024 * 1024))  # 3GB
DEFAULT_TIMEOUT_SEC = float(os.getenv("LOPA_DB_HTTP_TIMEOUT_SEC") or "30")


@dataclass
class ManifestInfo:
    variant: str
    patch: str
    created_at: Optional[str]
    db_gz_url: str
    db_gz_sha256: str


def _now_ts() -> int:
    return int(time.time())


def _ensure_dir(p: str | Path) -> Path:
    d = Path(p)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_https(url: str) -> bool:
    try:
        return urlparse(url).scheme.lower() == "https"
    except Exception:
        return False


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _check_url_security(url: str, allowed_hosts: set[str]) -> None:
    if not url or not isinstance(url, str):
        raise ValueError("URL is empty")
    if not _is_https(url):
        raise ValueError(f"Only HTTPS is allowed: {url}")
    h = _host(url)
    if h not in allowed_hosts:
        raise ValueError(f"Host not allowed: {h} (url={url})")


def _http_get_bytes(url: str, timeout_sec: float = DEFAULT_TIMEOUT_SEC, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    req = Request(url, headers={"User-Agent": "LOPA/1.0"})
    with urlopen(req, timeout=timeout_sec) as r:
        # best-effort content length guard
        cl = r.headers.get("Content-Length")
        if cl:
            try:
                n = int(cl)
                if n > max_bytes:
                    raise ValueError(f"File too large: {n} bytes > max_bytes={max_bytes}")
            except Exception:
                pass

        buf = io.BytesIO()
        chunk = r.read(1024 * 1024)
        total = 0
        while chunk:
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"File too large while downloading: > max_bytes={max_bytes}")
            buf.write(chunk)
            chunk = r.read(1024 * 1024)
        return buf.getvalue()


def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_manifest(manifest_url: str, allowed_hosts: set[str]) -> Dict[str, Any]:
    _check_url_security(manifest_url, allowed_hosts)
    raw = _http_get_bytes(manifest_url)
    try:
        j = json.loads(raw.decode("utf-8"))
        if not isinstance(j, dict):
            raise ValueError("manifest is not a json object")
        return j
    except Exception as e:
        raise ValueError(f"manifest json parse failed: {e}")


def _parse_manifest(j: Dict[str, Any], variant: str, patch: str) -> ManifestInfo:
    # manifest.json 생성 스크립트에 따라 키가 달라도 최대한 호환
    v = (j.get("variant") or j.get("profile") or "").strip().lower()
    p = (j.get("patch") or j.get("target_patch") or "").strip()

    # 강제 체크(실수 방지)
    if v and v != variant:
        raise ValueError(f"manifest variant mismatch: manifest={v}, expected={variant}")
    if p and p != patch:
        raise ValueError(f"manifest patch mismatch: manifest={p}, expected={patch}")

    created_at = j.get("created_at") or j.get("createdAt")

    db_gz_url = (j.get("db_gz_url") or j.get("dbGzUrl") or "").strip()
    db_gz_sha256 = (j.get("db_gz_sha256") or j.get("dbGzSha256") or j.get("sha256") or "").strip().lower()

    if not db_gz_url or not db_gz_sha256:
        raise ValueError("manifest missing db_gz_url or db_gz_sha256")

    return ManifestInfo(
        variant=variant,
        patch=patch,
        created_at=str(created_at) if created_at else None,
        db_gz_url=db_gz_url,
        db_gz_sha256=db_gz_sha256,
    )


def _atomic_replace(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass
    shutil.copyfile(src, tmp)
    os.replace(str(tmp), str(dst))


def ensure_patch_db_from_manifest(
    manifest_url: str,
    variant: str,
    patch: str,
    out_dir: str = "db",
    force: bool = False,
    allowed_hosts: Optional[set[str]] = None,
) -> Path:
    """
    manifest_url (https)에서 db.gz + sha256을 받아서
    out_dir/lol_graph_{variant}_{patch}.db 를 만든다.

    - 이미 파일이 있으면(force=False) 재다운로드 안 함
    - 보안: https only + host allowlist + sha256 검증
    """
    variant2 = (variant or "").strip().lower()
    patch2 = (patch or "").strip()
    if not variant2:
        raise ValueError("variant is empty")
    if not patch2 or patch2.upper() == "ALL":
        raise ValueError("patch must be specific (not ALL)")

    out = _ensure_dir(out_dir)
    dst_db = out / f"lol_graph_{variant2}_{patch2}.db"

    if dst_db.exists() and not force:
        return dst_db

    allow = allowed_hosts or DEFAULT_ALLOWED_HOSTS

    # 1) manifest load
    mj = _read_manifest(manifest_url, allow)
    info = _parse_manifest(mj, variant2, patch2)

    # 2) validate db url
    _check_url_security(info.db_gz_url, allow)

    # 3) download gz
    gz_bytes = _http_get_bytes(info.db_gz_url)

    # 4) sha256 verify
    got = _sha256_hex(gz_bytes).lower()
    exp = info.db_gz_sha256.lower()
    if got != exp:
        raise ValueError(f"sha256 mismatch for db.gz: got={got}, expected={exp}")

    # 5) decompress to temp file
    tmp_gz = out / f".tmp_{variant2}_{patch2}_{_now_ts()}.db.gz"
    tmp_db = out / f".tmp_{variant2}_{patch2}_{_now_ts()}.db"

    tmp_gz.write_bytes(gz_bytes)

    try:
        with gzip.open(tmp_gz, "rb") as f_in:
            with open(tmp_db, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # 6) atomic replace final db
        _atomic_replace(tmp_db, dst_db)
        return dst_db
    finally:
        for p in (tmp_gz, tmp_db):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
