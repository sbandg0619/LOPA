# app.py
# ============================================================
# LOPA (LoL Pick AI)
# - 추천: 로컬브릿지(LOPA Bridge) 우선 사용
# - 브릿지 미사용 시: 로컬 LCUClient(lcu_client.py)로 fallback(개인용)
# - legal/*.md 문서를 UI에서 바로 접근 가능하게 노출
#
# 환경변수(선택):
#   APP_PROFILE              personal / public
#   DB_PATH                  기본 DB 경로 (미설정 시 profile별 기본값)
#   LOPA_BRIDGE_URL          브릿지 URL (기본: http://127.0.0.1:12145)
#   LOPA_BRIDGE_TOKEN        브릿지 토큰
#   LOPA_BRIDGE_TIMEOUT      브릿지 요청 타임아웃 (기본: 2.0)
#
# NOTE (중요):
# - "외부 서버에 호스팅된 Streamlit"은 사용자 PC의 127.0.0.1 브릿지에 접근할 수 없음.
#   공개 배포를 웹으로 하려면 "브라우저(프론트)가 로컬 브릿지를 직접 호출"하는 구조가 필요.
#   (현재 앱은 로컬 실행 데모/배포에 최적화)
# ============================================================

from __future__ import annotations

import os
import time
import json
import hashlib
import sqlite3
import difflib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

from dotenv import load_dotenv

from champ_pool_store import load_pool, save_pool, ROLES, get_pool_for_role
from champion_catalog import load_champions_ko
from recommender import (
    recommend_champions,
    get_latest_patch,
    get_available_patches,
    champ_role_distribution,
    guess_enemy_roles,
)

# 로컬 LCU fallback (개인용에서만 의미 있음)
try:
    from lcu_client import LCUClient
except Exception:
    LCUClient = None


# -------------------------
# .env loader (profile aware)
# -------------------------
def _load_env_candidates() -> List[str]:
    """
    우선순위:
      1) .env.<APP_PROFILE>
      2) .env.personal
      3) .env.public
      4) .env
    """
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
            load_dotenv(dotenv_path=p, override=False)  # 먼저 로드된 값 우선
            loaded.append(str(p))
    return loaded


_LOADED_ENVS = _load_env_candidates()


# -------------------------
# Service constants
# -------------------------
SERVICE_NAME = "LOPA (로파)"
CONTACT_EMAIL = "sbandg0619@gmail.com"
DELETION_TEXT = "“계정/데이터 삭제를 원하면 아래 이메일로 Riot ID(Name#TAG)와 함께 요청하세요.”"
SUPPORT_TEXT = "후원은 서버 유지 및 개발에 큰 도움이 됩니다. 감사합니다."

ROLE_KO = {"TOP": "탑", "JUNGLE": "정글", "MIDDLE": "미드", "BOTTOM": "원딜", "UTILITY": "서폿"}

PROFILE = (os.getenv("APP_PROFILE") or "personal").strip().lower()
DEFAULT_DB_BY_PROFILE = "lol_graph_public.db" if PROFILE == "public" else "lol_graph_personal.db"
DB_PATH_DEFAULT = os.getenv("DB_PATH") or DEFAULT_DB_BY_PROFILE

LCU_POS_TO_ROLE = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "middle": "MIDDLE",
    "mid": "MIDDLE",
    "bottom": "BOTTOM",
    "bot": "BOTTOM",
    "utility": "UTILITY",
    "support": "UTILITY",
    "sup": "UTILITY",
}


# -------------------------
# Helpers: names
# -------------------------
def norm(s: str) -> str:
    s = (s or "").strip().lower()
    for ch in [" ", ".", "'", "’", "-", "_", "·"]:
        s = s.replace(ch, "")
    return s


def make_name_resolver(all_names):
    norm_to_official = {norm(nm): nm for nm in all_names}
    official_norms = list(norm_to_official.keys())

    def resolve(user_text: str):
        q = (user_text or "").strip()
        if not q:
            return (None, [])
        if q in all_names:
            return (q, [])
        nq = norm(q)
        if nq in norm_to_official:
            return (norm_to_official[nq], [])
        close = difflib.get_close_matches(nq, official_norms, n=5, cutoff=0.80)
        if close:
            best = close[0]
            score = difflib.SequenceMatcher(None, nq, best).ratio()
            if score >= 0.90:
                return (norm_to_official[best], [])
            return (None, [norm_to_official[c] for c in close])
        return (None, [])

    return resolve


def champ_badge(cid, id_to_name):
    return f"{id_to_name.get(cid, 'UNKNOWN')} ({cid})"


def remove_item(lst, x):
    if x in lst:
        lst.remove(x)


def render_chips_readonly(title, ids, id_to_name):
    st.markdown(f"**{title} ({len(ids)})**")
    if not ids:
        st.caption("(비어있음)")
        return
    cols = st.columns(5)
    for i, cid in enumerate(ids):
        with cols[i % 5]:
            st.button(id_to_name.get(cid, "UNKNOWN"), key=f"ro_{title}_{cid}_{i}", disabled=True)


def render_chips_editable(title, ids, id_to_name, key_prefix):
    st.markdown(f"**{title} ({len(ids)})**")
    if not ids:
        st.caption("(비어있음)")
        return
    cols = st.columns(5)
    for i, cid in enumerate(ids):
        with cols[i % 5]:
            st.button(id_to_name.get(cid, "UNKNOWN"), key=f"{key_prefix}_chip_{cid}_{i}", disabled=True)
            if st.button("삭제", key=f"{key_prefix}_rm_{cid}_{i}"):
                remove_item(ids, cid)
                st.rerun()


# -------------------------
# Bridge client (LOPA Bridge)
# -------------------------
class BridgeClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 2.0):
        self.base_url = (base_url or "").rstrip("/")
        self.token = (token or "").strip()
        self.timeout = float(timeout)

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["X-LOPA-TOKEN"] = self.token
        return h

    def health(self) -> Tuple[bool, str, Optional[dict]]:
        try:
            r = requests.get(f"{self.base_url}/health", headers=self._headers(), timeout=self.timeout)
            if r.status_code == 401:
                return False, "브릿지 토큰이 틀립니다(401). LOPA_BRIDGE_TOKEN 확인.", {"status": 401, "text": r.text}
            if r.status_code >= 400:
                return False, f"브릿지 HTTP {r.status_code}", {"status": r.status_code, "text": r.text}
            j = r.json()
            return bool(j.get("ok")), str(j.get("msg")), j
        except requests.exceptions.ConnectTimeout:
            return False, "브릿지 연결 타임아웃(ConnectTimeout). 브릿지 실행/포트 확인.", None
        except requests.exceptions.ConnectionError:
            return False, "브릿지 연결 실패(ConnectionError). 브릿지 실행/포트 확인.", None
        except Exception as e:
            return False, str(e), None

    def state(self) -> Tuple[bool, Optional[dict], str]:
        try:
            r = requests.get(f"{self.base_url}/state", headers=self._headers(), timeout=self.timeout)
            if r.status_code == 401:
                return False, None, "브릿지 토큰이 틀립니다(401). LOPA_BRIDGE_TOKEN 확인."
            if r.status_code >= 400:
                return False, None, f"브릿지 HTTP {r.status_code}: {r.text[:200]}"
            j = r.json()
            stt = j.get("state") if isinstance(j, dict) else None
            return True, stt, ""
        except requests.exceptions.ConnectTimeout:
            return False, None, "브릿지 연결 타임아웃(ConnectTimeout)."
        except requests.exceptions.ConnectionError:
            return False, None, "브릿지 연결 실패(ConnectionError)."
        except Exception as e:
            return False, None, str(e)


def _bridge_env() -> Tuple[str, str, float]:
    url = (os.getenv("LOPA_BRIDGE_URL") or "http://127.0.0.1:12145").strip()
    token = (os.getenv("LOPA_BRIDGE_TOKEN") or "").strip()
    timeout = float(os.getenv("LOPA_BRIDGE_TIMEOUT") or "2.0")
    return url, token, timeout


# -------------------------
# Session state
# -------------------------
def _ensure_rec_state():
    if "rec_bans" not in st.session_state:
        st.session_state["rec_bans"] = []
    if "rec_enemy" not in st.session_state:
        st.session_state["rec_enemy"] = []
    if "rec_ally_by_role" not in st.session_state:
        st.session_state["rec_ally_by_role"] = {r: [] for r in ROLES}
    if "rec_cached_recs" not in st.session_state:
        st.session_state["rec_cached_recs"] = []
    if "rec_last_digest" not in st.session_state:
        st.session_state["rec_last_digest"] = None
    if "rec_stop_autorun" not in st.session_state:
        st.session_state["rec_stop_autorun"] = False


def _lcu_to_inputs(lcu_state: dict):
    """LCU/Bridge state -> (bans, ally_by_role, enemy, inferred_my_role)"""
    bans = []
    my_bans = (lcu_state.get("bans", {}) or {}).get("myTeamBans", []) or []
    their_bans = (lcu_state.get("bans", {}) or {}).get("theirTeamBans", []) or []
    for x in list(my_bans) + list(their_bans):
        try:
            xi = int(x)
        except Exception:
            continue
        if xi and xi not in bans:
            bans.append(xi)

    ally_by_role = {r: [] for r in ROLES}
    for p in (lcu_state.get("myTeam") or []):
        cid = int(p.get("championId") or 0)
        if cid == 0:
            continue
        pos = (p.get("assignedPosition") or "").strip().lower()
        role = LCU_POS_TO_ROLE.get(pos)
        if role in ROLES and cid not in ally_by_role[role]:
            ally_by_role[role].append(cid)

    enemy = []
    for p in (lcu_state.get("theirTeam") or []):
        cid = int(p.get("championId") or 0)
        if cid and cid not in enemy:
            enemy.append(cid)

    inferred_my_role = None
    local_cell = lcu_state.get("localPlayerCellId")
    if local_cell is not None:
        for p in (lcu_state.get("myTeam") or []):
            if p.get("cellId") == local_cell:
                pos = (p.get("assignedPosition") or "").strip().lower()
                inferred_my_role = LCU_POS_TO_ROLE.get(pos)
                break

    return bans, ally_by_role, enemy, inferred_my_role


def _make_digest(patch, tier, my_role, champ_pool, bans, ally_by_role, enemy, min_games, top_n):
    payload = {
        "patch": patch,
        "tier": tier,
        "my_role": my_role,
        "champ_pool": sorted([int(x) for x in champ_pool]),
        "bans": sorted([int(x) for x in bans]),
        "ally": {r: sorted([int(x) for x in ally_by_role.get(r, [])]) for r in ROLES},
        "enemy": sorted([int(x) for x in enemy]),
        "min_games": int(min_games),
        "top_n": int(top_n),
    }
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _is_local_pick_completed(lcu_state: dict) -> bool:
    if not lcu_state or lcu_state.get("phase") != "ChampSelect":
        return False

    local_cell = lcu_state.get("localPlayerCellId")
    actions = lcu_state.get("actionsRaw")

    if local_cell is not None and actions:
        try:
            for group in actions or []:
                for a in group or []:
                    if a.get("type") == "pick" and a.get("actorCellId") == local_cell:
                        if a.get("completed") is True:
                            return True
        except Exception:
            pass

    if local_cell is not None:
        for p in (lcu_state.get("myTeam") or []):
            if p.get("cellId") == local_cell:
                cid = int(p.get("championId") or 0)
                return cid != 0

    return False


# -------------------------
# Pages
# -------------------------
def page_champ_pool(id_to_name, name_to_id, all_names, resolve_name):
    st.subheader("라인별 챔피언 폭 관리")
    pool = load_pool()

    role = st.selectbox(
        "라인 선택",
        ROLES,
        format_func=lambda r: f"{ROLE_KO.get(r, r)} ({r})",
        key="pool_role",
    )

    def add_official(official_name: str):
        cid = int(name_to_id[official_name])
        if cid not in pool[role]:
            pool[role].append(cid)
            save_pool(pool)

    st.caption("빠른 추가 입력칸에서 엔터를 누르면 추가됩니다. (오타는 후보 선택으로 처리)")

    with st.form("pool_quick_add_form", clear_on_submit=True):
        user_text = st.text_input("빠른 추가: 챔피언 이름 입력 후 엔터", key="pool_quick_name")
        ok = st.form_submit_button("추가(엔터)")
        if ok:
            official, cands = resolve_name(user_text)
            if official:
                add_official(official)
                st.rerun()
            elif cands:
                st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
                st.session_state["pool_cands"] = cands
            else:
                st.error("챔피언을 찾지 못했어요.")

    if st.session_state.get("pool_cands"):
        pick = st.selectbox("후보 선택", st.session_state["pool_cands"], key="pool_cand_pick")
        if st.button("이 후보로 추가", key="pool_cand_add", use_container_width=True):
            add_official(pick)
            st.session_state["pool_cands"] = None
            st.rerun()

    st.divider()

    with st.form("pool_select_add_form"):
        selected = st.selectbox("목록에서 선택", all_names, key="pool_selectbox")
        ok2 = st.form_submit_button("추가")
        if ok2:
            add_official(selected)
            st.rerun()

    st.divider()
    st.subheader("삭제")

    if pool[role]:
        options = pool[role][:]
        to_del = st.multiselect(
            "삭제할 챔피언 선택",
            options,
            format_func=lambda cid: champ_badge(cid, id_to_name),
            key="pool_del_multi",
        )
        if st.button("선택 삭제", key="pool_del_btn", use_container_width=True):
            if to_del:
                pool[role] = [x for x in pool[role] if x not in set(to_del)]
                save_pool(pool)
                st.success(f"{len(to_del)}개 삭제 완료")
                st.rerun()
    else:
        st.info("이 라인에는 저장된 챔피언이 없습니다.")

    st.subheader("현재 라인 챔프폭")
    st.write(f"**{ROLE_KO[role]} ({role})**: {len(pool[role])}개")
    st.code(", ".join(champ_badge(cid, id_to_name) for cid in pool[role]) if pool[role] else "(비어있음)")

    with st.expander("전체 라인 요약"):
        for r in ROLES:
            st.write(f"**{ROLE_KO[r]} ({r})**: {len(pool[r])}개")
            st.write(", ".join(champ_badge(cid, id_to_name) for cid in pool[r]) if pool[r] else "(비어있음)")


def _open_db_for_patch_list(db_path: str):
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def page_recommend(id_to_name, name_to_id, all_names, resolve_name):
    st.subheader("픽 추천 (자동 입력: 브릿지/LCU + 자동 업데이트)")
    _ensure_rec_state()

    # --- 설정 ---
    db_path = st.text_input("DB 파일 경로", value=DB_PATH_DEFAULT, key="rec_db_path")
    if not os.path.exists(db_path):
        st.error("DB 파일이 없습니다. 경로를 확인하세요.")
        return

    try:
        con = _open_db_for_patch_list(db_path)
        latest_patch = get_latest_patch(con)
        patches = get_available_patches(con)
    except Exception:
        st.error("DB를 열 수 없습니다. 파일이 손상되었거나 경로가 잘못됐습니다.")
        return

    if not latest_patch:
        st.warning("DB에 matches가 아직 없습니다. 수집이 더 진행되어야 추천이 가능합니다.")
        return

    patch_options = ["ALL"] + patches

    def patch_label(p: str) -> str:
        return "전체(ALL)" if p == "ALL" else p

    default_idx = patch_options.index(latest_patch) if latest_patch in patch_options else 0
    patch = st.selectbox("패치 선택", patch_options, index=default_idx, format_func=patch_label, key="rec_patch")

    tier = st.selectbox(
        "티어(테스트용)",
        ["ALL", "EMERALD", "DIAMOND", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON", "UNRANKED"],
        index=1,
        key="rec_tier",
    )

    auto_source = st.radio("자동 입력 소스", ["브릿지(권장)", "로컬 LCU(fallback)", "수동"], index=0, horizontal=True)
    show_detail = st.checkbox("상세 지표 표시(기본/하한/카운터/시너지/표본)", value=True, key="rec_show_detail")

    my_role = st.selectbox(
        "내 라인",
        ROLES,
        format_func=lambda r: f"{ROLE_KO.get(r, r)} ({r})",
        key="rec_my_role",
    )

    min_games = st.slider("최소 표본수(games) 필터", min_value=1, max_value=200, value=30, step=5, key="rec_min_games")
    top_n = st.slider("추천 개수", min_value=3, max_value=20, value=10, step=1, key="rec_top_n")

    champ_pool = [c for c in get_pool_for_role(my_role) if isinstance(c, int)]
    st.markdown("**내 챔프폭**")
    st.write(", ".join(champ_badge(cid, id_to_name) for cid in champ_pool) if champ_pool else "(비어있음)")

    if not champ_pool:
        st.warning("내 라인 챔프폭이 비어있습니다. 먼저 챔프폭 관리에서 챔피언을 저장하세요.")
        return

    # --- 자동 소스 상태 ---
    state = None
    phase = "Unknown"
    ok_conn = False
    err_msg = None

    if auto_source == "브릿지(권장)":
        url, token, tout = _bridge_env()
        bc = BridgeClient(url, token=token, timeout=tout)
        ok_conn, msg, _raw = bc.health()
        if ok_conn:
            ok2, state, err = bc.state()
            if ok2 and isinstance(state, dict):
                phase = (state or {}).get("phase") or "Unknown"
            else:
                err_msg = err or "브릿지 state 읽기 실패"
        else:
            err_msg = msg
            ok2, state, err = bc.state()
            if ok2 and isinstance(state, dict):
                phase = (state or {}).get("phase") or "Unknown"

    elif auto_source == "로컬 LCU(fallback)":
        if PROFILE == "public":
            err_msg = "public 모드에서는 로컬 LCU fallback을 권장하지 않습니다(브릿지 사용 권장)."
        elif LCUClient is None:
            err_msg = "LCUClient import 실패 (lcu_client.py 확인)"
        else:
            try:
                lcu = LCUClient.from_env_or_guess(timeout=2.0)
                ok_conn, msg = lcu.ping()
                if ok_conn:
                    state = lcu.get_champ_select_state()
                    phase = (state or {}).get("phase") or "Unknown"
                else:
                    err_msg = f"LCU ping 실패: {msg}"
            except Exception as e:
                err_msg = str(e)

    # --- 상태 표시 ---
    colA, colB, colC = st.columns(3)
    with colA:
        st.metric("자동 연결", "OK" if ok_conn else "FAIL")
    with colB:
        st.metric("Phase", phase)
    with colC:
        st.metric("UI 갱신시각", f"{time.time():.1f}")

    if err_msg and auto_source != "수동":
        st.warning(f"자동 입력 경고: {err_msg}")

    # --- 입력 적용 ---
    waiting = False

    if auto_source != "수동":
        if state and isinstance(state, dict) and phase == "ChampSelect":
            bans, ally_by_role, enemy, inferred_role = _lcu_to_inputs(state)
            st.session_state["rec_bans"] = bans
            st.session_state["rec_ally_by_role"] = ally_by_role
            st.session_state["rec_enemy"] = enemy

            if inferred_role in ROLES and st.session_state.get("rec_my_role") != inferred_role:
                st.session_state["rec_my_role"] = inferred_role
                st.rerun()

            if _is_local_pick_completed(state):
                st.session_state["rec_stop_autorun"] = True
        else:
            waiting = True

    # --- 현재 상황 표시 ---
    st.divider()
    st.subheader("현재 밴/픽 상황")

    if auto_source != "수동":
        if waiting:
            st.info("아직 ChampSelect가 아닙니다. 챔프 선택창에 들어가면 자동으로 반영됩니다.")
        render_chips_readonly("밴 목록", st.session_state["rec_bans"], id_to_name)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 아군 픽(라인별)")
            for r in ROLES:
                render_chips_readonly(f"{ROLE_KO[r]}({r})", st.session_state["rec_ally_by_role"].get(r, []), id_to_name)
        with c2:
            st.markdown("### 적군 픽")
            render_chips_readonly("적군", st.session_state["rec_enemy"], id_to_name)

        if st.session_state.get("rec_stop_autorun"):
            st.warning("내 픽이 확정된 것으로 감지되어 자동 갱신/추천을 멈췄습니다.")
            if st.button("자동 갱신 다시 시작", use_container_width=True, key="rec_resume_autorun"):
                st.session_state["rec_stop_autorun"] = False
                st.rerun()

    else:
        st.caption("수동 모드에서는 밴/픽을 직접 입력합니다.")
        bans = st.session_state["rec_bans"]
        enemy = st.session_state["rec_enemy"]
        ally_by_role = st.session_state["rec_ally_by_role"]

        st.markdown("### 밴")
        with st.form("rec_ban_form", clear_on_submit=True):
            ban_text = st.text_input("밴할 챔피언 이름 입력 후 엔터", key="rec_ban_text")
            ok = st.form_submit_button("추가(엔터)")
            if ok:
                official, cands = resolve_name(ban_text)
                if official:
                    cid = int(name_to_id[official])
                    if cid not in bans:
                        bans.append(cid)
                    st.rerun()
                elif cands:
                    st.session_state["rec_ban_cands"] = cands
                    st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
                else:
                    st.error("챔피언을 찾지 못했어요.")

        if st.session_state.get("rec_ban_cands"):
            pick = st.selectbox("밴 후보 선택", st.session_state["rec_ban_cands"], key="rec_ban_pick")
            if st.button("이 후보를 밴에 추가", key="rec_ban_pick_btn", use_container_width=True):
                cid = int(name_to_id[pick])
                if cid not in bans:
                    bans.append(cid)
                st.session_state["rec_ban_cands"] = None
                st.rerun()

        render_chips_editable("밴 목록", bans, id_to_name, "rec_ban")

        st.divider()
        st.markdown("### 아군 픽(라인별)")
        ally_tabs = st.tabs([f"{ROLE_KO[r]}({r})" for r in ROLES])
        for idx, r in enumerate(ROLES):
            with ally_tabs[idx]:
                with st.form(f"rec_ally_form_{r}", clear_on_submit=True):
                    t = st.text_input(f"{ROLE_KO[r]} 챔피언 입력 후 엔터", key=f"rec_ally_text_{r}")
                    ok2 = st.form_submit_button("추가(엔터)")
                    if ok2:
                        official, cands = resolve_name(t)
                        if official:
                            cid = int(name_to_id[official])
                            if cid not in ally_by_role[r]:
                                ally_by_role[r].append(cid)
                            st.rerun()
                        elif cands:
                            st.session_state[f"rec_ally_cands_{r}"] = cands
                            st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
                        else:
                            st.error("챔피언을 찾지 못했어요.")

                if st.session_state.get(f"rec_ally_cands_{r}"):
                    pick = st.selectbox("후보 선택", st.session_state[f"rec_ally_cands_{r}"], key=f"rec_ally_pick_{r}")
                    if st.button("이 후보로 추가", key=f"rec_ally_pick_btn_{r}", use_container_width=True):
                        cid = int(name_to_id[pick])
                        if cid not in ally_by_role[r]:
                            ally_by_role[r].append(cid)
                        st.session_state[f"rec_ally_cands_{r}"] = None
                        st.rerun()

                render_chips_editable(f"{ROLE_KO[r]} 아군 픽", ally_by_role[r], id_to_name, f"rec_ally_{r}")

        st.divider()
        st.markdown("### 적군 픽(라인 미정)")
        with st.form("rec_enemy_form", clear_on_submit=True):
            enemy_text = st.text_input("적 챔피언 입력 후 엔터", key="rec_enemy_text")
            ok3 = st.form_submit_button("추가(엔터)")
            if ok3:
                official, cands = resolve_name(enemy_text)
                if official:
                    cid = int(name_to_id[official])
                    if cid not in enemy:
                        enemy.append(cid)
                    st.rerun()
                elif cands:
                    st.session_state["rec_enemy_cands"] = cands
                    st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
                else:
                    st.error("챔피언을 찾지 못했어요.")

        if st.session_state.get("rec_enemy_cands"):
            pick = st.selectbox("적 후보 선택", st.session_state["rec_enemy_cands"], key="rec_enemy_pick")
            if st.button("이 후보를 적군에 추가", key="rec_enemy_pick_btn", use_container_width=True):
                cid = int(name_to_id[pick])
                if cid not in enemy:
                    enemy.append(cid)
                st.session_state["rec_enemy_cands"] = None
                st.rerun()

        render_chips_editable("적군 픽", enemy, id_to_name, "rec_enemy")

    # --- 추천 ---
    st.divider()
    st.subheader("추천 결과 (자동 업데이트)")

    if auto_source != "수동" and waiting:
        st.caption("대기 중… (ChampSelect 진입 시 자동으로 추천을 계산합니다.)")
    else:
        digest = _make_digest(
            patch=patch,
            tier=tier,
            my_role=st.session_state["rec_my_role"],
            champ_pool=champ_pool,
            bans=st.session_state["rec_bans"],
            ally_by_role=st.session_state["rec_ally_by_role"],
            enemy=st.session_state["rec_enemy"],
            min_games=min_games,
            top_n=top_n,
        )

        should_recalc = (digest != st.session_state["rec_last_digest"]) and (not st.session_state.get("rec_stop_autorun"))

        if should_recalc:
            recs = recommend_champions(
                db_path=db_path,
                patch=patch,
                tier=tier,
                my_role=st.session_state["rec_my_role"],
                champ_pool=champ_pool,
                bans=st.session_state["rec_bans"],
                ally_picks_by_role=st.session_state["rec_ally_by_role"],
                enemy_picks=st.session_state["rec_enemy"],
                min_games=min_games,
                top_n=top_n,
            )
            st.session_state["rec_cached_recs"] = recs
            st.session_state["rec_last_digest"] = digest

        recs = st.session_state.get("rec_cached_recs") or []
        if not recs:
            st.warning("추천할 데이터가 부족합니다. (표본수 필터가 높거나 DB가 아직 작을 수 있음)")
        else:
            try:
                dist = champ_role_distribution(con, patch, tier)
                guessed = guess_enemy_roles(st.session_state["rec_enemy"], dist)
                if st.session_state["rec_enemy"]:
                    with st.expander("적 챔프 라인 추정(간단)"):
                        for cid in st.session_state["rec_enemy"]:
                            st.write(f"- {id_to_name.get(cid,'UNKNOWN')} → {guessed.get(cid,'UNKNOWN')}")
            except Exception:
                pass

            for r in recs:
                cid = r["champ_id"]
                name = id_to_name.get(cid, "UNKNOWN")
                if show_detail:
                    st.write(
                        f"**{name}** — 최종 {r['final_score']}% | "
                        f"기본 {r['base_wr']}% | 하한 {r['base_lb']}% | "
                        f"카운터 {r['counter_delta']} (표본 {r['counter_samples']}) | "
                        f"시너지 {r['synergy_delta']} (표본 {r['synergy_samples']}) | "
                        f"기본표본 {r['games']}판"
                    )
                else:
                    st.write(f"**{name}** — 최종 {r['final_score']}% | 표본 {r['games']}판")

    # --- 자동 rerun ---
    if auto_source != "수동" and (not st.session_state.get("rec_stop_autorun")):
        sec = 1.0
        if phase == "ChampSelect":
            sec = 0.6
        time.sleep(sec)
        st.rerun()


def page_bridge_guide():
    st.subheader("로컬브릿지(LOPA Bridge) 안내")
    st.markdown(
        """
브릿지는 **사용자 PC에서 LoL 클라이언트(LCU)를 읽어** 자동 입력을 제공하는 방식입니다.  
서버가 lockfile에 접근하는 구조가 아니라서 **공개 서비스에서 안전하고 현실적인 방법**입니다.
"""
    )

    url, token, tout = _bridge_env()
    st.markdown("### 현재 설정(환경변수)")
    st.code(
        "\n".join(
            [
                f"APP_PROFILE={PROFILE}",
                f"DB_PATH={DB_PATH_DEFAULT}",
                f"LOPA_BRIDGE_URL={url}",
                f"LOPA_BRIDGE_TOKEN={'(설정됨)' if token else '(비어있음)'}",
                f"LOPA_BRIDGE_TIMEOUT={tout}",
            ]
        )
    )

    with st.expander("사용 방법(개인 PC)"):
        st.markdown(
            """
1) LoL 클라이언트 실행  
2) 프로젝트 폴더에서 브릿지 실행  
   - CMD: `python lopa_bridge.py`  
3) 브릿지 콘솔에 출력되는 `token` 확인  
4) `.env.personal` 또는 `.env.public`에 `LOPA_BRIDGE_TOKEN` 추가  
5) 추천 페이지에서 자동 입력 소스를 **브릿지(권장)** 으로 선택
"""
        )

    st.info(
        "자동 입력을 쓰려면, 각 사용자 PC에서 브릿지를 실행해야 합니다. "
        "브릿지를 안 켠 사용자는 수동 입력만 가능합니다."
    )

    with st.expander("디버그: 로드된 env 파일"):
        st.code("\n".join(_LOADED_ENVS) if _LOADED_ENVS else "(none)")


def _read_legal_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return f"(문서를 읽지 못했습니다: {e})"


def page_legal():
    st.subheader("약관 / 개인정보 / 삭제요청 / 문의")

    base = Path(__file__).resolve().parent / "legal"
    if not base.exists():
        st.error("legal 폴더가 없습니다. 프로젝트 루트에 legal 폴더를 만들어주세요.")
        return

    docs = {
        "개인정보 처리방침 (KO)": base / "privacy_ko.md",
        "이용약관 (KO)": base / "terms_ko.md",
        "데이터 삭제 정책 (KO)": base / "deletion_ko.md",
        "고지/면책 (KO)": base / "disclaimer_ko.md",
        "문의/지원 (KO)": base / "contact_ko.md",
        "Privacy Policy (EN)": base / "privacy_en.md",
        "Terms (EN)": base / "terms_en.md",
        "Deletion Policy (EN)": base / "deletion_en.md",
        "Disclaimer (EN)": base / "disclaimer_en.md",
        "Contact (EN)": base / "contact_en.md",
    }

    keys = list(docs.keys())
    pick = st.selectbox("문서 선택", keys, index=0)
    p = docs[pick]

    if not p.exists():
        st.warning(f"파일이 없습니다: {p.name}")
        return

    st.markdown(_read_legal_file(p))


# -------------------------
# MAIN
# -------------------------
st.set_page_config(page_title="LOPA", layout="wide")

st.title(f"{SERVICE_NAME}")

try:
    champs = load_champions_ko()
    id_to_name = {int(k): v for k, v in champs["id_to_name"].items()}
    name_to_id = champs["name_to_id"]
    all_names = champs["all_names"]
    resolve_name = make_name_resolver(all_names)
    st.caption(f"챔피언 데이터: Data Dragon {champs['version']} (ko_KR)")
except Exception:
    st.error("챔피언 목록을 불러오지 못했습니다. 인터넷/방화벽을 확인하세요.")
    st.stop()

with st.sidebar:
    st.markdown("## 메뉴")
    page = st.radio(
        "이동",
        ["픽 추천(자동)", "챔프폭 관리", "브릿지 안내", "약관/개인정보"],
        index=0,
        key="nav_page",
    )

    st.divider()
    st.markdown("### 프로필")
    st.write(f"APP_PROFILE={PROFILE}")
    st.markdown("### 문의")
    st.write(CONTACT_EMAIL)
    st.markdown("### 삭제 요청")
    st.caption(DELETION_TEXT)
    st.markdown("### 후원")
    st.caption(SUPPORT_TEXT)

    st.divider()
    st.caption("LOPA(로파)는 Riot Games와 무관한 비공식 팬메이드 도구입니다.")

if page == "챔프폭 관리":
    page_champ_pool(id_to_name, name_to_id, all_names, resolve_name)
elif page == "브릿지 안내":
    page_bridge_guide()
elif page == "약관/개인정보":
    page_legal()
else:
    page_recommend(id_to_name, name_to_id, all_names, resolve_name)
