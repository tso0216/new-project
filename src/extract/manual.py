"""人工查詢模式（main.py --manual）：取代 Google Places API，在終端機請使用者自己查、貼上結果。

每個要查的景點貼兩樣：
  1. place_id：到 Place ID Finder 搜尋後複製（跟之後的 API 相容，當節點的唯一 ID）
  2. Google 地圖網址：在 Google 地圖點開景點後複製網址列（程式從網址取出名稱與座標）
營業時間等其他欄位先留空，之後有金鑰再補。
"""
import re
from urllib.parse import quote, unquote_plus

import httpx

PLACE_ID_FINDER = "https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder"
MAPS_SEARCH = "https://www.google.com/maps/search/?api=1&query={}"


def parse_maps_url(url: str) -> tuple[str | None, float, float] | None:
    """Google 地圖網址 → (名稱, 緯度, 經度)；找不到座標回傳 None。分享用的短網址會先展開。"""
    if re.match(r"https?://(maps\.app\.goo\.gl|goo\.gl)/", url):
        url = str(httpx.get(url, follow_redirects=True, timeout=15).url)
    # data= 裡的 !3d緯度!4d經度 是景點本身的座標；@緯度,經度 是畫面中心，只在沒有前者時使用
    coords = re.findall(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url) or re.findall(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if not coords:
        return None
    name = re.search(r"/maps/place/([^/]+)", url)
    lat, lon = coords[-1]
    return (unquote_plus(name.group(1)) if name else None), float(lat), float(lon)


def search(query: str, hint: str) -> dict | None:
    """跟 places.search 一樣回傳 nodes 表的欄位；使用者直接按 Enter＝查不到，回傳 None。"""
    print(f"\n── 人工查詢：{query}\n{hint}")
    print(f"Google 地圖：{MAPS_SEARCH.format(quote(query))}")
    print(f"Place ID Finder：{PLACE_ID_FINDER}")
    while True:
        place_id = input("place_id（直接按 Enter＝查不到）：").strip()
        if not place_id:
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{10,}", place_id):
            break
        print("  place_id 格式不對，請重新貼上")
    while True:
        url = input("Google 地圖網址：").strip()
        parsed = parse_maps_url(url) if url else None
        if parsed:
            break
        print("  網址裡找不到座標：請在 Google 地圖點開景點後，複製網址列的網址")
    name, lat, lon = parsed
    print(f"  → {name}（{lat}, {lon}）")
    return {"place_id": place_id, "google_name": name, "lat": lat, "lon": lon, "maps_uri": url,
            "resolved_by": "manual"}
