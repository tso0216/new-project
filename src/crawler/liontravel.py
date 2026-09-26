"""雄獅旅遊（travel.liontravel.com）團體行程爬蟲：行程由前端渲染，需用 Chrome 取得 DOM。

用法：python src/crawler/liontravel.py "https://travel.liontravel.com/detail?NormGroupID=<uuid>"
"""
import json
import re
import sys

from browser import render_dom
from funliday import RAW_DIR, TextExtractor

START_MARKER = "每日行程"


def parse(url: str, html: str) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S).group(1).strip()
    ext = TextExtractor()
    ext.feed(html)
    lines = ext.lines
    start = lines.index(START_MARKER) if START_MARKER in lines else 0
    return {"source": "liontravel", "url": url, "title": title, "lines": lines[start:]}


def main(url: str):
    group_id = re.search(r"NormGroupID=([\w-]+)", url).group(1)
    html = render_dom(url)
    out_dir = RAW_DIR / "liontravel"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"liontravel_{group_id}.html").write_text(html, encoding="utf-8")
    article = parse(url, html)
    (out_dir / f"liontravel_{group_id}.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{article['title']} -> {len(article['lines'])} lines")
    return article


if __name__ == "__main__":
    main(sys.argv[1])
