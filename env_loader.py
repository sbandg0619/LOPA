# env_loader.py
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

_LOADED = False


def _project_dir() -> Path:
    # 이 파일이 있는 폴더를 "프로젝트 루트"로 가정
    return Path(__file__).resolve().parent


def load_project_env(profile: str | None = None, override: bool = False) -> str:
    """
    profile 우선순위:
      1) 명시 인자 profile
      2) 환경변수 APP_PROFILE
      3) 기본 "personal"

    로드 우선순위:
      - .env.<profile> 가 있으면 그걸 먼저 로드
      - 없으면 .env 로드
    """
    global _LOADED
    if _LOADED:
        # 중복 로드 방지 (여러 모듈에서 호출해도 OK)
        return os.getenv("APP_PROFILE", profile or "") or ""

    proj = _project_dir()

    p = (profile or os.getenv("APP_PROFILE") or "personal").strip().lower()
    if p not in ("personal", "public"):
        # 알 수 없는 값이면 personal로 폴백
        p = "personal"

    # APP_PROFILE는 항상 정규화해서 환경변수로 고정
    os.environ["APP_PROFILE"] = p

    env_profile = proj / f".env.{p}"
    env_default = proj / ".env"

    loaded = False
    if env_profile.exists():
        load_dotenv(dotenv_path=env_profile, override=override)
        loaded = True

    # profile env에 키가 없을 수도 있으니 .env도 이어서 로드(override=False면 profile 값 보존)
    if env_default.exists():
        load_dotenv(dotenv_path=env_default, override=False if loaded else override)

    _LOADED = True
    return p
