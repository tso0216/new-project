"""可樂旅遊（tour.colatour.com.tw）團體行程爬蟲：用 crawl4ai 搜尋關鍵字，把前 N 個行程存成 Markdown。

用法：
    python src/crawler/colatour.py 東京 --limit 5          # 只留行程相關內容
    python src/crawler/colatour.py 東京 --limit 5 --full   # 整頁保留

輸出：data/raw/colatour/colatour_<PatternNo>.md，開頭是 YAML 資訊區（url、title、crawled_at、departure_months）。
「行程相關」＝ 標題與行程概要、行程特色、每日安排、訂購須知裡的「行前必讀」、全部景點介紹（會先點開），
不含出發日期／價格表、訂購須知的其他部分（小費說明、護照簽證、旅遊指南、出入境須知）與網站導覽列。
出團月份從頁面內嵌的 Next.js 資料讀出完整清單，不展開含航班、價格的出團表。
"""
import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "colatour"
SEARCH_URL = "https://tour.colatour.com.tw/search?KeyWord={}"
DELAY = 2  # 每個行程之間間隔（秒）

# 點開「全部景點介紹」對話框（有入內參觀／下車拍照／行車經過、景點說明與注意事項）。
# 「每日安排」「行前必讀」和這個對話框都沒有固定 id（頁面上另有刷卡分期的 dialog），先幫它們加上 id 再選取：
# 每日安排＝主欄裡含「Day Dn schedule」的子區塊；行前必讀＝訂購須知分頁裡以「行前必讀」為標題的區塊；
# 景點介紹＝以「景點介紹」開頭的 dialog。
EXPAND_JS = """
const main = document.getElementById('title')?.parentElement;
const daily = main && [...main.children].find(c => c.querySelector('[role=region][aria-label$=" schedule"]'));
if (daily) daily.id = 'daily-schedule';
const preTrip = [...document.querySelectorAll('#order-instructions [role=tabpanel] > div')]
  .find(d => d.firstElementChild?.textContent.trim() === '行前必讀');
if (preTrip) preTrip.id = 'pre-trip';
const findSights = () => [...document.querySelectorAll('[role=dialog]')].find(d => d.textContent.trim().startsWith('景點介紹'));
const btn = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '全部景點介紹');
if (btn) {
  btn.click();
  for (let i = 0; i < 50 && !findSights(); i++) await new Promise(r => setTimeout(r, 100));
  const sights = findSights();
  if (sights) sights.id = 'sight-intro';
}
"""
ITINERARY_ELEMENTS = ["#title", "#itinerary-feature", "#daily-schedule", "#pre-trip", "#sight-intro"]


def search_urls(html_links: list[dict]) -> list[str]:
    urls = [l["href"] for l in html_links if re.search(r"/itinerary\?PatternNo=\d+$", l["href"])]
    return list(dict.fromkeys(urls))


def departure_months(html: str) -> list[str]:
    """Next.js 內嵌資料的 Departure_Date_List → 排序後的 "YYYY/MM" 清單。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    data = "".join(json.loads(f'"{c}"') for c in chunks)
    i = data.find('"Departure_Date_List":')
    if i < 0:
        return []
    dates = json.JSONDecoder().raw_decode(data, i + len('"Departure_Date_List":'))[0]
    return sorted({d["Tour_Date"][:7] for m in dates for d in m["Departure_Date_Detail"]})


def front_matter(meta: dict) -> str:
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()] + ["---", ""]
    return "\n".join(lines)


async def crawl_tour(crawler: AsyncWebCrawler, url: str, full: bool) -> Path:
    config = CrawlerRunConfig(wait_until="networkidle", js_code=EXPAND_JS, delay_before_return_html=1,
                              exclude_all_images=True, verbose=False)
    if not full:  # 用 target_elements 而非 css_selector：只影響 Markdown，result.html 仍是整頁（出團月份要從裡面讀）
        config.target_elements = ITINERARY_ELEMENTS
    result = await crawler.arun(url, config=config)
    if not result.success:
        raise RuntimeError(result.error_message)
    if 'id="daily-schedule"' not in result.html:  # 版面改了就別存
        raise RuntimeError("找不到「每日安排」區塊")
    if 'id="sight-intro"' not in result.html:
        print(f"  注意：{url} 沒有展開到「全部景點介紹」")
    if 'id="pre-trip"' not in result.html:
        print(f"  注意：{url} 找不到「行前必讀」")
    title = re.search(r"<h1[^>]*>(.*?)</h1>", result.html, re.S)
    meta = {
        "source": "colatour",
        "url": url,
        "title": re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else result.metadata.get("title"),
        "crawled_at": datetime.now().isoformat(timespec="seconds"),
        "content": "整頁" if full else "行程相關",
        "departure_months": departure_months(result.html),
    }
    pattern_no = re.search(r"PatternNo=(\d+)", url).group(1)
    path = RAW_DIR / f"colatour_{pattern_no}.md"
    path.write_text(front_matter(meta) + result.markdown.raw_markdown, encoding="utf-8")
    return path


async def main(keyword: str, limit: int, full: bool):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    browser = BrowserConfig(chrome_channel="chrome", channel="chrome", verbose=False)  # 用本機 Google Chrome
    async with AsyncWebCrawler(config=browser) as crawler:
        search = await crawler.arun(SEARCH_URL.format(quote(keyword)), config=CrawlerRunConfig(
            wait_until="networkidle", scan_full_page=True, verbose=False))
        urls = search_urls(search.links["internal"])[:limit]
        print(f"搜尋「{keyword}」：取 {len(urls)} 個行程")
        for i, url in enumerate(urls, 1):
            if i > 1:
                await asyncio.sleep(DELAY)
            try:
                path = await crawl_tour(crawler, url, full)
                print(f"[{i}/{len(urls)}] {path.name}  {path.stat().st_size // 1024} KB")
            except Exception as e:  # 下架、逾時等，換下一個
                print(f"[{i}/{len(urls)}] 略過 {url}：{e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="可樂旅遊團體行程爬蟲")
    ap.add_argument("keyword", help="搜尋關鍵字，例如：東京")
    ap.add_argument("--limit", type=int, default=5, help="最多爬幾個行程（依搜尋結果順序）")
    ap.add_argument("--full", action="store_true", help="整頁保留，不裁切成行程相關內容")
    args = ap.parse_args()
    asyncio.run(main(args.keyword, args.limit, args.full))
