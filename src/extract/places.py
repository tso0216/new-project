"""Google Places API (New) Text Search：用景點名稱查 place_id、座標、營業時間等。

每次呼叫都會計費；field mask 含 regularOpeningHours，屬於較高的計費等級。
"""
import json

import httpx

from config import config

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ["id", "displayName", "location", "regularOpeningHours", "utcOffsetMinutes", "businessStatus",
          "primaryType", "types", "formattedAddress", "viewport", "googleMapsUri", "userRatingCount"]


def search(query: str, hint: str = "") -> dict | None:
    """回傳第一筆結果整理成 nodes 表的欄位；查無結果回傳 None。hint 是給人工查詢模式用的，這裡用不到。"""
    response = httpx.post(SEARCH_URL, timeout=30, headers={
        "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY or "",
        "X-Goog-FieldMask": ",".join(f"places.{f}" for f in FIELDS),
    }, json={"textQuery": query, "languageCode": "zh-TW", "pageSize": 1})
    if response.status_code != 200:
        raise RuntimeError(f"Google Places 回應 {response.status_code}：{response.text[:300]}")
    places = response.json().get("places") or []
    if not places:
        return None
    p = places[0]
    hours = p.get("regularOpeningHours")
    return {
        "place_id": p["id"],
        "google_name": p.get("displayName", {}).get("text"),
        "lat": p.get("location", {}).get("latitude"),
        "lon": p.get("location", {}).get("longitude"),
        "opening_hours": json.dumps(hours["periods"], ensure_ascii=False) if hours and "periods" in hours else None,
        "utc_offset_min": p.get("utcOffsetMinutes"),
        "business_status": p.get("businessStatus"),
        "primary_type": p.get("primaryType"),
        "types": json.dumps(p.get("types", []), ensure_ascii=False),
        "address": p.get("formattedAddress"),
        "viewport": json.dumps(p["viewport"]) if "viewport" in p else None,
        "maps_uri": p.get("googleMapsUri"),
        "rating_count": p.get("userRatingCount"),
        "resolved_by": "api",
    }
