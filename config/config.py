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

