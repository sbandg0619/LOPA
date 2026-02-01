import json
import os
from pathlib import Path

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

def _pool_path() -> str:
    """
    작업폴더(cwd) 영향 제거:
    - 이 파일(champ_pool_store.py) 기준 폴더에 저장
    - profile별로 파일 분리: champ_pool.personal.json / champ_pool.public.json
    """
    here = Path(__file__).resolve().parent
    profile = (os.getenv("APP_PROFILE") or "personal").strip().lower()
    name = f"champ_pool.{profile}.json"
    return str(here / name)

def _normalize_pool(data):
    if isinstance(data, list):
        new_data = {r: [] for r in ROLES}
        new_data["UTILITY"] = data[:]
        return new_data

    if not isinstance(data, dict):
        return {r: [] for r in ROLES}

    for r in ROLES:
        data.setdefault(r, [])
        seen = set()
        dedup = []
        for x in data[r]:
            if x in seen:
                continue
            seen.add(x)
            dedup.append(x)
        data[r] = dedup

    return data

def load_pool(create_if_missing=True, migrate=True):
    path = _pool_path()

    if not os.path.exists(path):
        pool = {r: [] for r in ROLES}
        if create_if_missing:
            save_pool(pool)
        return pool

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pool = _normalize_pool(data)

    if migrate and pool != data:
        save_pool(pool)

    return pool

def save_pool(pool: dict):
    path = _pool_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

def get_pool_for_role(role: str):
    pool = load_pool()
    return pool.get(role, [])

def get_flat_pool():
    pool = load_pool()
    out = []
    for r in ROLES:
        out.extend(pool.get(r, []))
    seen = set()
    dedup = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup
