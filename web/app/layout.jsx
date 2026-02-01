import "./globals.css";
import Link from "next/link";

export const metadata = {
  title: "LOPA (로파) — Web",
  description: "LOPA web for Riot Production Key readiness",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>
        <div className="wrap">
          <header className="topbar">
            <div className="brand">
              <Link href="/" className="brandLink">
                LOPA (로파)
              </Link>
              <span className="badge">WEB</span>
            </div>

            <nav className="nav">
              <Link className="navLink" href="/">Home</Link>
              <Link className="navLink" href="/guide">Guide</Link>
              <Link className="navLink" href="/recommend">Recommend</Link>
              <Link className="navLink" href="/connect">Connect</Link>

              {/* ✅ 추가: Meta */}
              <Link className="navLink" href="/meta">Meta</Link>

              <Link className="navLink" href="/legal">Legal</Link>
              <Link className="navLink" href="/public">Public</Link>
              <Link className="navLink" href="/about">About</Link>
            </nav>
          </header>

          <main className="main">{children}</main>

          <footer className="footer">
            <div>LOPA(로파)는 Riot Games와 무관한 비공식 팬메이드 도구입니다.</div>
          </footer>
        </div>
      </body>
    </html>
  );
}
