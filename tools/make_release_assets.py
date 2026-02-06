from __future__ import annotations

import argparse
import gzip
import json
import hashlib
import time
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="input db path (e.g. lol_graph_public_16.2.db)")
    ap.add_argument("--patch", required=True, help="patch label (e.g. 16.2)")
    ap.add_argument("--variant", default="public", choices=["public", "personal"])
    ap.add_argument("--outdir", default="release_out")
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
    sha_path.write_text(f"{digest}  {gz_name}\n", encoding="utf-8")

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
    print(f"OK: {manifest_path}")


if __name__ == "__main__":
    main()
