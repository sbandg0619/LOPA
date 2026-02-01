import json
import os
import time
import requests

CACHE_PATH = "ddragon_champions_ko.json"

def _get_latest_ddragon_version(timeout=10) -> str:
    # 최신 Data Dragon 버전
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    return requests.get(url, timeout=timeout).json()[0]

def _download_champion_json(version: str, timeout=15) -> dict:
    # ko_KR 챔피언 목록
    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json"
    return requests.get(url, timeout=timeout).json()

def load_champions_ko(force_refresh: bool = False) -> dict:
    """
    반환:
      {
        "version": "15.24.1",
        "id_to_name": { 21: "미스 포츈", ... },
        "name_to_id": { "미스 포츈": 21, ... },
        "all_names": ["가렌", "갈리오", ...]  # 한글명 정렬
      }
    """
    latest = _get_latest_ddragon_version()

    if not force_refresh and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("version") == latest and "id_to_name" in cached and "name_to_id" in cached:
                return cached
        except Exception:
            pass

    raw = _download_champion_json(latest)
    data = raw.get("data", {})

    id_to_name = {}
    name_to_id = {}

    for champ in data.values():
        # champ["key"] = "21" (championId)
        cid = int(champ["key"])
        ko_name = champ["name"]
        id_to_name[cid] = ko_name
        name_to_id[ko_name] = cid

    all_names = sorted(name_to_id.keys())

    out = {
        "version": latest,
        "fetched_at": int(time.time()),
        "id_to_name": id_to_name,
        "name_to_id": name_to_id,
        "all_names": all_names,
    }

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    return out
