# riot_api.py
from __future__ import annotations

import os
import time
import random
import requests
from pathlib import Path
from urllib.parse import quote
from collections import deque
from dotenv import load_dotenv

# NOTE: 기존 코드와 동일하게 "호스트명만" 둠 (scheme 없음)
ASIA_HOST = "asia.api.riotgames.com"
KR_HOST = "kr.api.riotgames.com"


def _clean_key(raw: str | None) -> str:
    key = (raw or "")
    return key.strip().strip('"').strip("'")


def _truthy(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _load_env_candidates() -> list[str]:
    """
    ✅ 프로필 기반 env 로드
    - APP_PROFILE=public  -> .env.public
    - APP_PROFILE=personal -> .env.personal
    그리고 공통 fallback(.env)도 지원

    우선순위:
      1) .env.<profile> (있으면)
      2) .env.public / .env.personal (혹시 profile 미설정 대비)
      3) .env
    """
    here = Path(__file__).resolve().parent
    profile = (os.getenv("APP_PROFILE") or "").strip().lower()

    cands: list[Path] = []
    if profile:
        cands.append(here / f".env.{profile}")

    cands.extend([
        here / ".env.public",
        here / ".env.personal",
        here / ".env",
    ])

    loaded: list[str] = []
    for p in cands:
        if p.exists():
            load_dotenv(dotenv_path=p, override=False)
            loaded.append(str(p))
    return loaded


def _parse_retry_after(headers: dict) -> float | None:
    ra = headers.get("Retry-After") or headers.get("retry-after")
    if not ra:
        return None
    try:
        return float(ra)
    except Exception:
        return None


def _parse_app_rate_limit(limit_header: str | None):
    """
    X-App-Rate-Limit: "20:1,100:120" 형태를 파싱해서 (limit_1s, limit_120s) 반환
    """
    if not limit_header:
        return None, None
    try:
        parts = [p.strip() for p in limit_header.split(",") if p.strip()]
        lim_1s = None
        lim_120s = None
        for p in parts:
            a, b = p.split(":")
            limit = int(a.strip())
            window = int(b.strip())
            if window == 1:
                lim_1s = limit
            elif window == 120:
                lim_120s = limit
        return lim_1s, lim_120s
    except Exception:
        return None, None


class RiotClient:
    def __init__(self, api_key: str | None = None):
        # ✅ env 로드 (프로필 기반)
        loaded_envs = _load_env_candidates()

        # 1) Prefer explicitly passed key
        if api_key:
            key = _clean_key(api_key)
            source = "constructor api_key"
        else:
            # 2) Prefer process env var
            raw_env = os.getenv("RIOT_API_KEY")
            if raw_env:
                key = _clean_key(raw_env)
                source = "process env RIOT_API_KEY"
            else:
                # 3) env files already loaded above
                key = _clean_key(os.getenv("RIOT_API_KEY"))
                source = f"dotenv candidates ({', '.join(loaded_envs) if loaded_envs else 'none'})"

        if not key:
            raise RuntimeError(
                "RIOT_API_KEY not found.\n"
                f"- Checked: constructor api_key, process env RIOT_API_KEY, and dotenv candidates\n"
                f"- Last source attempted: {source}\n"
                "Fix:\n"
                "  1) Put RIOT_API_KEY=RGAPI-... in .env.public or .env.personal (no quotes)\n"
                "  2) OR set it in your .bat: set \"RIOT_API_KEY=RGAPI-...\"\n"
            )

        self.api_key = key
        self.s = requests.Session()
        self.s.headers.update({"X-Riot-Token": self.api_key})

        # ---- rate stats ----
        self._req_ts_1s = deque()
        self._req_ts_120s = deque()
        self.total_req = 0
        self.n_429 = 0
        self.n_retry = 0
        self.sleep_sec_total = 0.0

        self.last_app_limit = None
        self.last_app_count = None
        self.last_method_limit = None
        self.last_method_count = None

        # ---- 기본 한도(개발 키 가정). 필요시 헤더로 자동 업데이트 됨 ----
        self.limit_1s = int(os.getenv("RIOT_LIMIT_1S", "20"))
        self.limit_120s = int(os.getenv("RIOT_LIMIT_120S", "100"))

        # ---- throttling knobs ----
        self.throttle_limit_1s = int(os.getenv("RIOT_THROTTLE_1S", str(max(1, self.limit_1s - 1))))
        self.throttle_limit_120s = int(os.getenv("RIOT_THROTTLE_120S", str(max(1, self.limit_120s - 5))))

        # ✅ pacing 옵션 (기본 OFF)
        # - 개인키 BAT에서 set RIOT_PACE_120S=1 로 켜서 사용
        self.pace_enabled = _truthy(os.getenv("RIOT_PACE_120S") or os.getenv("RIOT_PACE"))
        self._last_pace_ts = 0.0

        # ✅ 로그 옵션
        # - 네 요청: 429가 아닌 wait(자체 pacing/throttle)는 출력하지 않음
        self.log_429 = _truthy(os.getenv("RIOT_LOG_429") or "1")          # 기본 ON
        self.log_pace = _truthy(os.getenv("RIOT_LOG_PACE") or "0")        # 기본 OFF (원하면 켜기)

        self._sleep_quantum = 0.05
        self.timeout = float(os.getenv("RIOT_TIMEOUT", "15"))

        self.max_tries = int(os.getenv("RIOT_MAX_TRIES", "8"))
        self.base_backoff = float(os.getenv("RIOT_BASE_BACKOFF", "0.8"))
        self.max_backoff = float(os.getenv("RIOT_MAX_BACKOFF", "20"))
        self.retry_5xx = True

    def _note_request(self, r: requests.Response):
        now = time.time()
        self.total_req += 1

        self._req_ts_1s.append(now)
        self._req_ts_120s.append(now)

        while self._req_ts_1s and now - self._req_ts_1s[0] > 1.0:
            self._req_ts_1s.popleft()
        while self._req_ts_120s and now - self._req_ts_120s[0] > 120.0:
            self._req_ts_120s.popleft()

        self.last_app_limit = r.headers.get("X-App-Rate-Limit")
        self.last_app_count = r.headers.get("X-App-Rate-Limit-Count")
        self.last_method_limit = r.headers.get("X-Method-Rate-Limit")
        self.last_method_count = r.headers.get("X-Method-Rate-Limit-Count")

        lim_1s, lim_120s = _parse_app_rate_limit(self.last_app_limit)
        updated = False
        if lim_1s and lim_1s != self.limit_1s:
            self.limit_1s = lim_1s
            updated = True
        if lim_120s and lim_120s != self.limit_120s:
            self.limit_120s = lim_120s
            updated = True

        if updated:
            if os.getenv("RIOT_THROTTLE_1S") is None:
                self.throttle_limit_1s = max(1, self.limit_1s - 1)
            if os.getenv("RIOT_THROTTLE_120S") is None:
                self.throttle_limit_120s = max(1, self.limit_120s - 5)

    def rate_report(self) -> str:
        req_1s = len(self._req_ts_1s)
        req_120s = len(self._req_ts_120s)

        util_1s = (req_1s / float(self.limit_1s)) * 100.0 if self.limit_1s else 0.0
        util_120s = (req_120s / float(self.limit_120s)) * 100.0 if self.limit_120s else 0.0

        return (
            f"[RATE] req_1s={req_1s}/{self.limit_1s} ({util_1s:.0f}%) | "
            f"req_120s={req_120s}/{self.limit_120s} ({util_120s:.0f}%) | "
            f"total={self.total_req} | 429={self.n_429} | retry={self.n_retry} | sleep={self.sleep_sec_total:.1f}s | "
            f"hdr_app={self.last_app_count}/{self.last_app_limit} | "
            f"hdr_method={self.last_method_count}/{self.last_method_limit}"
        )

    def _pace_before_request(self):
        """
        일정 텀으로 "고르게" 요청(pacing).
        - interval = max(120/throttle_120s, 1/throttle_1s)
        - 기본적으로 pacing sleep 로그는 안 찍음(원하면 RIOT_LOG_PACE=1)
        """
        if not self.pace_enabled:
            return

        t120 = max(1, int(self.throttle_limit_120s or 1))
        t1 = max(1, int(self.throttle_limit_1s or 1))
        interval = max(120.0 / float(t120), 1.0 / float(t1))

        now = time.time()
        if self._last_pace_ts <= 0:
            self._last_pace_ts = now
            return

        next_ts = self._last_pace_ts + interval
        if now < next_ts:
            sleep_s = next_ts - now
            self.sleep_sec_total += sleep_s
            if self.log_pace:
                print(f"[RIOT_PACE] sleep {sleep_s:.2f}s (interval={interval:.2f}s, t1={t1}, t120={t120})", flush=True)
            time.sleep(sleep_s)

        self._last_pace_ts = time.time()

    def _throttle_before_request(self):
        # pacing 먼저
        self._pace_before_request()

        # 윈도우 기반 throttle(버스트 방지)
        while True:
            now = time.time()

            while self._req_ts_1s and now - self._req_ts_1s[0] > 1.0:
                self._req_ts_1s.popleft()
            while self._req_ts_120s and now - self._req_ts_120s[0] > 120.0:
                self._req_ts_120s.popleft()

            need_wait = 0.0

            if len(self._req_ts_1s) >= self.throttle_limit_1s and self._req_ts_1s:
                oldest = self._req_ts_1s[0]
                need_wait = max(need_wait, (oldest + 1.0) - now)

            if len(self._req_ts_120s) >= self.throttle_limit_120s and self._req_ts_120s:
                oldest = self._req_ts_120s[0]
                need_wait = max(need_wait, (oldest + 120.0) - now)

            if need_wait <= 0:
                return

            # 여기서도 로그는 기본 OFF (원하면 RIOT_LOG_PACE=1)
            sleep_s = min(need_wait, self._sleep_quantum)
            self.sleep_sec_total += sleep_s
            time.sleep(sleep_s)

    def _sleep_with_jitter(self, sec: float):
        sec = float(sec)
        sec = max(0.0, sec)
        sec *= (0.85 + 0.30 * random.random())
        sec = min(sec, self.max_backoff)
        if sec > 0:
            self.sleep_sec_total += sec
            time.sleep(sec)

    def get(self, host: str, path: str, params: dict | None = None):
        url = f"https://{host}{path}"

        last_text = None
        for attempt in range(1, self.max_tries + 1):
            self._throttle_before_request()

            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                self.n_retry += 1
                wait = min(self.max_backoff, self.base_backoff * (2 ** (attempt - 1)))
                self._sleep_with_jitter(wait)
                last_text = f"network error: {e}"
                continue

            self._note_request(r)

            if r.status_code == 200:
                return r.json()

            if r.status_code in (401, 403):
                raise RuntimeError(f"{r.status_code} Unauthorized/Forbidden: {r.text}")

            if r.status_code == 429:
                self.n_429 += 1
                self.n_retry += 1

                ra = _parse_retry_after(r.headers)
                if ra is None:
                    ra = min(self.max_backoff, self.base_backoff * (2 ** (attempt - 1)))

                sleep_s = max(1.0, float(ra))

                # ✅ 네 요청: 429일 때만 출력
                if self.log_429:
                    app = r.headers.get("X-App-Rate-Limit-Count")
                    app_lim = r.headers.get("X-App-Rate-Limit")
                    meth = r.headers.get("X-Method-Rate-Limit-Count")
                    meth_lim = r.headers.get("X-Method-Rate-Limit")
                    print(
                        f"[RIOT_429] retry-after sleep {sleep_s:.2f}s (attempt {attempt}/{self.max_tries}) "
                        f"app={app}/{app_lim} method={meth}/{meth_lim}",
                        flush=True,
                    )

                self._sleep_with_jitter(sleep_s)
                last_text = r.text
                continue

            if self.retry_5xx and r.status_code in (500, 502, 503, 504):
                self.n_retry += 1
                wait = min(self.max_backoff, self.base_backoff * (2 ** (attempt - 1)))
                self._sleep_with_jitter(wait)
                last_text = r.text
                continue

            r.raise_for_status()
            return r.json()

        raise RuntimeError(f"Riot API request failed after retries: {url} / last={last_text}")

    # account-v1
    def account_by_riot_id(self, game_name: str, tag_line: str):
        g = quote(game_name, safe="")
        t = quote(tag_line, safe="")
        path = f"/riot/account/v1/accounts/by-riot-id/{g}/{t}"
        return self.get(ASIA_HOST, path)

    # match-v5
    def match_ids(self, puuid: str, count: int = 20, start_time: int | None = None):
        path = f"/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"count": int(count)}
        if start_time:
            params["startTime"] = int(start_time)
        return self.get(ASIA_HOST, path, params=params)

    def match(self, match_id: str):
        path = f"/lol/match/v5/matches/{match_id}"
        return self.get(ASIA_HOST, path)

    # summoner-v4
    def summoner_by_puuid(self, puuid: str):
        path = f"/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return self.get(KR_HOST, path)

    def summoner_by_name(self, name: str):
        path = f"/lol/summoner/v4/summoners/by-name/{name}"
        return self.get(KR_HOST, path)

    # league-v4
    def league_entries_by_summoner(self, summoner_id: str):
        path = f"/lol/league/v4/entries/by-summoner/{summoner_id}"
        return self.get(KR_HOST, path)
