# api_server.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

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
PROFILE = (os.getenv("APP_PROFILE") or "public").strip().lower()

DEFAULT_DB_BY_PROFILE = "lol_graph_public.db" if PROFILE == "public" else "lol_graph_personal.db"
DEFAULT_DB = os.getenv("LOPA_DB_DEFAULT") or DEFAULT_DB_BY_PROFILE

app = FastAPI(title="LOPA API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# helpers
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


def _resolve_db_path(db_path: Optional[str]) -> str:
    """
    Render 환경에서 CWD가 바뀌거나, 상대경로가 꼬여도 DB를 찾을 수 있게:
    1) 절대경로면 그대로
    2) 현재 작업폴더(CWD)
    3) api_server.py가 있는 폴더
    4) 레포 루트(= api_server.py 폴더의 상위들 중 git 기준) 대신 간단히: script_dir
    """
    name = (db_path or "").strip() or DEFAULT_DB
    p = Path(name)

    if p.is_absolute():
        return str(p)

    # 1) cwd
    cand1 = Path.cwd() / p
    if cand1.exists():
        return str(cand1)

    # 2) script dir
    here = Path(__file__).resolve().parent
    cand2 = here / p
    if cand2.exists():
        return str(cand2)

    # 3) repo root 추정: here의 부모(대개 동일 폴더일 확률 높음)
    cand3 = here.parent / p
    if cand3.exists():
        return str(cand3)

    # 못 찾으면 "기본적으로 cwd 기준 경로" 반환 (에러 메시지에 쓰기 위함)
    return str(cand1)


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _db_connect_must_exist(db_path: str) -> sqlite3.Connection:
    resolved = _resolve_db_path(db_path)
    if not os.path.exists(resolved):
        raise FileNotFoundError(f"DB not found: {db_path} (resolved: {resolved})")

    # ✅ 중요한 포인트:
    # sqlite3.connect는 파일이 없으면 빈 DB를 새로 만들어버리는데,
    # 위에서 exists를 체크해서 그 케이스를 완전히 차단.
    con = sqlite3.connect(resolved, check_same_thread=False)
    return con


def _require_core_tables(con: sqlite3.Connection) -> None:
    # 공개 데모/심사용 최소 테이블
    if not _table_exists(con, "agg_champ_role"):
        raise RuntimeError("DB is missing required table: agg_champ_role")


# -------------------------
# Schemas
# -------------------------
class RecommendRequest(BaseModel):
    db_path: str = Field(default=DEFAULT_DB)
    patch: str = Field(default="ALL")
    tier: str = Field(default="ALL")
    my_role: str = Field(default="MIDDLE")

    # champ_pool: 내 챔프폭 모드일 때만 사용.
    # 전체 후보 모드에서는 빈 배열로 보내도 OK (서버에서 후보를 뽑음)
    champ_pool: List[int] = Field(default_factory=list)

    bans: List[int] = Field(default_factory=list)
    ally_picks_by_role: Dict[str, List[int]] = Field(default_factory=dict)
    enemy_picks: List[int] = Field(default_factory=list)

    # legacy
    min_games: int = Field(default=30, ge=1, le=10000)

    # ✅ new: pickrate filter (0.005 = 0.5%)
    min_pick_rate: float = Field(default=0.005, ge=0.0, le=1.0)

    # 후보 상한(전체 후보 모드에서)
    max_candidates: int = Field(default=400, ge=10, le=3000)

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
    return {"ok": True, "profile": PROFILE, "default_db": DEFAULT_DB, "loaded_envs": _LOADED_ENVS}


@app.get("/meta")
def meta(db_path: str = DEFAULT_DB):
    try:
        con = _db_connect_must_exist(db_path)
        try:
            _require_core_tables(con)
            latest = get_latest_patch(con)
            patches = get_available_patches(con)
        finally:
            con.close()
        return {"ok": True, "latest_patch": latest, "patches": patches, "db_path": db_path}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    # db 검증은 API에서 먼저(빈 DB 생성/테이블 누락 방지)
    try:
        con = _db_connect_must_exist(req.db_path)
        try:
            _require_core_tables(con)
        finally:
            con.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        recs, reason = recommend_champions(
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
                "reason": reason,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
