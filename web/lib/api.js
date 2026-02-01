// web/lib/api.js
const FALLBACK_LOCAL = "http://127.0.0.1:8000";

function getApiBase() {
  // Vercel에서 환경변수로 주입: NEXT_PUBLIC_API_BASE
  // 로컬 개발: 없으면 127.0.0.1:8000 사용
  const env = typeof process !== "undefined" ? process.env?.NEXT_PUBLIC_API_BASE : "";
  const base = (env || "").trim() || FALLBACK_LOCAL;
  return base.replace(/\/$/, "");
}

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
    // detail이 객체일 때도 사용자에게 문자열로 보이게 처리
    const detail = j?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail
        ? JSON.stringify(detail)
        : j?._raw
        ? String(j._raw)
        : `HTTP ${r.status}`;
    throw new Error(msg);
  }

  return j;
}

export async function apiRecommend(body) {
  const base = getApiBase();
  return await fetchText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath) {
  const base = getApiBase();
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
