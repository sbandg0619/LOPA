import Link from "next/link";

export default function PublicPage() {
  return (
    <div className="card">
      <div className="h1">LOPA (LoL Pick AI) — Public Build</div>

      <p className="p">
        LOPA(로파)는 League of Legends 챔피언 선택(밴/픽) 상황에서,
        내 챔피언 풀 기준으로 추천을 제공하는 비공식 팬메이드 도구입니다.
      </p>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">Important notice</div>
        <ul className="p" style={{ lineHeight: 1.8, marginTop: 8 }}>
          <li><b>LOPA는 Riot Games와 제휴/승인/후원 관계가 아닙니다.</b></li>
          <li>League of Legends 및 관련 상표/로고는 해당 권리자에게 귀속됩니다.</li>
          <li>본 도구는 교육/편의 목적의 비공식 팬메이드 도구이며, 게임 플레이 결과를 보장하지 않습니다.</li>
        </ul>
      </div>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">What it does</div>
        <ul className="p" style={{ lineHeight: 1.8, marginTop: 8 }}>
          <li><b>챔프 선택창(Champ Select)</b>의 밴/픽 정보를 입력으로 받음</li>
          <li><b>내 라인 + 내 챔프폭</b> 기준으로 추천 계산</li>
          <li>DB 기반 통계(기본승률/카운터/시너지/표본수)를 반영</li>
        </ul>
        <div style={{ height: 10 }} />
        <Link className="btn" href="/recommend">Recommend 열기</Link>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">How “Auto Input” works (Public-safe)</div>
        <p className="p">
          공개 서비스에서 서버가 사용자 PC의 LoL 클라이언트(LCU)에 직접 접근하는 것은 불가능/비권장입니다.
          그래서 LOPA는 <b>Local Bridge(LOPA Bridge)</b> 방식을 사용합니다.
        </p>

        <div className="pre" style={{ marginTop: 10 }}>
{`- 사용자가 본인 PC에서 lopa_bridge.py 실행
- 웹은 http://127.0.0.1:<port> 로컬 브릿지에 접속
- ChampSelect 상태를 자동으로 읽어 입력을 채움
- 브릿지를 실행하지 않으면 수동 입력 모드로 사용`}
        </div>

        <div style={{ height: 10 }} />
        <div className="row">
          <Link className="btn" href="/guide">Guide (실행 순서)</Link>
          <Link className="btn" href="/connect">Connect (브릿지 저장/테스트)</Link>
        </div>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Data &amp; Privacy</div>
        <ul className="p" style={{ lineHeight: 1.8, marginTop: 8 }}>
          <li>LOPA 공개 UI는 사용자의 Riot API Key를 요구하지 않습니다.</li>
          <li>LOPA Bridge는 사용자 PC에서만 실행되며, LCU 정보를 외부로 전송하지 않도록 설계합니다.</li>
          <li>자세한 내용은 아래 Legal 문서를 참고하세요.</li>
        </ul>

        <div style={{ height: 10 }} />
        <div className="row">
          <Link className="btn" href="/legal/terms_ko">이용약관</Link>
          <Link className="btn" href="/legal/privacy_ko">개인정보</Link>
          <Link className="btn" href="/legal/disclaimer_ko">면책</Link>
        </div>
      </div>

      <div className="grid" style={{ marginTop: 14 }}>
        <div className="card" style={{ background: "rgba(255,255,255,0.03)" }}>
          <div className="h2">Contact</div>
          <p className="p">Email: <b>sbandg0619@gmail.com</b></p>
          <div style={{ height: 10 }} />
          <Link className="btn" href="/legal/contact_ko">문의 문서</Link>
        </div>

        <div className="card" style={{ background: "rgba(255,255,255,0.03)" }}>
          <div className="h2">Deletion request</div>
          <p className="p">
            “계정/데이터 삭제를 원하면 이메일로 Riot ID(Name#TAG)와 함께 요청하세요.”
          </p>
          <div style={{ height: 10 }} />
          <Link className="btn" href="/legal/deletion_ko">삭제 요청 문서</Link>
        </div>
      </div>

      <div style={{ height: 14 }} />

      <div className="card" style={{ background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">One-click(로컬 개발)</div>
        <p className="p">
          네가 만든 원클릭 배치로 Bridge/API/Web을 띄운 뒤, 웹에서 Connect → Recommend 흐름으로 사용.
        </p>
        <div className="pre" style={{ marginTop: 10 }}>
{`1) RUN_ONECLICK_PERSONAL.bat 실행
2) http://localhost:3000/connect 접속
3) Bridge token 입력 -> Save + Go Recommend`}
        </div>
      </div>
    </div>
  );
}
