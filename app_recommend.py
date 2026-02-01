import streamlit as st
import sqlite3
import difflib

from champ_pool_store import get_pool_for_role, ROLES
from champion_catalog import load_champions_ko
from recommender import recommend_champions, get_latest_patch, get_available_patches, champ_role_distribution, guess_enemy_roles

ROLE_KO = {"TOP":"탑", "JUNGLE":"정글", "MIDDLE":"미드", "BOTTOM":"원딜", "UTILITY":"서폿"}
DB_PATH_DEFAULT = "lol_graph.db"

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    for ch in [" ", ".", "'", "’", "-", "_", "·"]:
        s = s.replace(ch, "")
    return s

def make_name_resolver(all_names):
    norm_to_official = {norm(nm): nm for nm in all_names}
    official_norms = list(norm_to_official.keys())

    def resolve(user_text: str):
        """
        return (official_name or None, candidates_list)
        - 정확히 찾으면 (official, [])
        - 애매하면 (None, 후보리스트)
        """
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
            # 유사도 높으면 자동 선택
            best = close[0]
            score = difflib.SequenceMatcher(None, nq, best).ratio()
            if score >= 0.90:
                return (norm_to_official[best], [])
            # 아니면 후보 제시
            return (None, [norm_to_official[c] for c in close])
        return (None, [])

    return resolve

def add_champ_by_name(state_list, official_name, name_to_id):
    cid = int(name_to_id[official_name])
    if cid not in state_list:
        state_list.append(cid)

def remove_champ(state_list, cid):
    if cid in state_list:
        state_list.remove(cid)

def champ_tag(cid, id_to_name):
    return f"{id_to_name.get(cid,'UNKNOWN')}"

def champ_badge(cid, id_to_name):
    return f"{id_to_name.get(cid,'UNKNOWN')} ({cid})"

def render_chips(title, ids, id_to_name, key_prefix):
    st.markdown(f"**{title} ({len(ids)})**")
    if not ids:
        st.caption("(비어있음)")
        return
    cols = st.columns(5)
    for i, cid in enumerate(ids):
        with cols[i % 5]:
            st.button(champ_tag(cid, id_to_name), key=f"{key_prefix}_chip_{cid}", disabled=True)
            if st.button("삭제", key=f"{key_prefix}_rm_{cid}"):
                remove_champ(ids, cid)
                st.rerun()

st.set_page_config(page_title="LoL 픽 추천", layout="centered")
st.title("솔로랭크 픽 추천 (한글 입력 + 엔터 추가)")

# 챔피언 목록
champs = load_champions_ko()
id_to_name = {int(k): v for k, v in champs["id_to_name"].items()}
name_to_id = champs["name_to_id"]
all_names = champs["all_names"]
resolve_name = make_name_resolver(all_names)

st.caption("입력은 한글/영문 챔피언 이름, 저장/계산은 내부적으로 championId로 처리됩니다.")

# DB 경로 & 연결
db_path = st.text_input("DB 파일 경로", value=DB_PATH_DEFAULT)
try:
    con = sqlite3.connect(db_path, check_same_thread=False)
    latest_patch = get_latest_patch(con)
    patches = get_available_patches(con)
except Exception:
    st.error("DB를 열 수 없습니다. db_path가 맞는지 확인하세요. (기본: lol_graph.db)")
    st.stop()

if not latest_patch:
    st.warning("DB에 matches가 아직 없습니다. 수집이 좀 더 진행되어야 추천이 가능합니다.")
    st.stop()

patch = st.selectbox("패치 선택", patches, index=patches.index(latest_patch) if latest_patch in patches else 0)

# 테스트용 tier
tier = st.selectbox("티어(테스트용)", ["EMERALD", "DIAMOND", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON", "UNRANKED"], index=0)

my_role = st.selectbox("내 라인", ROLES, format_func=lambda r: f"{ROLE_KO.get(r,r)} ({r})")

# 내 챔프폭
champ_pool = [c for c in get_pool_for_role(my_role) if isinstance(c, int)]
st.subheader("내 챔프폭")
st.write(f"{len(champ_pool)}개")
st.write(", ".join(champ_badge(cid, id_to_name) for cid in champ_pool) if champ_pool else "(비어있음)")

st.divider()

# 세션 상태 초기화
if "bans" not in st.session_state:
    st.session_state["bans"] = []
if "enemy" not in st.session_state:
    st.session_state["enemy"] = []
if "ally_by_role" not in st.session_state:
    st.session_state["ally_by_role"] = {r: [] for r in ROLES}

bans = st.session_state["bans"]
enemy = st.session_state["enemy"]
ally_by_role = st.session_state["ally_by_role"]

st.header("밴/픽 입력 (한글 이름으로, 엔터로 추가)")

# ---- 밴 입력 ----
st.subheader("밴")
with st.form("ban_form", clear_on_submit=True):
    ban_text = st.text_input("밴할 챔피언 이름 입력 후 엔터", key="ban_text")
    ok = st.form_submit_button("추가(엔터)")
    if ok:
        official, cands = resolve_name(ban_text)
        if official:
            add_champ_by_name(bans, official, name_to_id)
            st.rerun()
        elif cands:
            st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
            st.session_state["ban_cands"] = cands
        else:
            st.error("챔피언을 찾지 못했어요.")

if st.session_state.get("ban_cands"):
    pick = st.selectbox("밴 후보 선택", st.session_state["ban_cands"], key="ban_pick")
    if st.button("이 후보를 밴에 추가", use_container_width=True):
        add_champ_by_name(bans, pick, name_to_id)
        st.session_state["ban_cands"] = None
        st.rerun()

render_chips("밴 목록", bans, id_to_name, "ban")

st.divider()

# ---- 아군 픽: 라인별 입력 ----
st.subheader("아군 픽 (라인별)")
ally_tabs = st.tabs([f"{ROLE_KO[r]}({r})" for r in ROLES])

for idx, r in enumerate(ROLES):
    with ally_tabs[idx]:
        with st.form(f"ally_form_{r}", clear_on_submit=True):
            t = st.text_input(f"{ROLE_KO[r]} 챔피언 입력 후 엔터", key=f"ally_text_{r}")
            ok2 = st.form_submit_button("추가(엔터)")
            if ok2:
                official, cands = resolve_name(t)
                if official:
                    add_champ_by_name(ally_by_role[r], official, name_to_id)
                    st.rerun()
                elif cands:
                    st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
                    st.session_state[f"ally_cands_{r}"] = cands
                else:
                    st.error("챔피언을 찾지 못했어요.")

        if st.session_state.get(f"ally_cands_{r}"):
            pick = st.selectbox("후보 선택", st.session_state[f"ally_cands_{r}"], key=f"ally_pick_{r}")
            if st.button("이 후보로 추가", key=f"ally_pick_btn_{r}", use_container_width=True):
                add_champ_by_name(ally_by_role[r], pick, name_to_id)
                st.session_state[f"ally_cands_{r}"] = None
                st.rerun()

        render_chips(f"{ROLE_KO[r]} 아군 픽", ally_by_role[r], id_to_name, f"ally_{r}")

st.divider()

# ---- 적 픽: 라인 불명이라 그냥 추가 ----
st.subheader("적군 픽 (라인 미정)")
with st.form("enemy_form", clear_on_submit=True):
    enemy_text = st.text_input("적 챔피언 입력 후 엔터", key="enemy_text")
    ok3 = st.form_submit_button("추가(엔터)")
    if ok3:
        official, cands = resolve_name(enemy_text)
        if official:
            add_champ_by_name(enemy, official, name_to_id)
            st.rerun()
        elif cands:
            st.warning("정확한 이름이 아니에요. 아래 후보에서 선택하세요.")
            st.session_state["enemy_cands"] = cands
        else:
            st.error("챔피언을 찾지 못했어요.")

if st.session_state.get("enemy_cands"):
    pick = st.selectbox("적 후보 선택", st.session_state["enemy_cands"], key="enemy_pick")
    if st.button("이 후보로 적군에 추가", use_container_width=True):
        add_champ_by_name(enemy, pick, name_to_id)
        st.session_state["enemy_cands"] = None
        st.rerun()

render_chips("적군 픽", enemy, id_to_name, "enemy")

st.divider()

# 추천 옵션
min_games = st.slider("최소 표본수(games) 필터", min_value=5, max_value=200, value=30, step=5)
top_n = st.slider("추천 개수", min_value=3, max_value=20, value=10, step=1)

# 추천 실행
if st.button("추천 보기", use_container_width=True):
    if not champ_pool:
        st.error("내 라인 챔프폭이 비어있습니다. 먼저 챔프폭 UI에서 챔피언을 저장하세요.")
        st.stop()

    # 아군 픽 합치기
    ally_all = []
    for r in ROLES:
        ally_all.extend(ally_by_role[r])

    # 적 라인 추정(표시용)
    try:
        dist = champ_role_distribution(con, patch, tier)
        guessed = guess_enemy_roles(enemy, dist)
        if enemy:
            st.subheader("적 챔프 라인 추정(간단 버전)")
            for cid in enemy:
                nm = id_to_name.get(cid, "UNKNOWN")
                rr = guessed.get(cid, "UNKNOWN")
                st.write(f"- {nm} → {rr}")
    except Exception:
        pass

    recs = recommend_champions(
        db_path=db_path,
        patch=patch,
        tier=tier,
        my_role=my_role,
        champ_pool=champ_pool,
        bans=bans,
        ally_picks=ally_all,
        enemy_picks=enemy,
        min_games=min_games,
        top_n=top_n,
    )

    st.subheader("추천 결과")
    if not recs:
        st.warning("추천할 데이터가 부족합니다. (표본수 필터가 높거나 DB가 아직 작을 수 있음)")
    else:
        for r in recs:
            cid = r["champ_id"]
            st.write(
                f"**{id_to_name.get(cid,'UNKNOWN')}** — "
                f"승률 {r['wr']}% | 표본 {r['games']}판"
            )

st.caption("※ 현재 MVP는 '내 라인/티어/패치 기준 승률' 중심 추천입니다. (상대/아군 조합 상성 반영은 다음 단계에서 추가)")
