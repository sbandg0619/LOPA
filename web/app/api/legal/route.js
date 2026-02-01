import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";

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

  if (!isSafeName(name)) {
    return NextResponse.json({ ok: false, error: "invalid name" }, { status: 400 });
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
    return NextResponse.json(
      { ok: false, error: "not found", tried: candidates },
      { status: 404 }
    );
  }

  return new NextResponse(r.text, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
