// web/app/page.jsx
import Link from "next/link";

export default function HomePage() {
  return (
    <div className="card">
      <div className="h1">LOPA (로파) — Web</div>
      <p className="p">
        목표: Riot Production Key 승인을 위해, 공개 배포 가능한 형태(보안/운영/문서/동작 시나리오)를 갖춘 웹 서비스를 완성합니다.
      </p>

      <div style={{ height: 14 }} />

      {/* Quick actions */}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <Link className="btn" href="/recommend">바로 Recommend</Link>
          <Link className="btn" href="/connect">브릿지 연결(Connect)</Link>
          <Link className="btn" href="/guide">가이드</Link>
        </div>
        <div className="badge" title="로컬 PC에서 Bridge/API를 켜고 쓰는 개발 모드">
          Local Dev
        </div>
      </div>

      <div style={{ height: 14 }} />

      {/* Main grid */}
      <div className="grid">
        <div className="card">
          <div className="h2">✅ 추천 사용 순서 (권장)</div>
          <div className="p" style={{ marginTop: 8 }}>
            1) <b>Bridge</b> 실행 (LCU 읽기)<br />
            2) <b>API</b> 실행 (추천 계산)<br />
            3) <b>Web</b> 실행 → <b>Connect</b>에서 토큰 저장 → <b>Recommend</b> 사용
          </div>

          <div style={{ height: 10 }} />

          <div className="card" style={{ background: "rgba(255,255,255,0.03)" }}>
            <div className="h2" style={{ marginBottom: 6 }}>AutoConnect 옵션</div>
            <p className="p" style={{ marginTop: 0 }}>
              한 번에 연결/이동이 필요하면 아래 형태로 접속 가능합니다.
              <br />
              <span style={{ opacity: 0.9 }}>
                (주의: URL에 token이 노출될 수 있으니, 개인 PC에서만 사용 권장)
              </span>
            </p>
            <div className="pre" style={{ marginTop: 10 }}>
              {`http://localhost:3000/autoconnect?bridge=http://127.0.0.1:12145&token=YOUR_TOKEN&next=/recommend`}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="h2">1) Guide</div>
          <p className="p">설치/실행 동선(브릿지/웹/API)과 “자동 입력” 개념을 정리합니다.</p>
          <div style={{ height: 10 }} />
          <Link className="btn" href="/guide">Guide 열기</Link>
        </div>

        <div className="card">
          <div className="h2">2) Connect</div>
          <p className="p">
            브릿지 URL/토큰을 <b>localStorage에 1회 저장</b>합니다. (401 방지)
            <br />
            저장 후 <b>Recommend</b>에서 자동으로 읽어옵니다.
          </p>
          <div style={{ height: 10 }} />
          <Link className="btn" href="/connect">Connect 열기</Link>
        </div>

        <div className="card">
          <div className="h2">3) Recommend</div>
          <p className="p">
            브릿지에서 챔프셀렉트 상태를 읽고(옵션), API(/recommend)로 추천을 받아 보여줍니다.
          </p>
          <div style={{ height: 10 }} />
          <Link className="btn" href="/recommend">Recommend 열기</Link>
        </div>

        <div className="card">
          <div className="h2">Public Build (심사용 요약)</div>
          <p className="p">
            공개 배포 관점에서 “Auto Input(로컬 브릿지)” 구조와
            데이터/프라이버시/삭제요청/문의 문서를 한 페이지에 정리했습니다.
          </p>
          <div style={{ height: 10 }} />
          <div className="row">
            <Link className="btn" href="/public">Public 페이지</Link>
            <Link className="btn" href="/legal">Legal 문서</Link>
          </div>
        </div>

        <div className="card">
          <div className="h2">UI 개선 방향</div>
          <p className="p">
            Streamlit 감성은 “장점만” 가져오고, 기능 안정성(브릿지/추천)은 절대 건드리지 않는 방향.
            <br />
            지금은 심사용 준비(문서/동선/안정성) 우선으로 정리 중.
          </p>
        </div>
      </div>
    </div>
  );
}
