"""山富旅遊（travel4u.com.tw）團體行程爬蟲：抓單篇行程，原始 HTML 與解析結果存到 data/raw/。

行程內容以 JSON 字串（HTML 片段）放在 <script id="tour_content"> 裡，不需執行 JS。
用法：python src/crawler/travel4u.py https://www.travel4u.com.tw/group/itinerary/GNI02TRA10/
"""
import json
import re
import sys
import urllib.request

from funliday import RAW_DIR, TextExtractor

UA = "Mozilla/5.0"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def html_to_lines(fragment: str) -> list[str]:
    ext = TextExtractor()
    ext.feed(fragment)
    return ext.lines


def parse(url: str, html: str) -> dict:
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    m = re.search(r'<script id="tour_content"[^>]*>(.*?)</script>', html, re.S)
    lines = html_to_lines(json.loads(m.group(1))) if m else []
    return {
        "source": "travel4u",
        "url": url,
        "title": title,
        "lines": lines,
    }


def main(url: str):
    tour_id = url.rstrip("/").split("/")[-1]
    html = fetch(url)
    out_dir = RAW_DIR / "travel4u"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"travel4u_{tour_id}.html").write_text(html, encoding="utf-8")
    article = parse(url, html)
    (out_dir / f"travel4u_{tour_id}.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{article['title']} -> {len(article['lines'])} lines")
    return article


if __name__ == "__main__":
    main(sys.argv[1])
