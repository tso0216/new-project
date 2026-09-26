"""解析一篇文章：LLM 抽取 → 驗證（錯誤丟回 LLM）→ POI 對應（Google 查無結果丟回 LLM）→ 寫進資料庫。

只寫進 transaction、不 commit；commit／rollback 由呼叫端（main.py）決定。
"""
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from extract import db
from extract.article import read_article, source_type
from extract.resolve import Resolver
from extract.schema import Extraction
from extract.validate import tidy, validate
from service.llm_client import LLMClient

PROMPT_PATH = Path(__file__).with_name("per_article_prompt.md")
MAX_RETRY = 2  # 驗證失敗、Google 查無結果各自最多丟回 LLM 幾次


class ExtractError(Exception):
    """驗證重試用完仍失敗；detail 會寫進 data/extract_failures/。"""

    def __init__(self, message: str, detail: dict):
        super().__init__(message)
        self.detail = detail


@dataclass
class Result:
    nodes: int = 0
    new_nodes: int = 0
    edges: int = 0
    attempts: int = 0
    dropped: list[str] = field(default_factory=list)  # Google 重試用完仍查不到、被丟掉的景點


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def process_article(path: Path, parsed_path: str, conn, resolver: Resolver, llm: LLMClient) -> Result:
    """parsed_path：解析完要移過去的位置（相對專案根目錄），記在 articles.path。"""
    meta, body = read_article(path)
    trip_id = path.stem
    article = {"trip_id": trip_id, "source": meta["source"], "source_type": source_type(meta), "url": meta["url"],
               "title": meta.get("title"), "path": parsed_path}
    messages = [{"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
                {"role": "user", "content": path.read_text(encoding="utf-8")}]
    result = Result()
    resolver.created = []
    invalid_retries = unresolved_retries = 0

    while True:
        ext = llm.parse(messages, Extraction)
        result.attempts += 1
        tidy(ext)
        output = ext.model_dump_json()
        messages.append({"role": "assistant", "content": output})

        if errors := validate(ext, body):
            if invalid_retries == MAX_RETRY:
                raise ExtractError(f"驗證失敗（已重試 {MAX_RETRY} 次）", {"errors": errors, "llm_output": json.loads(output)})
            invalid_retries += 1
            messages.append({"role": "user", "content":
                             "你上一次的輸出有以下問題，請修正後輸出完整 JSON（不要只輸出修改的部分）：\n" + _numbered(errors)})
            continue

        # 被多個 node 共用的 name_raw（例如沒拆乾淨的「城崎海岸、門脇吊橋」）不拿來比對別名，以免把別的景點併進來
        raw_count = Counter(raw for n in ext.nodes for raw in {o.name_raw for o in n.observations})
        matches, unresolved = {}, []
        for n in ext.nodes:
            raws = sorted({o.name_raw for o in n.observations if raw_count[o.name_raw] == 1})
            if (m := resolver.resolve(n, trip_id, raws)) is None:
                unresolved.append(n)
            else:
                matches[n.poi_id] = m

        if unresolved and unresolved_retries < MAX_RETRY:
            unresolved_retries += 1
            messages.append({"role": "user", "content":
                             "以下景點在 Google 地圖查不到，請確認後輸出完整 JSON（不要只輸出修改的部分）：\n"
                             + _numbered([f"{n.poi_id}「{n.poi_name}」：名稱可能不是正式名稱，請改用通行的正式名稱"
                                          for n in unresolved])
                             + "\n若它其實不是景點，請刪掉這個 node 與相關的 edge。"})
            continue
        break

    result.dropped = [n.poi_name for n in unresolved]
    observations = [{"node_id": matches[n.poi_id].node_id, **o.model_dump()}
                    for n in ext.nodes if n.poi_id in matches for o in n.observations]

    # 改寫成資料庫的 node_id；丟掉連到查無結果景點的邊，以及兩端被判成同一地點的邊；seq 每天從 1 重編
    edges, seq = [], defaultdict(int)
    for e in sorted(ext.edges, key=lambda e: e.day):
        if e.from_ not in matches or e.to not in matches:
            continue
        src, dst = matches[e.from_].node_id, matches[e.to].node_id
        if src == dst:
            continue
        seq[e.day] += 1
        edges.append({**e.model_dump(by_alias=False, exclude={"from_", "to"}),
                      "from_node": src, "to_node": dst, "seq": seq[e.day]})

    article |= {"months": json.dumps(ext.months), "llm_model": llm.model, "attempts": result.attempts,
                "llm_output": output, "extracted_at": db.now()}
    db.replace_article(conn, article, observations, edges)
    db.delete_orphan_nodes(conn, resolver.created)

    result.nodes = len({m.node_id for m in matches.values()})
    result.new_nodes = len({m.node_id for m in matches.values()} & set(resolver.created))
    result.edges = len(edges)
    return result
