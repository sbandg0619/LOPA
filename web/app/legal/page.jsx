"use client";

import Link from "next/link";

const DOCS = [
  { slug: "terms_ko", title: "이용약관 (KO)" },
  { slug: "privacy_ko", title: "개인정보처리방침 (KO)" },
  { slug: "disclaimer_ko", title: "면책조항 (KO)" },
  { slug: "deletion_ko", title: "데이터 삭제 요청 (KO)" },
  { slug: "contact_ko", title: "문의/연락처 (KO)" },
  { slug: "terms_en", title: "Terms (EN)" },
  { slug: "privacy_en", title: "Privacy (EN)" },
  { slug: "disclaimer_en", title: "Disclaimer (EN)" },
  { slug: "deletion_en", title: "Deletion Request (EN)" },
  { slug: "contact_en", title: "Contact (EN)" },
];

export default function LegalIndexPage() {
  return (
    <div className="card">
      <div className="h1">Legal</div>
      <p className="p">
        아래 문서들은 공개 배포/심사 관점에서 필요한 항목들을 웹에서 바로 열람 가능하도록 정리해 둔 것입니다.
      </p>

      <div style={{ height: 10 }} />

      <div className="grid">
        {DOCS.map((d) => (
          <div
            key={d.slug}
            className="card"
            style={{ background: "rgba(255,255,255,0.03)" }}
          >
            <div className="h2" style={{ marginBottom: 6 }}>
              {d.title}
            </div>
            <p className="p" style={{ marginTop: 0 }}>
              slug: <b>{d.slug}</b>
            </p>
            <div style={{ height: 8 }} />
            <Link className="btn" href={`/legal/${d.slug}`}>열기</Link>
          </div>
        ))}
      </div>

      <div style={{ height: 16 }} />

      <div className="card" style={{ background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">윈도우에서 legal 파일 한번에 복사</div>
        <p className="p">
          배포 안정성을 위해 <b>web/public/legal</b> 아래에 md를 두는 걸 권장.
          아래 명령어로 루트 legal 폴더의 md를 web/public로 복사해.
        </p>
        <div className="pre">
{`cd /d "C:\\Users\\ajtwl\\OneDrive\\바탕 화면\\lol_pick_ai"
if not exist "web\\public\\legal" mkdir "web\\public\\legal"
xcopy /E /I /Y "legal\\*.md" "web\\public\\legal\\"`}
        </div>
        <p className="p">
          * 복사 안 해도 /api/legal이 상위 폴더(../legal)도 찾아보긴 하지만,
          배포/빌드 관점에선 public에 두는 게 가장 안전함.
        </p>
      </div>
    </div>
  );
}

export { DOCS };
