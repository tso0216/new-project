"""背包客棧爬蟲的設定。"""

from .config import _path

CRAWLER_FORUM_ID = 43            # 版面ID（43 = 日本關東）
CRAWLER_PREFIX_ID = "transport"  # 分類（transport = 交通；None = 不篩選分類）
CRAWLER_MAX_ARTICLES = 10000    # 文章要查幾篇（None = 不限制）
CRAWLER_START_LIST_PAGE = 290     # 從文章列表第幾頁開始（1～29頁已爬完）
CRAWLER_MAX_LIST_PAGES = None    # 文章列表要查幾頁，從起始頁算起（None = 不限制）
CRAWLER_WORKERS = 8              # 同時爬幾個列表頁；第1個負責起始頁+0、+5、+10…，第2個負責+1、+6、+11…，以此類推
CRAWLER_MAX_REPLY_PAGES = None   # 每篇文章的留言要抓幾頁，第1頁含原文（None = 不限制）
CRAWLER_DB_PATH = _path("CRAWLER_DB_PATH", "data/backpackers.db")  # 資料庫位置（相對路徑以專案根目錄為準）
CRAWLER_FULL_DB_PATH = _path("CRAWLER_FULL_DB_PATH", "data/backpackers_full.db")  # backpackers_full.py（存HTML）的資料庫位置
CRAWLER_TIMEOUT = 30             # 每次請求的逾時秒數（走Tor比較慢，建議30以上）
CRAWLER_PROXY = None  # 代理伺服器；Tor Browser 用 "socks5h://127.0.0.1:9150"（要先開著Tor Browser並連上Tor；socks5h 讓DNS也走Tor），None = 直接連線
CRAWLER_REQUEST_DELAY_MIN = 0    # 每次請求前隨機等待的最短秒數（固定間隔、太密集都容易被網站封鎖IP）
CRAWLER_REQUEST_DELAY_MAX = 1    # 每次請求前隨機等待的最長秒數
CRAWLER_ON_EXISTING = "skip"     # 文章已存在時："skip" 略過；"update" 重新抓取並覆蓋
