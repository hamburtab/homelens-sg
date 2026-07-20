import json
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "osm"

# 官方 Overpass 镜像列表
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

HEADERS = {
    "Accept": "application/json, */*;q=0.8",
    "User-Agent": "OSM-SG-Crawler/1.0 (academic research project)",
    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
}

# 拆分为单个查询，逐一爬取
QUERIES = {
    "railway_station": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["railway"="station"](area.singapore);
        out geom;
    """,
    "bus_stop": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["highway"="bus_stop"](area.singapore);
        out geom;
    """,
    "mall": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["shop"="mall"](area.singapore);
        out geom;
    """,
    "supermarket": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["shop"="supermarket"](area.singapore);
        out geom;
    """,
    "convenience": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["shop"="convenience"](area.singapore);
        out geom;
    """,
    "park": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["leisure"="park"](area.singapore);
        out geom;
    """,
    "nature_reserve": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["leisure"="nature_reserve"](area.singapore);
        out geom;
    """,
    "sports_centre": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["leisure"="sports_centre"](area.singapore);
        out geom;
    """,
    "food_court": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="food_court"](area.singapore);
        out geom;
    """,
    "cafe": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="cafe"](area.singapore);
        out geom;
    """,
    "restaurant": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="restaurant"](area.singapore);
        out geom;
    """,
    "community_centre": """
        [out:json][timeout:180];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="community_centre"](area.singapore);
        out geom;
    """,
    "hospital": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="hospital"](area.singapore);
        out geom;
    """,
    "clinic": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="clinic"](area.singapore);
        out geom;
    """,
    "school": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="school"](area.singapore);
        out geom;
    """,
    "kindergarten": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="kindergarten"](area.singapore);
        out geom;
    """,
    "laundry": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["shop"="laundry"](area.singapore);
        out geom;
    """,
    "post_office": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="post_office"](area.singapore);
        out geom;
    """,
    "atm": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="atm"](area.singapore);
        out geom;
    """,
    "bank": """
        [out:json][timeout:120];
        area["ISO3166-1"="SG"]->.singapore;
        nwr["amenity"="bank"](area.singapore);
        out geom;
    """,
}


def fetch_query(name, query):
    """对单个查询尝试多个 Overpass 镜像"""
    for url in OVERPASS_URLS:
        try:
            # 方式1: form-encoded data + headers
            resp = requests.post(
                url,
                data={"data": query.strip()},
                headers=HEADERS,
                timeout=200,
            )
            if resp.status_code == 200 and resp.text.strip():
                return resp.json()

            # 方式2: 原始查询字符串作为 body
            resp = requests.post(
                url,
                data=query.strip().encode("utf-8"),
                headers={
                    "Accept": "application/json, */*;q=0.8",
                    "User-Agent": "OSM-SG-Crawler/1.0",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                timeout=200,
            )
            if resp.status_code == 200 and resp.text.strip():
                return resp.json()

        except Exception as e:
            print(f"    镜像 {url} 异常: {e}")
            continue

    return None


def download_osm_data():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    success_count = 0
    fail_count = 0

    for name, query in QUERIES.items():
        print(f"[{success_count + fail_count + 1}/{len(QUERIES)}] 正在抓取 {name} ...", end=" ", flush=True)

        data = fetch_query(name, query)

        if data is not None:
            elements_count = len(data.get("elements", []))
            filename = OUTPUT_DIR / f"osm_{name}.json"
            with filename.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ {elements_count} 条 → {filename}")
            success_count += 1
        else:
            print(f"❌ 所有镜像均失败")
            fail_count += 1

        # 礼貌延迟，避免触发 rate limit
        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"完成: 成功 {success_count}, 失败 {fail_count} / 共 {len(QUERIES)}")


if __name__ == "__main__":
    download_osm_data()
