"use client";

// web/app/connect/page.jsx
// 목적:
// 1) 여기서 저장한 bridge/token/api가 Recommend에서 동일하게 읽히게 함.
// 2) /connect?bridge=...&token=...&api=...&next=/recommend 로 들어오면
//    자동으로 저장 후 next로 이동(=자동이동).
//
// ✅ Fix:
// - auto-save 직후 router.replace(SPA)로 이동하면 Recommend의 초기 fetch 타이밍 레이스가 생길 수 있음
// - 그래서 auto 이동은 window.location.replace(하드 네비게이션)로 변경
// - api= 파라미터도 같이 저장해서 Render(슬립) 대신 로컬 API를 안정적으로 사용 가능

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { bridgeHealth, bridgeState } from "../../lib/bridge";
import { getBridgeConfig, setBridgeConfig, clearBridgeConfig } from "../../lib/constants";

function ConnectInner() {
  const router = useRouter();
  const sp = useSearchParams();

  const [bridgeBase, setBridgeBase] = useState("");
  const [bridgeToken, setBridgeToken] = useState("");
  const [apiBase, setApiBase] = useState("");

  const [msg, setMsg] = useState("");
  const [raw, setRaw] = useState(null);

  // ✅ token 보이기/숨기기
  const [showToken, setShowToken] = useState(false);

  // URL params (있으면 자동 저장+이동)
  const qsBridge = useMemo(() => (sp.get("bridge") || "").trim(), [sp]);
  const qsToken = useMemo(() => (sp.get("token") || "").trim(), [sp]);
  const qsApi = useMemo(() => (sp.get("api") || "").trim(), [sp]);
  const qsNext = useMemo(() => (sp.get("next") || "/recommend").trim() || "/recommend", [sp]);

  // 1) 최초: localStorage 값 로드
  useEffect(() => {
    const cfg = getBridgeConfig();
    setBridgeBase(cfg?.bridgeBase || "http://127.0.0.1:12145");
    setBridgeToken(cfg?.bridgeToken || "");
    setApiBase(cfg?.apiBase || "http://127.0.0.1:8000");
  }, []);

  // 2) URL 파라미터가 있으면 입력칸에도 반영 (보이는 값)
  useEffect(() => {
    if (qsBridge) setBridgeBase(qsBridge);
    if (qsToken) setBridgeToken(qsToken);
    if (qsApi) setApiBase(qsApi);
  }, [qsBridge, qsToken, qsApi]);

  const effectiveBridge = useMemo(() => (bridgeBase || "").trim().replace(/\/$/, ""), [bridgeBase]);
  const effectiveToken = useMemo(() => (bridgeToken || "").trim(), [bridgeToken]);
  const effectiveApi = useMemo(() => (apiBase || "").trim().replace(/\/$/, ""), [apiBase]);

  // 3) URL 파라미터가 있으면 자동 저장 + 자동 이동
  useEffect(() => {
    if (!qsBridge && !qsToken && !qsApi) return;

    const saveBridge = (qsBridge || effectiveBridge || "").trim().replace(/\/$/, "");
    const saveToken = (qsToken || effectiveToken || "").trim();
    const saveApi = (qsApi || effectiveApi || "").trim().replace(/\/$/, "");

    // ✅ 저장 (constants.js가 sanitize + default 처리)
    setBridgeConfig({
      bridgeBase: saveBridge,
      bridgeToken: saveToken,
      apiBase: saveApi, // ✅ NEW
    });

    // ✅ 토큰이 주소창에 남지 않게, 우선 URL을 /connect로 바꾸고(히스토리) 곧바로 이동
    try {
      window.history.replaceState({}, "", "/connect");
    } catch {}

    // ✅ 하드 네비게이션(레이스 제거)
    setTimeout(() => {
      window.location.replace(qsNext);
    }, 50);

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qsBridge, qsToken, qsApi, qsNext]);

  async function onTestHealth() {
    setMsg("Testing /health ...");
    setRaw(null);
    try {
      const j = await bridgeHealth({ bridgeBase: effectiveBridge, bridgeToken: effectiveToken, timeoutMs: 2000 });
      setRaw(j);
      if (j && j.ok) setMsg("✅ Bridge OK (health)");
      else setMsg(`❌ Bridge FAIL (health): ${j?.msg || "unknown"}`);
    } catch (e) {
      setMsg(`❌ Bridge error: ${String(e)}`);
    }
  }

  async function onTestState() {
    setMsg("Testing /state ...");
    setRaw(null);
    try {
      const j = await bridgeState({ bridgeBase: effectiveBridge, bridgeToken: effectiveToken, timeoutMs: 2000 });
      setRaw(j);
      if (j && j.ok) setMsg("✅ Bridge OK (state)");
      else setMsg(`❌ Bridge FAIL (state): ${j?.msg || "unknown"}`);
    } catch (e) {
      setMsg(`❌ Bridge error: ${String(e)}`);
    }
  }

  function onSaveOnly() {
    setBridgeConfig({ bridgeBase: effectiveBridge, bridgeToken: effectiveToken, apiBase: effectiveApi });
    setMsg("✅ Saved to localStorage. 이제 Recommend에서 bridge/api 모두 같은 설정으로 읽힙니다.");
    setRaw(null);
  }

  function onSaveAndGo() {
    setBridgeConfig({ bridgeBase: effectiveBridge, bridgeToken: effectiveToken, apiBase: effectiveApi });
    // 수동 버튼은 SPA 이동 OK
    router.push("/recommend");
  }

  function onClear() {
    clearBridgeConfig();
    setBridgeBase("http://127.0.0.1:12145");
    setBridgeToken("");
    setApiBase("http://127.0.0.1:8000");
    setMsg("🧹 Cleared local config.");
    setRaw(null);
  }

  const standardAutoUrl = useMemo(() => {
    return `http://localhost:3000/autoconnect?bridge=http://127.0.0.1:12145&token=YOUR_TOKEN&api=http://127.0.0.1:8000&next=/recommend`;
  }, []);

  return (
    <div className="card">
      <div className="h1">Connect</div>

      <p className="p">
        브릿지는 <b style={{ color: "var(--text)" }}>사용자 PC</b>에서 LCU를 읽고, 웹은{" "}
        <b style={{ color: "var(--text)" }}>localhost 브릿지</b>에서 상태만 읽습니다.
        <br />
        <span style={{ opacity: 0.92 }}>
          TIP:{" "}
          <b style={{ color: "var(--text)" }}>
            /autoconnect?bridge=...&token=...&api=...&next=/recommend
          </b>{" "}
          로 들어오면 자동 저장 후 자동 이동합니다.
        </span>
      </p>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2" style={{ marginBottom: 6 }}>표준 AutoConnect URL</div>
        <div className="p" style={{ marginTop: 0, opacity: 0.92 }}>
          Home 페이지와 동일한 표준 형식입니다. (token 노출 가능 → 개인 PC에서만 권장)
        </div>
        <div className="pre" style={{ marginTop: 10 }}>{standardAutoUrl}</div>
      </div>

      <div style={{ height: 10 }} />

      <div className="card">
        <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 12 }}>
          <label>
            <div className="p" style={{ fontWeight: 900, marginBottom: 6 }}>
              Bridge URL
            </div>
            <input
              className="input"
              value={bridgeBase}
              onChange={(e) => setBridgeBase(e.target.value)}
              placeholder="http://127.0.0.1:12145"
            />
          </label>

          <label>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div className="p" style={{ fontWeight: 900, marginBottom: 6 }}>
                Bridge Token
              </div>
              <label className="p" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
                <input
                  type="checkbox"
                  checked={showToken}
                  onChange={(e) => setShowToken(e.target.checked)}
                />
                token 보기
              </label>
            </div>

            <input
              className="input"
              value={bridgeToken}
              onChange={(e) => setBridgeToken(e.target.value)}
              placeholder="브릿지 콘솔에 출력된 token"
              type={showToken ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
            />
            <div className="p" style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
              401이 뜨면 토큰이 저장/일치하지 않는 경우가 대부분입니다.
            </div>
          </label>

          <label>
            <div className="p" style={{ fontWeight: 900, marginBottom: 6 }}>
              API Base (LOPA API)
            </div>
            <input
              className="input"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              spellCheck={false}
            />
            <div className="p" style={{ marginTop: 6, fontSize: 12, opacity: 0.9 }}>
              배포 환경에서 Render가 슬립이면 첫 /meta가 실패할 수 있어서, 로컬 API를 쓰려면 여기 값을 127.0.0.1로 저장하세요.
            </div>
          </label>

          <div className="row" style={{ marginTop: 4 }}>
            <button className="btn" onClick={onSaveOnly}>
              Save (local)
            </button>
            <button className="btn" onClick={onSaveAndGo}>
              Save + Go Recommend
            </button>
            <button className="btn" onClick={onTestHealth}>
              Test /health
            </button>
            <button className="btn" onClick={onTestState}>
              Test /state
            </button>
            <button className="btn" onClick={onClear} style={{ background: "rgba(255,255,255,0.03)" }}>
              Clear
            </button>
          </div>

          {msg ? <div style={{ marginTop: 6, fontWeight: 900 }}>{msg}</div> : null}

          <div style={{ marginTop: 8 }}>
            <div className="p" style={{ margin: 0 }}>
              현재 적용 값(입력칸 기준):
            </div>
            <div className="pre">
              {`bridgeBase: ${effectiveBridge || "(empty)"}\nbridgeToken: ${effectiveToken ? "(set)" : "(empty)"}\napiBase: ${effectiveApi || "(empty)"}`}
            </div>
          </div>

          {raw ? (
            <div style={{ marginTop: 8 }}>
              <div className="p" style={{ fontWeight: 900, margin: 0 }}>
                Raw response
              </div>
              <div className="pre">{JSON.stringify(raw, null, 2)}</div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function ConnectPage() {
  return (
    <Suspense fallback={<div className="card"><div className="p">loading...</div></div>}>
      <ConnectInner />
    </Suspense>
  );
}
