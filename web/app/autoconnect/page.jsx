"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function AutoConnectInner() {
  const router = useRouter();
  const sp = useSearchParams();

  const bridge = useMemo(() => (sp.get("bridge") || "").trim(), [sp]);
  const token = useMemo(() => (sp.get("token") || "").trim(), [sp]);
  const next = useMemo(() => (sp.get("next") || "/recommend").trim() || "/recommend", [sp]);

  useEffect(() => {
    // ✅ /connect로 query를 붙여서 넘김 (connect가 저장+이동 처리)
    const qs = new URLSearchParams();
    if (bridge) qs.set("bridge", bridge);
    if (token) qs.set("token", token);
    if (next) qs.set("next", next);

    router.replace(`/connect?${qs.toString()}`);
  }, [bridge, token, next, router]);

  return (
    <div className="card">
      <div className="h1">AutoConnect</div>
      <p className="p">connect로 이동 중...</p>
      <div className="pre">{`bridge: ${bridge || "(empty)"}\ntoken: ${token ? "(set)" : "(empty)"}\nnext: ${next}`}</div>
    </div>
  );
}

export default function AutoConnectPage() {
  return (
    <Suspense fallback={<div className="card"><div className="p">loading...</div></div>}>
      <AutoConnectInner />
    </Suspense>
  );
}
