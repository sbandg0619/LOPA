import { useEffect, useState } from "react";

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

export function useChampionCatalog() {
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("init");
  const [idToName, setIdToName] = useState({});
  const [nameToId, setNameToId] = useState({});

  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        setStatus("fetch versions");
        const versions = await fetchJson("https://ddragon.leagueoflegends.com/api/versions.json");
        const v = Array.isArray(versions) ? versions[0] : null;
        if (!v) throw new Error("no version");

        setStatus(`fetch champions ${v}`);
        const data = await fetchJson(`https://ddragon.leagueoflegends.com/cdn/${v}/data/ko_KR/champion.json`);
        const champs = data?.data || {};

        const _idToName = {};
        const _nameToId = {};
        for (const key of Object.keys(champs)) {
          const c = champs[key];
          const cid = parseInt(c?.key || "0", 10);
          const nm = String(c?.name || "");
          if (cid && nm) {
            _idToName[cid] = nm;
            _nameToId[nm] = cid;
          }
        }

        if (!alive) return;
        setIdToName(_idToName);
        setNameToId(_nameToId);
        setReady(true);
        setStatus(`ready (${v})`);
      } catch (e) {
        if (!alive) return;
        setReady(false);
        setStatus(`error: ${String(e?.message || e)}`);
      }
    })();

    return () => { alive = false; };
  }, []);

  return { ready, status, idToName, nameToId };
}
