"""批次爬取各站「東京」行程，每站 5 篇，存到 data/raw/<站名>/。

用法：python src/crawler/crawl_tokyo.py [funliday|travel4u|colatour|liontravel ...]
"""
import re
import sys
import time
import urllib.request
from html import unescape
from urllib.parse import quote

import colatour
import funliday
import liontravel
import travel4u
from browser import render_dom

PER_SITE = 5
DELAY = 2  # 每次請求間隔（秒）

FUNLIDAY_SITEMAP = "https://www.funliday.com/sitemap.xml"


def dedupe(items):
    return list(dict.fromkeys(items))


def funliday_urls():
    """sitemap 索引 → 各分頁 sitemap → 所有遊記網址（約 5 千篇，不分城市；是不是東京由 crawl() 抓下來後判斷）。"""
    index = funliday.fetch(FUNLIDAY_SITEMAP)
    urls = []
    for sub in re.findall(r"<loc>(.*?)</loc>", index):
        urls += re.findall(r"<loc>(https://www\.funliday\.com/[^/<]+/journals/\d+)</loc>", funliday.fetch(sub))
    return dedupe(urls)


def travel4u_urls():
    xml = travel4u.fetch("https://www.travel4u.com.tw/sitemap-group-itinerary.xml")
    ids = dedupe(re.findall(r"/group/itinerary/(TYO[A-Z0-9]+)", xml))
    return [f"https://www.travel4u.com.tw/group/itinerary/{i}/" for i in ids]


def colatour_urls():
    html = render_dom("https://tour.colatour.com.tw/search?KeyWord=東京", budget_ms=20000, timeout=30)
    return dedupe(unescape(u) for u in re.findall(r'href="(https://tour\.colatour\.com\.tw/itinerary\?PatternNo=\d+)"', html))


def liontravel_urls():
    html = render_dom("https://search.liontravel.com/" + quote("東京") + "?taglist=grp", budget_ms=20000, timeout=30)
    ids = dedupe(re.findall(r'detail\?NormGroupID=([0-9a-f-]{36})', html))
    return [f"https://travel.liontravel.com/detail?NormGroupID={i}" for i in ids]


SITES = {
    "funliday": (funliday.main, funliday_urls),
    "travel4u": (travel4u.main, travel4u_urls),
    "colatour": (colatour.main, colatour_urls),
    "liontravel": (liontravel.main, liontravel_urls),
}


def crawl(site: str):
    crawler, get_urls = SITES[site]
    got = 0
    for url in get_urls():
        if got >= PER_SITE:
            break
        t0 = time.time()
        try:
            article = crawler(url)
        except Exception as e:  # 下架、逾時等，換下一篇
            print(f"  skip {url}: {e}")
            continue
        finally:
            time.sleep(DELAY)
        if "東京" in (article["title"] or "") or "東京" in " ".join(article["lines"][:200]):
            got += 1
        else:
            for f in (funliday.RAW_DIR / site).glob("*"):  # 刪掉剛寫入的檔，不然 build_graph 會把非東京行程也建進圖
                if f.stat().st_mtime >= t0:
                    f.unlink()
            print(f"  非東京，略過: {url}")
    print(f"[{site}] {got}/{PER_SITE}")


if __name__ == "__main__":
    for s in sys.argv[1:] or SITES:
        crawl(s)
