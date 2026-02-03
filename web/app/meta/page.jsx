"use client";

import { useEffect, useMemo, useState } from "react";
import { apiHealth, apiMeta, getEffectiveApiBase } from "../../lib/api";

export default function MetaPage() {
  const [health, setHealth] = useState(null);
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState("");

  const defaultDbPath = useMemo(() => {
    if (typeof window === "undefined") return "lol_graph_public.db";
    return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
      ? "lol_graph_personal.db"
      : "lol_graph_public.db";
  }, []);

  const effectiveApi = useMemo(() => {
    try {
      return getEffectiveApiBase();
    } catch {
      return "(unknown)";
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setErr("");
        const h = await apiHealth();
        const m = await apiMeta(defaultDbPath);
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
  }, [defaultDbPath]);

  return (
    <div className="card">
      <div className="h1">Meta</div>
      <p className="p">배포 환경에서 API 연결(/health, /meta)을 확인하는 페이지.</p>

      <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.03)" }}>
        <div className="h2">Debug</div>
        <div className="pre">{`effective_api_base: ${effectiveApi}\ndb_path: ${defaultDbPath}`}</div>
      </div>

      {err ? (
        <div className="card" style={{ background: "rgba(255,0,0,0.06)", marginTop: 12 }}>
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
