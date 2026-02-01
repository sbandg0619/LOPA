"use client";

import { useEffect, useState } from "react";
import { apiHealth, apiMeta } from "../../lib/api";

export default function MetaPage() {
  const [health, setHealth] = useState(null);
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setErr("");
        const h = await apiHealth();
        const m = await apiMeta("lol_graph_public.db");
        if (!alive) return;
        setHealth(h);
        setMeta(m);
      } catch (e) {
        if (!alive) return;
        setErr(String(e?.message || e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="card">
      <div className="h1">Meta</div>
      <p className="p">배포 환경에서 API 연결(/health, /meta)을 확인하는 페이지.</p>

      {err ? (
        <div className="card" style={{ background: "rgba(255,0,0,0.06)" }}>
          <div className="h2">Error</div>
          <div className="pre">{err}</div>
        </div>
      ) : null}

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">/health</div>
        <div className="pre">{health ? JSON.stringify(health, null, 2) : "loading..."}</div>
      </div>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">/meta</div>
        <div className="pre">{meta ? JSON.stringify(meta, null, 2) : "loading..."}</div>
      </div>
    </div>
  );
}
