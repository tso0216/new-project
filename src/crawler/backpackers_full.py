"""爬取背包客棧指定版面(與分類)的文章，將每一頁(含留言分頁)的完整原始HTML存進SQLite。版面、分類等參數見 config/config.py。"""

import asyncio
import html
import re
import sqlite3

import httpx

from config import config

BASE_URL = "https://www.backpackers.com.tw/forum/"
_prefix_query = f"&prefixid={config.CRAWLER_PREFIX_ID}" if config.CRAWLER_PREFIX_ID else ""
# 少了 order=desc 的話，翻到第2頁以後網站會回「頁面無效」
FORUM_LIST_URL = f"{BASE_URL}forumdisplay.php?f={config.CRAWLER_FORUM_ID}{_prefix_query}&order=desc"
DB_PATH = config.CRAWLER_FULL_DB_PATH
ON_EXISTING_OPTIONS = ("skip", "update")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            thread_id INTEGER NOT NULL,
            page INTEGER NOT NULL,
            url TEXT NOT NULL,
            html TEXT NOT NULL,
            PRIMARY KEY (thread_id, page)
        )
        """
    )
    conn.commit()
    return conn


def extract_thread_ids(list_html: str) -> list[str]:
    """從一頁版面列表頁抓出文章ID(依出現順序，可能包含重複，例如置頂文章)。"""
    return re.findall(r"showthread\.php\?(?:s=\w+&)?t=(\d+)", html.unescape(list_html))


def extract_listing_total_pages(list_html: str) -> int:
    """從版面列表頁的分頁導覽找出總共有多少頁列表(至少1頁)。"""
    page_numbers = re.findall(r"forumdisplay\.php\?[^\"'>]*\bpage=(\d+)", html.unescape(list_html))
    if not page_numbers:
        return 1
    return max(int(n) for n in page_numbers)


def thread_page_url(thread_id: int, page: int) -> str:
    url = f"{BASE_URL}showthread.php?t={thread_id}"
    return url if page == 1 else f"{url}&page={page}"


def _cap(total: int, limit: int | None) -> int:
    return total if limit is None else min(total, limit)


async def collect_thread_ids(
    client: httpx.AsyncClient, max_articles: int | None, max_list_pages: int | None
) -> list[int]:
    """依序翻頁版面列表，蒐集不重複的文章ID，達到文章數或列表頁數上限就停止。"""
    seen: set[int] = set()
    ids: list[int] = []
    page = 1
    total_pages = 1
    limit = max_articles if max_articles is not None else float("inf")

    while len(ids) < limit and page <= total_pages:
        list_url = FORUM_LIST_URL if page == 1 else f"{FORUM_LIST_URL}&page={page}"
        response = await client.get(list_url)
        response.raise_for_status()

        if page == 1:
            total_pages = _cap(extract_listing_total_pages(response.text), max_list_pages)

        found_new = False
        for tid in map(int, extract_thread_ids(response.text)):
            if tid in seen:
                continue
            seen.add(tid)
            found_new = True
            ids.append(tid)
            if len(ids) >= limit:
                break

        if not found_new:
            break
        page += 1

    return ids


def extract_total_pages(thread_page_html: str) -> int:
    """從分頁導覽的連結中找出這篇文章總共有多少留言分頁(至少1頁)。"""
    page_numbers = re.findall(r"showthread\.php\?(?:s=\w+&)?t=\d+&page=(\d+)", html.unescape(thread_page_html))
    if not page_numbers:
        return 1
    return max(int(n) for n in page_numbers)


async def fetch_thread_pages(
    client: httpx.AsyncClient, thread_id: int, max_reply_pages: int | None
) -> list[tuple[int, str, str]]:
    """抓取一篇文章每個分頁(最多 max_reply_pages 頁)的完整原始HTML，回傳 (頁碼, 網址, HTML)。"""
    pages = []
    total_pages = 1
    page = 1
    while page <= total_pages:
        url = thread_page_url(thread_id, page)
        response = await client.get(url)
        response.raise_for_status()
        if page == 1:
            total_pages = _cap(extract_total_pages(response.text), max_reply_pages)
        pages.append((page, url, response.text))
        page += 1
    return pages


async def crawl_forum(
    max_articles: int | None = config.CRAWLER_MAX_ARTICLES,
    max_list_pages: int | None = config.CRAWLER_MAX_LIST_PAGES,
    max_reply_pages: int | None = config.CRAWLER_MAX_REPLY_PAGES,
    on_existing: str = config.CRAWLER_ON_EXISTING,
) -> None:
    if on_existing not in ON_EXISTING_OPTIONS:
        raise ValueError(f"CRAWLER_ON_EXISTING 只能是 {ON_EXISTING_OPTIONS}，目前是 {on_existing!r}")

    conn = init_db()
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=config.CRAWLER_TIMEOUT) as client:
            thread_ids = await collect_thread_ids(client, max_articles, max_list_pages)
            print(f"抓到 {len(thread_ids)} 篇文章ID")

            for tid in thread_ids:
                exists = conn.execute("SELECT 1 FROM pages WHERE thread_id = ?", (tid,)).fetchone() is not None
                if exists and on_existing == "skip":
                    print(f"略過(已存在): {tid}")
                    continue
                pages = await fetch_thread_pages(client, tid, max_reply_pages)
                # 整篇一起寫入；覆蓋時先刪舊頁，避免留言頁數變少時殘留舊分頁
                with conn:
                    conn.execute("DELETE FROM pages WHERE thread_id = ?", (tid,))
                    conn.executemany(
                        "INSERT INTO pages (thread_id, page, url, html) VALUES (?, ?, ?, ?)",
                        [(tid, page, url, page_html) for page, url, page_html in pages],
                    )
                print(f"{'已更新' if exists else '已存'}: {tid} ({len(pages)} 頁)")
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(crawl_forum())
