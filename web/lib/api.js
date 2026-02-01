// web/lib/api.js
// ✅ 목표:
// - 배포(Vercel)에서는 기본 API가 Render를 보도록
// - 로컬(localhost)에서는 기본 API가 127.0.0.1:8000을 보도록
// - NEXT_PUBLIC_API_BASE가 있으면 그 값을 최우선으로 사용

const RENDER_API = "https://lopa-api.onrender.com";
const LOCAL_API = "http://127.0.0.1:8000";

function isLocalHost() {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h === "localhost" || h === "127.0.0.1";
}

function getDefaultApiBase() {
  const env =
    (typeof process !== "undefined" && process.env && process.env.NEXT_PUBLIC_API_BASE) || "";
  if (env) return String(env).trim().replace(/\/$/, "");
  if (isLocalHost()) return LOCAL_API;
  return RENDER_API;
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
    const msg = j?.detail ? String(j.detail) : `HTTP ${r.status}`;
    throw new Error(msg);
  }

  return j;
}

export async function apiHealth(apiBase) {
  const base = String(apiBase || getDefaultApiBase()).replace(/\/$/, "");
  return await fetchText(`${base}/health`, { method: "GET" });
}

export async function apiRecommend(body, apiBase) {
  const base = String(apiBase || getDefaultApiBase()).replace(/\/$/, "");
  return await fetchText(`${base}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiMeta(dbPath, apiBase) {
  const base = String(apiBase || getDefaultApiBase()).replace(/\/$/, "");
  const qs = new URLSearchParams();
  if (dbPath) qs.set("db_path", String(dbPath));
  return await fetchText(`${base}/meta?${qs.toString()}`, { method: "GET" });
}
