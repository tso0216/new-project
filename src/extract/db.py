"""SQLite（data/graph.db）：節點、別名、文章、觀測、邊。

連線用 autocommit=False：一篇文章的所有寫入在同一個 transaction，成功才 commit，失敗 rollback 整篇還原。
duration、node 的 months、source_count 不存，匯出或查詢時再從 observations 統計。
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  node_id          INTEGER PRIMARY KEY,
  name             TEXT NOT NULL,      -- 第一次出現時 LLM 給的 poi_name
  place_id         TEXT NOT NULL UNIQUE,
  google_name      TEXT,
  lat              REAL,
  lon              REAL,
  opening_hours    TEXT,               -- JSON（regularOpeningHours.periods）
  utc_offset_min   INTEGER,
  business_status  TEXT,
  primary_type     TEXT,
  types            TEXT,               -- JSON 陣列
  address          TEXT,
  viewport         TEXT,               -- JSON
  maps_uri         TEXT,
  rating_count     INTEGER,
  google_query     TEXT,
  resolved_by      TEXT,               -- api / manual（人工查詢：只有 place_id、名稱、座標，其他之後再補）
  resolved_at      TEXT
);

CREATE TABLE IF NOT EXISTS aliases (
  alias       TEXT PRIMARY KEY,        -- 正規化後的名稱
  node_id     INTEGER NOT NULL REFERENCES nodes ON DELETE CASCADE,
  raw         TEXT,                    -- 正規化前
  matched_by  TEXT,                    -- exact / fuzzy / embedding / google / place_id
  score       REAL,
  trip_id     TEXT,                    -- 第一次出現在哪篇
  embedding   BLOB                     -- float32 向量（已正規化，內積＝cosine）
);

CREATE TABLE IF NOT EXISTS articles (
  trip_id       TEXT PRIMARY KEY,
  source        TEXT,
  source_type   TEXT,
  url           TEXT,
  title         TEXT,
  path          TEXT,                  -- 解析完移到 data/parsed/ 後的位置
  months        TEXT,                  -- JSON 陣列，LLM 判斷
  llm_model     TEXT,
  attempts      INTEGER,               -- 用了幾次 LLM 呼叫
  llm_output    TEXT,                  -- 最後一次的 LLM 輸出，除錯用
  extracted_at  TEXT
);

CREATE TABLE IF NOT EXISTS observations (
  id          INTEGER PRIMARY KEY,
  trip_id     TEXT NOT NULL REFERENCES articles ON DELETE CASCADE,
  node_id     INTEGER NOT NULL REFERENCES nodes,
  name_raw    TEXT,
  visit_type  TEXT,
  stay_min    INTEGER,
  as_area     INTEGER
);

CREATE TABLE IF NOT EXISTS edges (
  edge_id        INTEGER PRIMARY KEY,
  trip_id        TEXT NOT NULL REFERENCES articles ON DELETE CASCADE,
  from_node      INTEGER NOT NULL REFERENCES nodes,
  to_node        INTEGER NOT NULL REFERENCES nodes,
  mode           TEXT,
  mode_inferred  INTEGER,
  mode_basis     TEXT,
  vehicle        TEXT,
  duration_min   INTEGER,
  via            TEXT,                 -- JSON 陣列
  day            INTEGER,
  seq            INTEGER,
  UNIQUE (trip_id, day, seq)
);

CREATE INDEX IF NOT EXISTS aliases_node ON aliases(node_id);
CREATE INDEX IF NOT EXISTS observations_node ON observations(node_id);
CREATE INDEX IF NOT EXISTS edges_trip ON edges(trip_id);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # 在 transaction 裡設定無效，所以先用 autocommit 連線
    conn.executescript(SCHEMA)
    conn.autocommit = False
    return conn


# ── 節點與別名 ──

def node_by_alias(conn: sqlite3.Connection, alias: str) -> int | None:
    row = conn.execute("SELECT node_id FROM aliases WHERE alias = ?", (alias,)).fetchone()
    return row["node_id"] if row else None


def node_by_place_id(conn: sqlite3.Connection, place_id: str) -> int | None:
    row = conn.execute("SELECT node_id FROM nodes WHERE place_id = ?", (place_id,)).fetchone()
    return row["node_id"] if row else None


def all_aliases(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    return [(r["alias"], r["node_id"]) for r in conn.execute("SELECT alias, node_id FROM aliases")]


def alias_embeddings(conn: sqlite3.Connection) -> tuple[list[str], list[int], np.ndarray]:
    rows = conn.execute("SELECT alias, node_id, embedding FROM aliases WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return [], [], np.empty((0, 0), dtype=np.float32)
    matrix = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    return [r["alias"] for r in rows], [r["node_id"] for r in rows], matrix


def insert_node(conn: sqlite3.Connection, name: str, place: dict, query: str) -> int:
    row = {"name": name, **place, "google_query": query, "resolved_at": now()}
    cols = ", ".join(row)
    cur = conn.execute(f"INSERT INTO nodes ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    return cur.lastrowid


def insert_alias(conn: sqlite3.Connection, alias: str, node_id: int, raw: str, matched_by: str,
                 score: float | None, trip_id: str, embedding: np.ndarray) -> None:
    conn.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (alias, node_id, raw, matched_by, score, trip_id, embedding.astype(np.float32).tobytes()))


def delete_orphan_nodes(conn: sqlite3.Connection, node_ids: list[int]) -> None:
    """重試過程中建了、但最後沒有任何觀測指向的節點（連同別名）刪掉。"""
    for node_id in node_ids:
        used = conn.execute("SELECT 1 FROM observations WHERE node_id = ? LIMIT 1", (node_id,)).fetchone()
        if not used:
            conn.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))


# ── 文章 ──

def replace_article(conn: sqlite3.Connection, article: dict, observations: list[dict], edges: list[dict]) -> None:
    """同一個 trip_id 重新解析時，先刪掉舊的文章、觀測與邊再寫入（節點與別名保留）。"""
    conn.execute("DELETE FROM articles WHERE trip_id = ?", (article["trip_id"],))
    conn.execute(f"INSERT INTO articles ({', '.join(article)}) VALUES ({', '.join('?' * len(article))})",
                 list(article.values()))
    for o in observations:
        conn.execute("INSERT INTO observations (trip_id, node_id, name_raw, visit_type, stay_min, as_area) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (article["trip_id"], o["node_id"], o["name_raw"], o["visit_type"], o["stay_min"], o["as_area"]))
    for e in edges:
        conn.execute("INSERT INTO edges (trip_id, from_node, to_node, mode, mode_inferred, mode_basis, vehicle, "
                     "duration_min, via, day, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (article["trip_id"], e["from_node"], e["to_node"], e["mode"], e["mode_inferred"],
                      e["mode_basis"], e["vehicle"], e["duration_min"], json.dumps(e["via"], ensure_ascii=False),
                      e["day"], e["seq"]))
