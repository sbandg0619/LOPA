# api_server.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dotenv import load_dotenv

from recommender import (
    recommend_champions,
    get_latest_patch,
    get_available_patches,
)

from release_db import ensure_patch_db_from_manifest

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


# -------------------------
# .env loader (profile aware)
# -------------------------
def _load_env_candidates() -> List[str]:
    here = Path(__file__).resolve().parent
    profile = (os.getenv("APP_PROFILE") or "").strip().lower()

    candidates: List[Path] = []
    if profile:
        candidates.append(here / f".env.{profile}")

    candidates += [
        here / ".env.personal",
        here / ".env.public",
        here / ".env",
    ]

    loaded: List[str] = []
    for p in candidates:
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)
            loaded.append(str(p))
    return loaded


_LOADED_ENVS = _load_env_candidates()
PROFILE = (os.getenv("APP_PROFILE") or "personal").strip().lower()

DEFAULT_DB_BY_PROFILE = "lol_graph_public.db" if PROFILE == "public" else "lol_graph_personal.db"
DEFAULT_DB = os.getenv("LOPA_DB_DEFAULT") or DEFAULT_DB_BY_PROFILE

MANIFEST_PUBLIC = (os.getenv("LOPA_RELEASE_MANIFEST_PUBLIC") or "").strip()
MANIFEST_PERSONAL = (os.getenv("LOPA_RELEASE_MANIFEST_PERSONAL") or "").strip()

DB_DIR = (os.getenv("LOPA_DB_DIR") or "db").strip()


app = FastAPI(title="LOPA API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# Normalizers (API-side)
# -------------------------
_ROLE_MAP = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLE",
    "JG": "JUNGLE",
    "MID": "MIDDLE",
    "MIDDLE": "MIDDLE",
    "BOT": "BOTTOM",
    "BOTTOM": "BOTTOM",
    "ADC": "BOTTOM",
    "SUP": "UTILITY",
    "SUPPORT": "UTILITY",
    "UTILITY": "UTILITY",
}


def normalize_role(role: str) -> str:
    r = (role or "").strip().upper()
    if not r:
        return "MIDDLE"
    return _ROLE_MAP.get(r, r)


def normalize_patch(patch: str) -> str:
    p = (patch or "").strip()
    if not p:
        return "ALL"
    if p.upper() == "ALL":
        return "ALL"
    return p


def normalize_tier(tier: str) -> str:
    t = (tier or "").strip().upper()
    if not t:
        return "ALL"
    if t == "ALL":
        return "ALL"
    return t


def _manifest_for_variant(variant: str) -> str:
    v = (variant or "").strip().lower()
    if v == "public":
        return MANIFEST_PUBLIC
    return MANIFEST_PERSONAL


def _variant_for_profile() -> str:
    return "public" if PROFILE == "public" else "personal"


def _is_explicit_db_path(user_db_path: str) -> bool:
    """
    ✅ 유저가 request에 '명시적으로' db_path를 준 케이스인지 판정
    - 기본값(DEFAULT_DB)이 그대로 넘어온 경우는 명시로 보지 않음
    - 빈 문자열도 명시로 보지 않음
    """
    p = (user_db_path or "").strip()
    if not p:
        return False
    if p == DEFAULT_DB:
        return False
    return True


def _is_path_like(p: str) -> bool:
    p = (p or "").strip()
    if not p:
        return False
    if os.path.isabs(p):
        return True
    return ("/" in p) or ("\\" in p)


def _resolve_all_db_path(user_db_path: str) -> str:
    """
    ✅ 중요(네 요구사항 반영):
    - patch=ALL 단일 DB는 "절대 CWD에서 찾지 않음"
    - db_path가 파일명만 오면 무조건 DB_DIR 아래로 해석한다.
    - db_path가 경로면 그대로 사용한다.
    """
    raw = (user_db_path or "").strip()
    use = raw if raw else DEFAULT_DB

    if _is_path_like(use):
        return use

    # 파일명만 오면 DB_DIR 밑으로 강제
    return os.path.join(DB_DIR, use)


def _resolve_db_path_for_request(user_db_path: str, patch: str) -> str:
    """
    규칙:
    - patch == "ALL":
        - 단일 DB는 _resolve_all_db_path()로 해결(= DB_DIR 강제)
    - patch != "ALL":
        - 유저가 db_path를 "명시적으로" 줬으면 그걸 사용(고급/디버그용)
        - 아니면 db_dir/lol_graph_{variant}_{patch}.db 를 사용 (없으면 자동 다운로드 대상)
    """
    patch = normalize_patch(patch)

    if patch == "ALL":
        return _resolve_all_db_path(user_db_path)

    if _is_explicit_db_path(user_db_path):
        return user_db_path

    variant = _variant_for_profile()
    patch_db = os.path.join(DB_DIR, f"lol_graph_{variant}_{patch}.db")
    return patch_db


def _ensure_patch_db_if_needed(db_path: str, patch: str) -> str:
    patch = normalize_patch(patch)

    try:
        os.makedirs(DB_DIR, exist_ok=True)
    except Exception:
        pass

    # ALL은 단일 DB 사용. (다운로드는 start script가 담당)
    if patch == "ALL":
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"DB not found: {db_path} (patch=ALL)")
        return db_path

    if os.path.exists(db_path):
        return db_path

    variant = _variant_for_profile()
    manifest_url = _manifest_for_variant(variant)
    if not manifest_url:
        raise FileNotFoundError(
            f"Patch DB not found: {db_path} and manifest env missing. "
            f"Set LOPA_RELEASE_MANIFEST_{variant.upper()}=..."
        )

    out = ensure_patch_db_from_manifest(
        manifest_url=manifest_url,
        variant=variant,
        patch=patch,
        out_dir=DB_DIR,
        force=False,
    )
    return str(out)


def _db_connect(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB not found: {db_path}")
    return sqlite3.connect(db_path, check_same_thread=False)


# -------------------------
# Schemas
# -------------------------
class RecommendRequest(BaseModel):
    db_path: str = Field(default=DEFAULT_DB)
    patch: str = Field(default="ALL")
    tier: str = Field(default="ALL")
    my_role: str = Field(default="MIDDLE")

    use_champ_pool: bool = Field(default=True)

    champ_pool: List[int] = Field(default_factory=list)
    bans: List[int] = Field(default_factory=list)
    ally_picks_by_role: Dict[str, List[int]] = Field(default_factory=dict)
    enemy_picks: List[int] = Field(default_factory=list)

    min_games: int = Field(default=30, ge=1, le=10000)
    min_pick_rate: float = Field(default=0.005, ge=0.0, le=1.0)
    max_candidates: int = Field(default=400, ge=10, le=5000)

    top_n: int = Field(default=10, ge=1, le=50)


class RecommendResponse(BaseModel):
    ok: bool
    recs: List[Dict[str, Any]]
    meta: Dict[str, Any]


# -------------------------
# Endpoints
# -------------------------
@app.get("/health")
def health():
    resolved_default = _resolve_db_path_for_request(DEFAULT_DB, "ALL")
    return {
        "ok": True,
        "profile": PROFILE,
        "default_db": DEFAULT_DB,
        "db_dir": DB_DIR,
        "default_db_resolved": resolved_default,
        "default_db_exists": bool(os.path.exists(resolved_default)),
        "manifest_public_set": bool(MANIFEST_PUBLIC),
        "manifest_personal_set": bool(MANIFEST_PERSONAL),
    }


@app.get("/meta")
def meta(db_path: str = DEFAULT_DB, patch: str = "ALL"):
    try:
        patch2 = normalize_patch(patch)
        resolved = _resolve_db_path_for_request(db_path, patch2)
        resolved = _ensure_patch_db_if_needed(resolved, patch2)

        con = _db_connect(resolved)
        try:
            latest = get_latest_patch(con)
            patches = get_available_patches(con)
        finally:
            con.close()

        return {
            "ok": True,
            "latest_patch": latest,
            "patches": patches,
            "db_path": resolved,
            "patch_arg": patch2,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/env")
def env_debug():
    return {
        "ok": True,
        "profile": PROFILE,
        "loaded_envs": _LOADED_ENVS,
        "default_db": DEFAULT_DB,
        "db_dir": DB_DIR,
        "default_db_resolved": _resolve_db_path_for_request(DEFAULT_DB, "ALL"),
        "manifest_public": MANIFEST_PUBLIC,
        "manifest_personal": MANIFEST_PERSONAL,
    }


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    patch = normalize_patch(req.patch)
    tier = normalize_tier(req.tier)
    my_role = normalize_role(req.my_role)

    if my_role not in ROLES:
        raise HTTPException(status_code=400, detail=f"invalid my_role(after normalize): {req.my_role} -> {my_role}")

    ally: Dict[str, List[int]] = {r: [] for r in ROLES}
    for k, v in (req.ally_picks_by_role or {}).items():
        kk = normalize_role(k)
        if kk in ROLES and isinstance(v, list):
            ally[kk] = [int(x) for x in v if int(x) != 0]

    bans = [int(x) for x in (req.bans or []) if int(x) != 0]
    enemy = [int(x) for x in (req.enemy_picks or []) if int(x) != 0]
    champ_pool = [int(x) for x in (req.champ_pool or []) if int(x) != 0]

    if req.use_champ_pool and not champ_pool:
        raise HTTPException(status_code=400, detail="champ_pool is empty (use_champ_pool=true)")

    try:
        resolved = _resolve_db_path_for_request(req.db_path, patch)
        resolved = _ensure_patch_db_if_needed(resolved, patch)

        recs, meta2 = recommend_champions(
            db_path=resolved,
            patch=patch,
            tier=tier,
            my_role=my_role,
            champ_pool=champ_pool,
            bans=bans,
            ally_picks_by_role=ally,
            enemy_picks=enemy,
            min_games=req.min_games,
            min_pick_rate=req.min_pick_rate,
            use_champ_pool=req.use_champ_pool,
            max_candidates=req.max_candidates,
            top_n=req.top_n,
        )

        return {
            "ok": True,
            "recs": recs,
            "meta": {
                "db_path": resolved,
                "patch": patch,
                "tier": tier,
                "my_role": my_role,
                "min_games": req.min_games,
                "min_pick_rate": req.min_pick_rate,
                "top_n": req.top_n,
                "max_candidates": req.max_candidates,
                "use_champ_pool": req.use_champ_pool,
                "reason": meta2.get("reason", "ok"),
                "enemy_role_guess": meta2.get("enemy_role_guess", {}) or {},
                "enemy_role_guess_method": meta2.get("enemy_role_guess_method", "unknown"),
                "enemy_role_guess_detail": meta2.get("enemy_role_guess_detail", {}) or {},
                "used_enemy_role_column": bool(meta2.get("used_enemy_role_column", False)),
                "counter_used_role_filtered_cnt": int(meta2.get("counter_used_role_filtered_cnt", 0) or 0),
                "counter_used_roleless_cnt": int(meta2.get("counter_used_roleless_cnt", 0) or 0),
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
