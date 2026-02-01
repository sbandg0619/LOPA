\# Security \& Abuse Prevention (LOPA)



\## Overview

LOPA는 Riot Games 공식 서비스가 아닌 팬메이드 도구입니다.

공개 서비스 환경에서 개인 PC의 League Client(LCU)에 접근하지 않기 위해,

"Local Bridge" 구조를 사용합니다.



\## Local Bridge model

\- `lopa\_bridge.py`는 사용자 PC에서 실행됩니다.

\- Streamlit UI는 사용자의 로컬 브릿지(127.0.0.1)로만 요청합니다.

\- 외부 서버가 LCU/lockfile/토큰을 직접 취득하는 구조가 아닙니다.



\## Token

\- 브릿지는 단순 보호용 토큰(X-LOPA-TOKEN)을 지원합니다.

\- 토큰은 브릿지 실행 시 콘솔에 출력되며, 사용자는 이를 UI 환경변수로 설정합니다.

\- 토큰이 없다면 같은 PC 내 다른 프로세스가 호출할 수 있으므로 토큰 사용을 권장합니다.



\## Logging

\- 공개 UI는 기본적으로 사용자의 개인 식별정보를 수집하지 않습니다.

\- 운영 시 서버 로그에는 IP 등 접속 로그가 남을 수 있습니다(호스팅 플랫폼 정책).

\- LOPA Bridge는 로컬에서만 동작하며, 외부 전송을 최소화합니다.



\## Reporting

\- 취약점/보안 이슈 제보: sbandg0619@gmail.com



