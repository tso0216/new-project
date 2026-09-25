"""從 Chroma 取回與問題最相近的 chunk。"""

from llama_index.core.schema import NodeWithScore

from config import config
from rag import store


class Retriever:
    def __init__(self, top_k: int | None = None) -> None:
        self._retriever = store.load_index().as_retriever(
            similarity_top_k=top_k or config.TOP_K
        )

    def retrieve(self, query: str) -> list[NodeWithScore]:
        return self._retriever.retrieve(query)
