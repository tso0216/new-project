"""可樂旅遊（tour.colatour.com.tw）團體行程爬蟲：行程由 Next.js 前端渲染，需用 Chrome 取得 DOM。

用法：python src/crawler/colatour.py "https://tour.colatour.com.tw/itinerary?PatternNo=245524"
"""
import json
import re
import sys

from browser import render_dom
from funliday import RAW_DIR, TextExtractor

START_MARKER = "行程概要"


def parse(url: str, html: str) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S).group(1).strip()
    ext = TextExtractor()
    ext.feed(html)
    lines = ext.lines
    start = lines.index(START_MARKER) if START_MARKER in lines else 0
    return {"source": "colatour", "url": url, "title": title, "lines": lines[start:]}


def main(url: str):
    pattern_no = re.search(r"PatternNo=(\d+)", url).group(1)
    html = render_dom(url)
    out_dir = RAW_DIR / "colatour"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"colatour_{pattern_no}.html").write_text(html, encoding="utf-8")
    article = parse(url, html)
    (out_dir / f"colatour_{pattern_no}.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{article['title']} -> {len(article['lines'])} lines")
    return article


if __name__ == "__main__":
    main(sys.argv[1])
