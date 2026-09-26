"""讀爬蟲存下的文章：拆出開頭的 front matter（每行 `key: <JSON 值>`，見 src/crawler/colatour.py）與內文。"""
import json
from pathlib import Path

# front matter 的 source → source_type；新增來源時加在這裡
SOURCE_TYPES = {
    "colatour": "旅行社",
    "liontravel": "旅行社",
    "travel4u": "旅行社",
    "pixnet": "遊記",
    "ptt": "遊記",
    "dcard": "遊記",
}


def read_article(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name} 開頭沒有 front matter")
    head, body = text[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        key, value = line.split(": ", 1)
        meta[key] = json.loads(value)
    return meta, body


def source_type(meta: dict) -> str:
    source = meta.get("source")
    if source not in SOURCE_TYPES:
        raise ValueError(f"不認得的 source「{source}」，請在 src/extract/article.py 的 SOURCE_TYPES 加上它")
    return SOURCE_TYPES[source]
