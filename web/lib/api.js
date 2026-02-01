// web/lib/api.js

// ✅ 배포(예: Vercel)에서는 환경변수로 API 주소를 주입
//   - Vercel Environment Variables:
//     NEXT_PUBLIC_API_BASE = https://lopa-api.onrender.com
// ✅ 로컬 개발에서는 기본값으로 127.0.0.1:8000 사용
const DEFAULT_API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

async function fetchText(url, opts = {}) {
  const r = await fetch(url, opts);
  const txt = await r.text();

  let j = null;
  try {
    j = txt ? JSON.parse(txt) : null;
  } catch {
    j = { _raw: txt };
  }

  if (!r.ok) {
    const msg = j?.detail ? String(j.detail) : `HTTP ${r.status}`;
    throw new Error(msg);
  }

  return j;
}

export async function apiHealth(apiBase = DEFAULT_API) {
  const base = String(apiBase || DEFAULT_API).replace(/\/$/, "");
  return await fetchText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase = DEFAULT_API) {
  const base = String(apiBase || DEFAULT_API).replace(/\/$/, "");
  return await fetchText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ✅ /meta (patch list, latest_patch)
export async function apiMeta(dbPath, apiBase = DEFAULT_API) {
  const base = String(apiBase || DEFAULT_API).replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
