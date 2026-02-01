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


def _db_connect(db_path: str) -> sqlite3.Connection:
    if not db_path:
        db_path = DEFAULT_DB
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

    # ✅ champ_pool: 비어있어도 허용(전체 후보 모드)
    champ_pool: List[int] = Field(default_factory=list)

    bans: List[int] = Field(default_factory=list)
    ally_picks_by_role: Dict[str, List[int]] = Field(default_factory=dict)
    enemy_picks: List[int] = Field(default_factory=list)

    # ✅ 기존 min_games는 0도 허용(필요하면 유지)
    min_games: int = Field(default=0, ge=0, le=100000)

    # ✅ NEW: 픽률 필터(기본 0.5%)
    min_pick_rate: float = Field(default=0.005, ge=0.0, le=1.0)

    top_n: int = Field(default=10, ge=1, le=50)

    # ✅ 너무 커지는 거 방지용
    max_candidates: int = Field(default=400, ge=50, le=2000)


class RecommendResponse(BaseModel):
    ok: bool
    recs: List[Dict[str, Any]]
    meta: Dict[str, Any]


# -------------------------
# Endpoints
# -------------------------
@app.get("/health")
def health():
    return {"ok": True, "profile": PROFILE, "default_db": DEFAULT_DB}


@app.get("/meta")
def meta(db_path: str = DEFAULT_DB):
    try:
        con = _db_connect(db_path)
        try:
            latest = get_latest_patch(con)
            patches = get_available_patches(con)
        finally:
            con.close()
        return {"ok": True, "latest_patch": latest, "patches": patches, "db_path": db_path}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/env")
def env_debug():
    return {"ok": True, "profile": PROFILE, "loaded_envs": _LOADED_ENVS, "default_db": DEFAULT_DB}


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

    champ_pool = [int(x) for x in (req.champ_pool or []) if int(x) != 0]
    bans = [int(x) for x in (req.bans or []) if int(x) != 0]
    enemy = [int(x) for x in (req.enemy_picks or []) if int(x) != 0]

    # ✅ 핵심 변경:
    # - champ_pool이 비면 "전체 후보 모드"로 동작 (에러 내지 않음)
    try:
        recs, extra = recommend_champions(
            db_path=req.db_path,
            patch=patch,
            tier=tier,
            my_role=my_role,
            champ_pool=champ_pool,
            bans=bans,
            ally_picks_by_role=ally,
            enemy_picks=enemy,
            min_games=req.min_games,
            min_pick_rate=req.min_pick_rate,
            top_n=req.top_n,
            max_candidates=req.max_candidates,
        )

        return {
            "ok": True,
            "recs": recs,
            "meta": {
                "db_path": req.db_path,
                "patch": patch,
                "tier": tier,
                "my_role": my_role,
                "min_games": req.min_games,
                "min_pick_rate": req.min_pick_rate,
                "top_n": req.top_n,
                "max_candidates": req.max_candidates,
                **(extra or {}),
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
