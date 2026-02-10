from __future__ import annotations

import argparse
import gzip
import json
import hashlib
import time
import shutil
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_compress(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=9) as f_out:
        while True:
            b = f_in.read(1024 * 1024)
            if not b:
                break
            f_out.write(b)


def write_sha256(digest: str, filename: str, sha_path: Path) -> None:
    sha_path.write_text(f"{digest}  {filename}\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="input db path (e.g. lol_graph_public_16.2.db)")
    ap.add_argument("--patch", required=True, help="patch label (e.g. 16.2)")
    ap.add_argument("--variant", default="public", choices=["public", "personal"])
    ap.add_argument("--outdir", default="release_out")
    # alias 생성 on/off (기본: 켬)
    ap.add_argument("--no_alias", action="store_true", help="do not create lol_graph_{variant}.db.gz alias")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"DB not found: {db}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Naming rule A (current): lol_graph_{variant}_{patch}.db.gz
    gz_name = f"lol_graph_{args.variant}_{args.patch}.db.gz"
    gz_path = outdir / gz_name

    print(f"[1] gzip: {db} -> {gz_path}")
    gzip_compress(db, gz_path)

    print("[2] sha256...")
    digest = sha256_file(gz_path)
    sha_path = outdir / f"{gz_name}.sha256"
    write_sha256(digest, gz_name, sha_path)

    # NEW: alias 파일 생성 (예: lol_graph_public.db.gz)
    alias_gz_name = f"lol_graph_{args.variant}.db.gz"
    alias_gz_path = outdir / alias_gz_name
    alias_sha_path = outdir / f"{alias_gz_name}.sha256"

    made_alias = False
    if not args.no_alias:
        if alias_gz_path.resolve() != gz_path.resolve():
            print(f"[2.5] alias: {gz_name} -> {alias_gz_name}")
            shutil.copy2(gz_path, alias_gz_path)
            # 내용 동일하므로 digest 동일. sha256 파일만 별칭명으로 따로 기록
            write_sha256(digest, alias_gz_name, alias_sha_path)
            made_alias = True
        else:
            print("[2.5] alias skipped (same path)")

    print("[3] manifest.json update...")
    manifest_path = outdir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            manifest = {}
    else:
        manifest = {}

    manifest.setdefault("schema_version", 1)
    manifest.setdefault("generated_at", int(time.time()))
    manifest.setdefault("variant", args.variant)
    manifest.setdefault("files", {})

    manifest["generated_at"] = int(time.time())
    manifest["files"][args.patch] = {
        "patch": args.patch,
        "variant": args.variant,
        "filename": gz_name,
        "sha256": digest,
        "bytes": gz_path.stat().st_size,
    }

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: {gz_path}")
    print(f"OK: {sha_path}")
    if made_alias:
        print(f"OK: {alias_gz_path}")
        print(f"OK: {alias_sha_path}")
    print(f"OK: {manifest_path}")


if __name__ == "__main__":
    main()
