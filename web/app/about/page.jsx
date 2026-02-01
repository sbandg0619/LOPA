import Link from "next/link";

export default function AboutPage() {
  return (
    <div className="card">
      <div className="h1">About</div>
      <p className="p">
        LOPA(로파)는 League of Legends 챔피언 선택(밴/픽) 상황에서,
        내 챔피언 풀을 기준으로 추천을 제공하는 비공식 팬메이드 도구입니다.
      </p>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">Important notice</div>
        <ul className="p" style={{ lineHeight: 1.8, marginTop: 8 }}>
          <li><b>LOPA는 Riot Games와 제휴/승인/후원 관계가 아닙니다.</b></li>
          <li>League of Legends 및 관련 상표/로고는 해당 권리자에게 귀속됩니다.</li>
          <li>본 도구는 교육/편의 목적의 비공식 팬메이드 도구이며, 게임 플레이 결과를 보장하지 않습니다.</li>
        </ul>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Public-safe 구조</div>
        <p className="p">
          공개 서비스에서 서버가 사용자의 LoL 클라이언트(LCU)에 직접 접근하는 것은 불가능/비권장입니다.
          그래서 사용자가 본인 PC에서 <b>LOPA Bridge</b>를 실행하고,
          웹은 <b>localhost 브릿지</b>에서 상태만 읽는 구조를 사용합니다.
        </p>
        <div style={{ height: 10 }} />
        <div className="row">
          <Link className="btn" href="/guide">Guide</Link>
          <Link className="btn" href="/public">Public</Link>
        </div>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Legal</div>
        <p className="p">
          심사/공개 배포 준비를 위해 약관/개인정보/면책/삭제요청/연락처 문서를
          웹에서 바로 열람 가능하게 포함했습니다.
        </p>
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
    </div>
  );
}
