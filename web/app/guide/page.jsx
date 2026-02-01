import Link from "next/link";

export default function GuidePage() {
  return (
    <div className="card">
      <div className="h1">Guide</div>

      <div className="row" style={{ marginTop: 10 }}>
        <Link className="btn" href="/connect">Connect</Link>
        <Link className="btn" href="/recommend">Recommend</Link>
        <Link className="btn" href="/about">About</Link>
        <Link className="btn" href="/legal">Legal</Link>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">전체 구조</div>
        <p className="p">
          웹은 브라우저에서 실행되고, 브릿지는 사용자 PC(127.0.0.1)에서 LoL 클라이언트(LCU)를 읽습니다.
          서버가 lockfile에 직접 접근하지 않기 때문에 “공개 서비스”에서 현실적인 방식입니다.
        </p>
        <div className="pre">
{`[User PC]
LoL Client(LCU)  <--local-->  LOPA Bridge (http://127.0.0.1:12145)

[Browser]
LOPA Web (Next.js)  --fetch-->  Bridge /health, /state

[Local API or Server]
LOPA API (FastAPI)  <--web-->  /recommend`}
        </div>
        <p className="p" style={{ marginTop: 10 }}>
          * 브릿지를 실행하지 않아도 <b>Recommend</b> 페이지에서 수동 입력으로 추천 호출이 가능합니다(브릿지는 Auto Input 옵션).
        </p>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">실행 순서(로컬 개발 기준)</div>
        <ol className="p" style={{ lineHeight: 1.8 }}>
          <li>LoL 클라이언트 실행</li>
          <li>브릿지 실행: <b>RUN_BRIDGE.bat</b> (또는 python lopa_bridge.py)</li>
          <li>API 실행: <b>RUN_API.bat</b> (또는 uvicorn api_server:app)</li>
          <li>웹 실행: <b>web 폴더에서 npm run dev</b></li>
          <li>웹에서 <b>Connect</b> 페이지에서 브릿지 URL/토큰 저장(1회)</li>
          <li><b>Recommend</b> 페이지에서 Bridge 상태 읽고 추천 호출</li>
        </ol>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">자주 터지는 문제</div>
        <ul className="p" style={{ lineHeight: 1.8 }}>
          <li><b>Bridge 401</b>: 토큰이 저장/일치하지 않음 → Connect에서 저장</li>
          <li><b>Bridge FAIL</b>: 브릿지 미실행/포트 다름 → 12145 확인</li>
          <li><b>추천이 빈 배열</b>: DB/집계/필터 문제(패치/티어/min_games) → API 로그 확인</li>
        </ul>
      </div>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">심사/공개 배포 대비 포인트</div>
        <ul className="p" style={{ lineHeight: 1.8 }}>
          <li>
            “Public-safe Auto Input”: 서버가 사용자 PC의 lockfile/LCU에 직접 접근하지 않고, 로컬 브릿지로만 읽음
          </li>
          <li>
            <b>About</b> 페이지에 서비스 설명/데이터/프라이버시 컨셉 정리
          </li>
          <li>
            <b>Legal</b> 페이지에 약관/개인정보/면책/삭제요청/문의 문서 노출
          </li>
        </ul>
        <div className="row" style={{ marginTop: 10 }}>
          <Link className="btn" href="/about">About 열기</Link>
          <Link className="btn" href="/legal">Legal 열기</Link>
        </div>
      </div>
    </div>
  );
}
