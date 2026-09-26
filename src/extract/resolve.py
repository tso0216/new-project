"""POI 對應：LLM 給的景點 → 資料庫的 node_id。

依序：別名完全比對 → 模糊比對 → embedding → Google Places。前三步是為了少呼叫 API；
門檻刻意設嚴（寧可交給 Google），因為合錯了之後同名稱都會跟著錯，而且很難發現。
Google 回傳的 place_id 已在資料庫 → 用既有節點；否則建新節點。命中後把名稱存成別名，下次直接完全比對命中。
"""
import re
import unicodedata
from dataclasses import dataclass

import numpy as np
import opencc
from rapidfuzz import fuzz, process

from config import config
from extract import db, places
from extract.schema import Node

FUZZY_MIN = 90     # rapidfuzz fuzz.ratio（0–100）
EMBED_MIN = 0.92   # cosine

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]|【[^】]*】")
_CONVERTERS = [opencc.OpenCC("s2t"), opencc.OpenCC("jp2t")]  # 簡→繁、日文新字體→繁（浅→淺、横浜→橫濱）


def normalize(name: str) -> str:
    """別名的 key：全形轉半形、去括號與括號內文字、去空白、英文小寫、簡繁與日文字體統一。"""
    s = unicodedata.normalize("NFKC", name)  # （）→ ()、全形英數 → 半形
    stripped = _BRACKETS.sub("", s)
    s = stripped if stripped.strip() else s  # 整個名稱都在括號裡就保留
    s = re.sub(r"\s+", "", s).lower()
    for cc in _CONVERTERS:
        s = cc.convert(s)
    return s


@dataclass
class Match:
    node_id: int
    matched_by: str      # exact / fuzzy / embedding / place_id / google
    score: float | None


class Resolver:
    def __init__(self, conn):
        self.conn = conn
        self.google_cache: dict[str, dict | None] = {}  # 這次執行內查過的名稱（含查無結果）不再查
        self.google_calls = 0
        self.created: list[int] = []  # 這篇新建的節點，寫完文章後清掉沒被用到的
        self._model = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(config.EMBED_MODEL)
        return self._model.encode(texts, normalize_embeddings=True).astype(np.float32)

    def resolve(self, node: Node, trip_id: str, raw_names: list[str]) -> Match | None:
        """raw_names：可以拿來比對的 name_raw（呼叫端已排除被多個 node 共用的，例如「城崎海岸、門脇吊橋」）。
        查無結果回傳 None。"""
        key = normalize(node.poi_name)
        names = {key: node.poi_name} | {normalize(r): r for r in raw_names}

        for alias in names:
            if (node_id := db.node_by_alias(self.conn, alias)) is not None:
                return self._matched(Match(node_id, "exact", None), names, trip_id)

        aliases = db.all_aliases(self.conn)
        if aliases:
            best = process.extractOne(key, [a for a, _ in aliases], scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
            if best:
                return self._matched(Match(aliases[best[2]][1], "fuzzy", best[1]), names, trip_id)

        _, node_ids, matrix = db.alias_embeddings(self.conn)
        if node_ids:
            sims = matrix @ self.embed([key])[0]
            i = int(sims.argmax())
            if sims[i] >= EMBED_MIN:
                return self._matched(Match(node_ids[i], "embedding", float(sims[i])), names, trip_id)

        place = self._search(node.poi_name)
        if place is None:
            return None
        if (node_id := db.node_by_place_id(self.conn, place["place_id"])) is not None:
            return self._matched(Match(node_id, "place_id", None), names, trip_id)
        node_id = db.insert_node(self.conn, node.poi_name, place, node.poi_name)
        self.created.append(node_id)
        return self._matched(Match(node_id, "google", None), names, trip_id)

    def _search(self, query: str) -> dict | None:
        if query not in self.google_cache:
            self.google_calls += 1
            self.google_cache[query] = places.search(query)
        return self.google_cache[query]

    def _matched(self, match: Match, names: dict[str, str], trip_id: str) -> Match:
        new = [a for a in names if db.node_by_alias(self.conn, a) is None]
        for alias, vec in zip(new, self.embed(new) if new else []):
            db.insert_alias(self.conn, alias, match.node_id, names[alias], match.matched_by, match.score, trip_id, vec)
        return match
