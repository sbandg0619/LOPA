// web/lib/bridge.js
// - Bridge /health, /state 호출 유틸
// - 폴링 환경에서 "JSON 파싱 실패"가 UI를 흔드는 걸 막기 위해 안전 파서 사용
// - 401은 명확히 처리, 그 외 HTTP 에러는 raw 텍스트 보존

function safeJsonParse(txt) {
  if (!txt) return null;
  try {
    return JSON.parse(txt);
  } catch {
    return { _raw: txt };
  }
}

export async function bridgeHealth({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const headers = {};
    if (bridgeToken) headers["X-LOPA-TOKEN"] = bridgeToken;

    const r = await fetch(`${String(bridgeBase || "").replace(/\/$/, "")}/health`, {
      method: "GET",
      headers,
      signal: controller.signal,
      cache: "no-store",
    });

    const txt = await r.text();
    const j = safeJsonParse(txt) || {};

    if (r.status === 401) return { ok: false, msg: "401 invalid token", raw: j };
    if (!r.ok) return { ok: false, msg: `HTTP ${r.status}`, raw: j };

    // 브릿지 정상 응답 형태 유지(보통 {ok:true, msg:"..."} )
    return j;
  } catch (e) {
    // AbortError는 타임아웃으로 명시
    const msg = e?.name === "AbortError" ? "timeout" : String(e?.message || e);
    return { ok: false, msg, error: msg };
  } finally {
    clearTimeout(id);
  }
}

export async function bridgeState({ bridgeBase, bridgeToken, timeoutMs = 2000 }) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const headers = {};
    if (bridgeToken) headers["X-LOPA-TOKEN"] = bridgeToken;

    const r = await fetch(`${String(bridgeBase || "").replace(/\/$/, "")}/state`, {
      method: "GET",
      headers,
      signal: controller.signal,
      cache: "no-store",
    });

    const txt = await r.text();
    const j = safeJsonParse(txt) || {};

    if (r.status === 401) throw new Error("401 invalid token");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);

    return j;
  } finally {
    clearTimeout(id);
  }
}
