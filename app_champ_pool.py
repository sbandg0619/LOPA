import streamlit as st
import difflib

from champ_pool_store import load_pool, save_pool, ROLES
from champion_catalog import load_champions_ko

ROLE_KO = {"TOP":"탑", "JUNGLE":"정글", "MIDDLE":"미드", "BOTTOM":"원딜", "UTILITY":"서폿"}

def norm(s: str) -> str:
    # 공백/특수문자 제거 + 소문자 (한글은 그대로)
    s = (s or "").strip().lower()
    for ch in [" ", ".", "'", "’", "-", "_", "·"]:
        s = s.replace(ch, "")
    return s

st.set_page_config(page_title="LoL 챔프폭 관리", layout="centered")
st.title("라인별 챔피언 폭 관리 (엔터로 추가 확실 버전)")

pool = load_pool()

# 챔피언 목록 로드(ko_KR)
try:
    champs = load_champions_ko()
    id_to_name = {int(k): v for k, v in champs["id_to_name"].items()}
    name_to_id = champs["name_to_id"]
    all_names = champs["all_names"]
    st.caption(f"챔피언 데이터: Data Dragon {champs['version']} (ko_KR)")
except Exception:
    st.error("챔피언 목록을 불러오지 못했습니다. 인터넷/방화벽을 확인하세요.")
    st.stop()

# 정규화 인덱스(오타 보정용)
norm_to_official = {norm(nm): nm for nm in all_names}
official_norms = list(norm_to_official.keys())

role = st.selectbox("라인 선택", ROLES, format_func=lambda r: f"{ROLE_KO.get(r,r)} ({r})")

def display_name(x):
    if isinstance(x, int):
        return f"{id_to_name.get(x, 'UNKNOWN')} ({x})"
    return str(x)

def add_by_official_name(official_name: str):
    cid = int(name_to_id[official_name])
    if cid in pool[role]:
        st.info("이미 저장되어 있습니다.")
        return
    pool[role].append(cid)
    save_pool(pool)
    st.success(f"{ROLE_KO[role]}에 추가됨: {official_name} ({cid})")

st.divider()

# ✅ 빠른 추가: text_input에서 Enter로 제출이 확실히 동작
st.subheader("빠른 추가 (여기 입력칸에서 엔터 누르면 추가)")
with st.form("quick_add_form", clear_on_submit=True):
    user_text = st.text_input("챔피언 이름 입력 (예: 미스 포춘 / 미스 포츈 / 파이크)", key="quick_name")
    submitted = st.form_submit_button("엔터로 추가")

    if submitted:
        q = (user_text or "").strip()
        if not q:
            st.warning("이름을 입력하세요.")
        else:
            # 1) 정확 일치
            if q in name_to_id:
                add_by_official_name(q)
            else:
                nq = norm(q)

                # 2) 정규화(공백/특수문자 제거)로 정확 일치
                if nq in norm_to_official:
                    official = norm_to_official[nq]
                    if official != q:
                        st.info(f"입력을 '{official}'로 인식했어요.")
                    add_by_official_name(official)
                else:
                    # 3) 유사도 기반 후보 추천
                    close = difflib.get_close_matches(nq, official_norms, n=5, cutoff=0.80)

                    if close:
                        best_official = norm_to_official[close[0]]
                        # 확신 높으면 자동 보정해서 추가
                        score = difflib.SequenceMatcher(None, nq, close[0]).ratio()
                        if score >= 0.90:
                            st.info(f"'{q}' → '{best_official}'로 자동 보정해서 추가했어요. (유사도 {score:.2f})")
                            add_by_official_name(best_official)
                        else:
                            # 확신 낮으면 후보 보여주기(여긴 클릭이 필요)
                            cand_officials = [norm_to_official[c] for c in close]
                            st.warning("정확한 이름이 아니에요. 아래 후보 중에서 선택해 주세요.")
                            st.session_state["_cands"] = cand_officials
                            st.session_state["_q"] = q
                    else:
                        st.error("챔피언을 찾지 못했어요. 철자를 확인해 주세요.")

# 후보가 생기면 선택해서 추가(클릭 1번)
if st.session_state.get("_cands"):
    st.subheader("후보 선택(자동 보정이 애매할 때)")
    pick = st.selectbox("이 챔피언이 맞나요?", st.session_state["_cands"], key="cand_pick")
    if st.button("이 후보로 추가", use_container_width=True):
        add_by_official_name(pick)
        st.session_state["_cands"] = None

st.divider()

# ✅ 기존 방식도 유지: 목록에서 골라서 추가(오타 완전 차단)
st.subheader("목록에서 선택해서 추가 (오타 0%)")
with st.form("select_add_form"):
    selected_name = st.selectbox("챔피언 검색", all_names, key="champ_select")
    submitted2 = st.form_submit_button("추가")
    if submitted2:
        add_by_official_name(selected_name)

st.divider()

# 삭제
st.subheader("삭제")
if pool[role]:
    options = pool[role][:]
    to_del = st.multiselect("삭제할 챔피언 선택", options, format_func=display_name)
    if st.button("선택 삭제", use_container_width=True):
        if not to_del:
            st.warning("삭제할 항목을 선택하세요.")
        else:
            pool[role] = [x for x in pool[role] if x not in set(to_del)]
            save_pool(pool)
            st.success(f"{len(to_del)}개 삭제 완료")
else:
    st.info("이 라인에는 아직 저장된 챔피언이 없습니다.")

# 현재 라인 목록
st.subheader("현재 라인 챔프폭")
st.write(f"**{ROLE_KO[role]} ({role})**: {len(pool[role])}개")
st.code(", ".join(display_name(x) for x in pool[role]) if pool[role] else "(비어있음)")

# 전체 요약
with st.expander("전체 라인 요약 보기"):
    for r in ROLES:
        st.write(f"**{ROLE_KO[r]} ({r})**: {len(pool[r])}개")
        st.write(", ".join(display_name(x) for x in pool[r]) if pool[r] else "(비어있음)")

st.divider()

# 초기화
st.subheader("초기화")
c1, c2 = st.columns(2)
with c1:
    if st.button("현재 라인 전체 삭제", use_container_width=True):
        pool[role] = []
        save_pool(pool)
        st.success(f"{ROLE_KO[role]} 챔프폭을 비웠습니다.")
with c2:
    if st.button("전체 라인 초기화(전부 삭제)", use_container_width=True):
        for r in ROLES:
            pool[r] = []
        save_pool(pool)
        st.success("전체 라인 챔프폭을 전부 비웠습니다.")
