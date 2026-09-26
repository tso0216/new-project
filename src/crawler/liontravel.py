"""雄獅旅遊（travel.liontravel.com）團體行程爬蟲：搜尋關鍵字，把前 N 個商品的每個行程版本存成 Markdown。

用法：
    python src/crawler/liontravel.py 東京 --limit 5          # 只留行程相關內容
    python src/crawler/liontravel.py 東京 --limit 5 --full   # 整頁保留

同一個商品（NormGroupID）常有好幾個行程版本（TourID），各自對應不同出發日期，景點順序也可能不同，
所以每個版本各存一檔：data/raw/liontravel/liontravel_<NormGroupID>_<TourID>.md。
開頭是 YAML 資訊區（url、title、crawled_at、content、departure_months、product_id、variant_id、variant_count）；
同一個 product_id 的檔案內容大多重複，之後解析時要避免重複計算。
「行程相關」＝ 標題、行程特色、每日行程、行程特殊提醒、行程備註，
不含出發日期／價格表、航班、防疫規範、安全守則、團體航班規定、旅遊資訊（簽證、小費等）與推薦行程。

商品清單、各版本與出發日期取自網站前端呼叫的 JSON API（搜尋頁一次只顯示 10 筆、出發月曆一次只顯示一個月）；
行程內容則用 crawl4ai 開啟該版本某個出發日的頁面，頁面會顯示該出發日所屬版本的行程。
"""
import argparse
import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "liontravel"
SEARCH_API = "https://search.liontravel.com/json/searchtravel"
DETAIL_API = "https://travel.liontravel.com/detail/{}"
DETAIL_URL = "https://travel.liontravel.com/detail?NormGroupID={}&GroupID={}"
UA = "Mozilla/5.0"
PAGE_SIZE = 20
DELAY = 2  # 每個頁面之間間隔（秒）

# 標題（body 直下的 h1）、行程特色、每日行程、行程特殊提醒、行程備註
ITINERARY_ELEMENTS = ["body > h1", "#feature", "#schedules", "#notes", "#itineraryNote"]
SCHEDULE_READY = "js:() => !!document.querySelector('#schedules h3')"  # 每日行程是另外載入的


def fetch_json(req: urllib.request.Request, tries: int = 3):
    """API 偶爾回 Cloudflare 522 之類的暫時錯誤，隔幾秒重試；最後一次失敗就讓例外往上拋。"""
    for _ in range(tries - 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.URLError:
            time.sleep(3)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_json(url: str):
    return fetch_json(urllib.request.Request(url, headers={"User-Agent": UA}))


def post_json(url: str, payload: dict):
    return fetch_json(urllib.request.Request(url, data=json.dumps(payload).encode(),
                                             headers={"User-Agent": UA, "Content-Type": "application/json"}))


def search_products(keyword: str, limit: int) -> list[str]:
    """搜尋 API（BuList=T 是團體）→ 依搜尋結果順序、不重複的 NormGroupID。"""
    ids, page = [], 1
    while len(ids) < limit:
        query = urlencode({"Keyword": keyword, "BuList": "T", "Page": page, "PageSize": PAGE_SIZE})
        data = get_json(f"{SEARCH_API}?{query}")["DataDetail"]
        for item in data["DataList"]:
            m = re.match(r"https://travel\.liontravel\.com/detail\?NormGroupID=([\w-]+)", item["ProductURL"])
            if m and m.group(1) not in ids:
                ids.append(m.group(1))
        if not data["DataList"] or page * PAGE_SIZE >= data["Total"]:
            break
        page += 1
    return ids[:limit]


def tour_variants(product_id: str) -> list[tuple[str, str, list[str]]]:
    """商品的各行程版本 → [(TourID, 該版本最早一團的 GroupID, 出團月份 "YYYY/MM" 清單)]，依最早出發日排序。"""
    info = post_json(DETAIL_API.format("tourinfojson"), {"NormGroupID": product_id, "TourSource": "Lion"})
    groups = post_json(DETAIL_API.format("groupcalendarjson"), {
        "NormGroupID": product_id, "GoDateStart": info["AllMinGoDate"], "GoDateEnd": info["AllMaxGoDate"],
        "TourID": "", "preferairlines": "", "TourSource": "Lion"})
    by_tour = defaultdict(list)
    for g in sorted(groups, key=lambda g: g["Date"]):  # Date 形如 "2026/10/09"
        by_tour[g["TourID"]].append(g)
    missing = [t["TourID"] for t in info["TourIDList"] if t["TourID"] not in by_tour]
    if missing:
        print(f"  注意：{product_id} 的版本 {', '.join(missing)} 沒有出發日期，無法開啟，略過")
    return [(tour_id, gs[0]["ID"], sorted({g["Date"][:7] for g in gs})) for tour_id, gs in by_tour.items()]


def front_matter(meta: dict) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


async def crawl_variant(crawler: AsyncWebCrawler, product_id: str, tour_id: str, group_id: str,
                        months: list[str], variant_count: int, full: bool) -> Path:
    url = DETAIL_URL.format(product_id, group_id)
    config = CrawlerRunConfig(wait_until="networkidle", wait_for=SCHEDULE_READY, delay_before_return_html=1,
                              exclude_all_images=True, verbose=False)
    if not full:  # target_elements 只影響 Markdown，result.html 仍是整頁（標題要從裡面讀）
        config.target_elements = ITINERARY_ELEMENTS
    result = await crawler.arun(url, config=config)
    if not result.success:
        raise RuntimeError(result.error_message)
    title = re.search(r"<h1[^>]*>(.*?)</h1>", result.html, re.S)
    meta = {
        "source": "liontravel",
        "url": url,
        "title": re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else result.metadata.get("title"),
        "crawled_at": datetime.now().isoformat(timespec="seconds"),
        "content": "整頁" if full else "行程相關",
        "departure_months": months,
        "product_id": product_id,
        "variant_id": tour_id,
        "variant_count": variant_count,
    }
    path = RAW_DIR / f"liontravel_{product_id}_{tour_id}.md"
    path.write_text(front_matter(meta) + result.markdown.raw_markdown, encoding="utf-8")
    return path


async def main(keyword: str, limit: int, full: bool):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    products = search_products(keyword, limit)
    print(f"搜尋「{keyword}」：取 {len(products)} 個商品")
    browser = BrowserConfig(chrome_channel="chrome", channel="chrome", verbose=False)  # 用本機 Google Chrome
    async with AsyncWebCrawler(config=browser) as crawler:
        pages = 0
        for i, product_id in enumerate(products, 1):
            try:
                variants = tour_variants(product_id)
            except Exception as e:  # 下架、API 格式改變等，換下一個
                print(f"[{i}/{len(products)}] 略過 {product_id}：{e}")
                continue
            for tour_id, group_id, months in variants:
                if pages:
                    await asyncio.sleep(DELAY)
                pages += 1
                try:
                    path = await crawl_variant(crawler, product_id, tour_id, group_id, months, len(variants), full)
                    print(f"[{i}/{len(products)}] {path.name}  {path.stat().st_size // 1024} KB")
                except Exception as e:
                    print(f"[{i}/{len(products)}] 略過 {product_id} 版本 {tour_id}：{e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="雄獅旅遊團體行程爬蟲")
    ap.add_argument("keyword", help="搜尋關鍵字，例如：東京")
    ap.add_argument("--limit", type=int, default=5, help="最多爬幾個商品（依搜尋結果順序；每個商品的各版本都會存）")
    ap.add_argument("--full", action="store_true", help="整頁保留，不裁切成行程相關內容")
    args = ap.parse_args()
    asyncio.run(main(args.keyword, args.limit, args.full))
