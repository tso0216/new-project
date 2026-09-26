"""痞客邦部落格文章爬蟲：抓取單篇文章，原始 HTML 與解析後的文章存到 data/raw/。

用法：python src/crawler/pixnet.py https://xxx.pixnet.net/blog/post/71199873
"""
import html as htmllib
import json
import re
import sys
import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
UA = "Mozilla/5.0 (research crawler; thesis project)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:  # 會自動跟隨轉址
        return r.read().decode("utf-8")


def extract_body(html: str) -> list[str]:
    """取出 article-content-inner 區塊並轉成逐行文字。"""
    seg = html[html.index('id="article-content-inner"'):]
    end = seg.find("創作者介紹")
    seg = seg[: end if end > 0 else len(seg)]
    seg = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", seg, flags=re.S)
    seg = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", seg)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", seg))
    lines = [l.strip() for l in text.split("\n")]
    return [l for l in lines[1:] if l]  # 第一行是殘留的 tag 屬性


def parse(url: str, html: str) -> dict:
    ld = next(json.loads(m) for m in re.findall(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S)
              if '"BlogPosting"' in m)
    return {
        "source": "pixnet",
        "url": url,
        "title": ld.get("headline"),
        "author": re.search(r"//([^.]+)\.pixnet\.net", url).group(1),
        "date_published": ld.get("datePublished"),
        "date_modified": ld.get("dateModified"),
        "category": ld.get("articleSection"),
        "lines": extract_body(html),
    }


def main(url: str):
    article_id = url.rstrip("/").split("/")[-1].split("-")[0]
    html = fetch(url)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"pixnet_{article_id}.html").write_text(html, encoding="utf-8")
    article = parse(url, html)
    (RAW_DIR / f"pixnet_{article_id}.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{article['title']} -> {len(article['lines'])} lines")


if __name__ == "__main__":
    main(sys.argv[1])
