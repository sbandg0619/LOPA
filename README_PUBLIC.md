# LOPA (LoL Pick AI) — Public Build

LOPA(로파)는 League of Legends 챔피언 선택(밴/픽) 상황에서,  
**내 챔피언 풀(champ pool)** 기준으로 추천을 제공하는 **비공식 팬메이드 도구**입니다.

> LOPA는 Riot Games와 무관하며, Riot의 공식 제품이 아닙니다.

---

## What it does

- **챔프 선택창(Champ Select)** 상황의 밴/픽 정보를 입력으로 받아
- **내 라인 + 내 챔프폭** 기준으로 추천을 계산합니다.
- 추천은 DB 기반 통계(기본승률/카운터/시너지/표본수)를 기반으로 합니다.

---

## Architecture (Public-safe by design)

공개 서비스에서 서버가 사용자 PC의 LoL 클라이언트(LCU) lockfile/인증정보에 직접 접근하는 것은 불가능/비권장입니다.  
따라서 LOPA는 **Local Bridge(LOPA Bridge)** 방식을 사용합니다.

