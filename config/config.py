"""集中讀取 config/.env 的設定。"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name) or default)
    return p if p.is_absolute() else ROOT / p



# LLM（OpenAI）
OPENAI_API_KEY = os.getenv("OPEN_AI_API_KEY")
LLM_BASE_URL = "https://api.openai.com/v1"
LLM_MODEL = "gpt-6-luna"
LLM_MAX_TOKENS = 16000
LLM_MANUAL = False
# 推理強度：none / low / medium / high / xhigh / max
LLM_REASONING_EFFORT = "medium"

# Embedding
EMBED_MODEL = "BAAI/bge-base-zh-v1.5"

# Chroma
CHROMA_DIR = _path("CHROMA_DIR", "storage/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION") or "docs"

# 切塊與檢索
DATA_DIR = _path("DATA_DIR", "data")
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
TOP_K = 4

# 背包客棧爬蟲
CRAWLER_FORUM_ID = 43            # 版面ID（43 = 日本關東）
CRAWLER_PREFIX_ID = "transport"  # 分類（transport = 交通；None = 不篩選分類）
CRAWLER_MAX_ARTICLES = 1000     # 文章要查幾篇（None = 不限制）
CRAWLER_START_LIST_PAGE = 53     # 從文章列表第幾頁開始（1～29頁已爬完）
CRAWLER_MAX_LIST_PAGES = None    # 文章列表要查幾頁，從起始頁算起（None = 不限制）
CRAWLER_WORKERS = 5              # 同時爬幾個列表頁；第1個負責起始頁+0、+5、+10…，第2個負責+1、+6、+11…，以此類推
CRAWLER_MAX_REPLY_PAGES = None   # 每篇文章的留言要抓幾頁，第1頁含原文（None = 不限制）
CRAWLER_DB_PATH = _path("CRAWLER_DB_PATH", "data/backpackers.db")  # 資料庫位置（相對路徑以專案根目錄為準）
CRAWLER_FULL_DB_PATH = _path("CRAWLER_FULL_DB_PATH", "data/backpackers_full.db")  # backpackers_full.py（存HTML）的資料庫位置
CRAWLER_TIMEOUT = 15             # 每次請求的逾時秒數
CRAWLER_REQUEST_DELAY = 1        # 每次請求前等待的秒數（太密集會被網站封鎖IP）
CRAWLER_ON_EXISTING = "skip"     # 文章已存在時："skip" 略過；"update" 重新抓取並覆蓋
