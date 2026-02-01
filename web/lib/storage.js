const KEY = "lopa_champ_pool_by_role_v1";

function defaultPool() {
  return { TOP: [], JUNGLE: [], MIDDLE: [], BOTTOM: [], UTILITY: [] };
}

function loadAll() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaultPool();
    const obj = JSON.parse(raw);
    const base = defaultPool();
    for (const k of Object.keys(base)) {
      const arr = Array.isArray(obj?.[k]) ? obj[k] : [];
      base[k] = Array.from(new Set(arr.map(x => parseInt(x, 10)).filter(Boolean)));
    }
    return base;
  } catch {
    return defaultPool();
  }
}

function saveAll(p) {
  localStorage.setItem(KEY, JSON.stringify(p));
}

export function loadRolePool(role) {
  const all = loadAll();
  return all?.[role] || [];
}

export function saveRolePool(role, ids) {
  const all = loadAll();
  all[role] = Array.from(new Set((ids || []).map(x => parseInt(x, 10)).filter(Boolean)));
  saveAll(all);
}
