# db_fetch.py
from __future__ import annotations

import hashlib
import json
import os
import shutil
import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import requests


@dataclass
class Manifest:
    latest_patch: str
    assets: Dict[str, Dict[str, Any]]  # patch -> {url, sha256, filename_db, filename_gz}

    @staticmethod
    def from_json(obj: Dict[str, Any]) -> "Manifest":
        latest = str(obj.get("latest_patch") or "").strip()
        assets = obj.get("assets") or {}
        if not isinstance(assets, dict):
            assets = {}
        return Manifest(latest_patch=latest, assets=assets)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_to(path: Path, url: str, timeout: float = 30.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
        tmp.replace(path)


def _gzip_decompress(gz_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with gzip.open(gz_path, "rb") as fin, tmp.open("wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)
    tmp.replace(out_path)


def fetch_manifest(manifest_url: str) -> Manifest:
    if not manifest_url:
        raise RuntimeError("LOPA_RELEASE_MANIFEST_URL is empty")
    r = requests.get(manifest_url, timeout=20.0)
    r.raise_for_status()
    obj = r.json()
    m = Manifest.from_json(obj)
    if not m.latest_patch:
        raise RuntimeError("manifest.json missing latest_patch")
    return m


def choose_patch(manifest: Manifest) -> str:
    forced = str(os.getenv("LOPA_DB_FORCE_PATCH") or "").strip()
    if forced:
        return forced
    return manifest.latest_patch


def resolve_patch_asset(manifest: Manifest, patch: str) -> Dict[str, Any]:
    a = manifest.assets.get(patch)
    if not a:
        raise RuntimeError(f"manifest has no asset for patch={patch}")
    need_keys = ["url", "sha256", "filename_db", "filename_gz"]
    for k in need_keys:
        if not a.get(k):
            raise RuntimeError(f"manifest asset missing {k} for patch={patch}")
    return a


def ensure_patch_db(
    *,
    manifest_url: str,
    db_dir: str,
) -> Tuple[str, Path]:
    """
    Returns: (patch, db_path)
    - Downloads manifest
    - Chooses patch (forced or latest)
    - Downloads .db.gz
    - Verifies sha256
    - Decompresses to .db (atomic)
    """
    m = fetch_manifest(manifest_url)
    patch = choose_patch(m)
    a = resolve_patch_asset(m, patch)

    db_root = Path(db_dir).resolve()
    gz_path = db_root / str(a["filename_gz"])
    db_path = db_root / str(a["filename_db"])

    # already have db -> ok
    if db_path.exists() and db_path.stat().st_size > 0:
        return patch, db_path

    # download gz if missing
    if not gz_path.exists() or gz_path.stat().st_size <= 0:
        _download_to(gz_path, str(a["url"]))

    # sha256 verify
    want = str(a["sha256"]).strip().lower()
    got = _sha256_file(gz_path).strip().lower()
    if got != want:
        # 깨진 파일이면 지우고 실패
        try:
            gz_path.unlink(missing_ok=True)  # py3.8+; on 3.13 ok
        except Exception:
            pass
        raise RuntimeError(f"sha256 mismatch for {gz_path.name}: want={want} got={got}")

    # decompress to db
    _gzip_decompress(gz_path, db_path)
    if not db_path.exists() or db_path.stat().st_size <= 0:
        raise RuntimeError(f"failed to materialize db: {db_path}")

    return patch, db_path
