"""爬取背包客棧指定版面(與分類)的文章，將原文與留言轉成markdown存進SQLite。版面、分類等參數見 config/crawl_config.py。"""

import asyncio
import html
import random
import re
import sqlite3
from bs4 import BeautifulSoup
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError, RequestException

from config import crawl_config as config

BASE_URL = "https://www.backpackers.com.tw/forum/"
_prefix_query = f"&prefixid={config.CRAWLER_PREFIX_ID}" if config.CRAWLER_PREFIX_ID else ""
# 少了 order=desc 的話，翻到第2頁以後網站會回「頁面無效」
FORUM_LIST_URL = f"{BASE_URL}forumdisplay.php?f={config.CRAWLER_FORUM_ID}{_prefix_query}&order=desc"
DB_PATH = config.CRAWLER_DB_PATH
ON_EXISTING_OPTIONS = ("skip", "update")
REQUEST_RETRIES = 3
RETRY_BASE_WAIT = 10  # 秒，每次重試等待時間加倍：10、20、40
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_markdown_generator = DefaultMarkdownGenerator()
# User-Agent 由 impersonate 自動帶入，與模擬的 Chrome 版本一致，不要自己覆蓋
IMPERSONATE = "chrome"  # 模擬 Chrome 的 TLS/JA3 指紋與 HTTP/2 握手
_HEADERS = {"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            content TEXT NOT NULL
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


def thread_url(thread_id: int) -> str:
    return f"{BASE_URL}showthread.php?t={thread_id}"


def _cap(total: int, limit: int | None) -> int:
    return total if limit is None else min(total, limit)


async def fetch_text(client: AsyncSession, url: str) -> str:
    """送出GET請求並回傳內容；逾時、連線失敗或伺服器忙碌時等待後重試。"""
    for attempt in range(1, REQUEST_RETRIES + 2):
        await asyncio.sleep(random.uniform(config.CRAWLER_REQUEST_DELAY_MIN, config.CRAWLER_REQUEST_DELAY_MAX))
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        except RequestException as e:
            retryable = not isinstance(e, HTTPError) or e.response.status_code in RETRYABLE_STATUS
            if not retryable or attempt > REQUEST_RETRIES:
                raise
            wait = RETRY_BASE_WAIT * 2 ** (attempt - 1)
            print(f"  請求失敗（{type(e).__name__}），{wait} 秒後重試（{attempt}/{REQUEST_RETRIES}）: {url}")
            await asyncio.sleep(wait)


def list_page_url(page: int) -> str:
    return FORUM_LIST_URL if page == 1 else f"{FORUM_LIST_URL}&page={page}"


def extract_posts(thread_page_html: str) -> list[tuple[str | None, str]]:
    """把一個分頁上所有文章(樓主原文或留言)轉成 (發文時間, markdown)，依原本順序回傳。"""
    soup = BeautifulSoup(thread_page_html, "html.parser")
    posts = []
    for post in soup.select('div[id^="post_message_"]'):
        post_id = post["id"].removeprefix("post_message_")
        # 發文時間不在內文裡，而是在同一則留言標頭的 <span>2004-08-17, 21:58</span>
        time_span = soup.select_one(f"#td_post_{post_id} .postmsgarea > span")
        posted_at = time_span.get_text(strip=True).replace(", ", " ") if time_span else None
        markdown = _markdown_generator.generate_markdown(str(post)).raw_markdown.strip()
        posts.append((posted_at, markdown))
    return posts


def format_section(title: str, posted_at: str | None, markdown: str) -> str:
    time_line = f"時間：{posted_at}\n\n" if posted_at else ""
    return f"## {title}\n\n{time_line}{markdown}"


def extract_total_pages(thread_page_html: str) -> int:
    """從分頁導覽的連結中找出這篇文章總共有多少留言分頁(至少1頁)。"""
    page_numbers = re.findall(r"showthread\.php\?(?:s=\w+&)?t=\d+&page=(\d+)", html.unescape(thread_page_html))
    if not page_numbers:
        return 1
    return max(int(n) for n in page_numbers)


async def fetch_thread_markdown(
    client: AsyncSession, url: str, max_reply_pages: int | None
) -> str:
    """抓取一篇文章的樓主原文與留言分頁(最多 max_reply_pages 頁)，合併成一份markdown。"""
    first_page = await fetch_text(client, url)
    posts = extract_posts(first_page)
    total_pages = _cap(extract_total_pages(first_page), max_reply_pages)

    for page in range(2, total_pages + 1):
        posts.extend(extract_posts(await fetch_text(client, f"{url}&page={page}")))

    if not posts:
        return ""

    sections = [format_section("原文", *posts[0])]
    for i, reply in enumerate(posts[1:], start=1):
        sections.append(format_section(f"留言 {i}", *reply))
    return "\n\n---\n\n".join(sections)


async def crawl_list_pages(
    client: AsyncSession,
    conn: sqlite3.Connection,
    worker: int,
    list_pages: range,
    seen: set[int],
    max_articles: int | None,
    max_reply_pages: int | None,
    on_existing: str,
) -> None:
    """一個工作者負責的列表頁(例如 1、11、21…)：逐頁抓出文章ID，再逐篇抓取存檔。
    所有工作者共用同一個 seen，達到文章數上限就一起停止。"""
    for page in list_pages:
        list_html = await fetch_text(client, list_page_url(page))
        new_ids = [tid for tid in dict.fromkeys(map(int, extract_thread_ids(list_html))) if tid not in seen]
        if not new_ids:
            break

        for tid in new_ids:
            if max_articles is not None and len(seen) >= max_articles:
                return
            if tid in seen:  # 等待請求期間可能已被其他工作者處理
                continue
            seen.add(tid)
            exists = conn.execute("SELECT 1 FROM articles WHERE id = ?", (tid,)).fetchone() is not None
            if exists and on_existing == "skip":
                print(f"[{worker}] 略過(已存在): {tid}")
                continue
            url = thread_url(tid)
            content = await fetch_thread_markdown(client, url, max_reply_pages)
            conn.execute(
                """
                INSERT INTO articles (id, url, content) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET url = excluded.url, content = excluded.content
                """,
                (tid, url, content),
            )
            conn.commit()
            print(f"[{worker}] {'已更新' if exists else '已存'}: {tid} ({len(content)} 字)")

        print(f"[{worker}] ===== 列表第 {page} 頁完成 =====")


async def crawl_forum(
    max_articles: int | None = config.CRAWLER_MAX_ARTICLES,
    start_list_page: int = config.CRAWLER_START_LIST_PAGE,
    max_list_pages: int | None = config.CRAWLER_MAX_LIST_PAGES,
    max_reply_pages: int | None = config.CRAWLER_MAX_REPLY_PAGES,
    on_existing: str = config.CRAWLER_ON_EXISTING,
    workers: int = config.CRAWLER_WORKERS,
) -> None:
    if on_existing not in ON_EXISTING_OPTIONS:
        raise ValueError(f"CRAWLER_ON_EXISTING 只能是 {ON_EXISTING_OPTIONS}，目前是 {on_existing!r}")

    conn = init_db()
    try:
        async with AsyncSession(
            impersonate=IMPERSONATE,
            headers=_HEADERS,
            timeout=config.CRAWLER_TIMEOUT,
            proxy=config.CRAWLER_PROXY,
            max_clients=workers,
        ) as client:
            total_pages = extract_listing_total_pages(await fetch_text(client, list_page_url(1)))
            end_page = total_pages if max_list_pages is None else min(total_pages, start_list_page + max_list_pages - 1)
            print(f"列表共 {total_pages} 頁，這次爬第 {start_list_page}～{end_page} 頁，{workers} 個工作者同時進行")

            seen: set[int] = set()
            # 協程共用同一個執行緒，所以可以安全共用 conn 與 seen
            async with asyncio.TaskGroup() as tg:
                for i in range(workers):
                    pages = range(start_list_page + i, end_page + 1, workers)
                    tg.create_task(
                        crawl_list_pages(client, conn, i + 1, pages, seen, max_articles, max_reply_pages, on_existing)
                    )
    except* RequestException as eg:
        print(
            f"連線一直失敗，已停止爬取（{type(eg.exceptions[0]).__name__}）。\n"
            "已經存進資料庫的文章都會保留；把 CRAWLER_START_LIST_PAGE 設成還沒完成的最小列表頁，用 skip 模式重跑即可。"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(crawl_forum())
