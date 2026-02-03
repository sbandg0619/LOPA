// web/app/api/legal/route.js
import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

// ✅ 서버에서도 slug 화이트리스트 강제 (클라와 동일하게)
const ALLOWED = new Set([
  "terms_ko",
  "privacy_ko",
  "disclaimer_ko",
  "deletion_ko",
  "contact_ko",
  "terms_en",
  "privacy_en",
  "disclaimer_en",
  "deletion_en",
  "contact_en",
]);

function isSafeName(name) {
  // path traversal 방지: terms_ko 같은 형태만 허용
  return /^[a-z0-9_]+$/i.test(String(name || ""));
}

async function readFirstExisting(paths) {
  for (const p of paths) {
    try {
      const txt = await fs.readFile(p, "utf-8");
      return { ok: true, path: p, text: txt };
    } catch {
      // continue
    }
  }
  return { ok: false, path: "", text: "" };
}

export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const name = (searchParams.get("name") || "").trim();

  // ✅ name 검증 + 화이트리스트
  if (!name || !isSafeName(name) || !ALLOWED.has(name)) {
    // not found로 통일(불필요한 힌트/정보 노출 줄임)
    return NextResponse.json({ ok: false, error: "not found" }, { status: 404 });
  }

  const filename = `${name}.md`;

  // Next dev의 cwd는 보통 web 폴더.
  // 아래 후보들을 순서대로 탐색:
  // 1) web/public/legal/*.md (배포에 가장 안전)
  // 2) web/legal/*.md
  // 3) 프로젝트 루트/legal/*.md (web의 상위 폴더)
  const cwd = process.cwd();
  const candidates = [
    path.resolve(cwd, "public", "legal", filename),
    path.resolve(cwd, "legal", filename),
    path.resolve(cwd, "..", "legal", filename),
  ];

  const r = await readFirstExisting(candidates);
  if (!r.ok) {
    // ✅ 내부 경로(tried) 노출 금지
    return NextResponse.json({ ok: false, error: "not found" }, { status: 404 });
  }

  return new NextResponse(r.text, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
