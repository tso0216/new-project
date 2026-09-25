"""RAG 問答服務：檢索 → 組 prompt → LLM 回答。"""

from collections.abc import Iterator

from llama_index.core.schema import NodeWithScore

from service.llm_client import LLMClient
from rag.prompt import SYSTEM_PROMPT, build_prompt
from rag.retriever import Retriever


class RAGService:
    def __init__(self, retriever: Retriever | None = None, llm: LLMClient | None = None) -> None:
        self.retriever = retriever or Retriever()
        self._llm = llm

    @property
    def llm(self) -> LLMClient:
        # 延後建立：只做檢索（search）時不需要 API key
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def retrieve(self, question: str) -> list[NodeWithScore]:
        return self.retriever.retrieve(question)

    def ask(self, question: str) -> tuple[str, list[NodeWithScore]]:
        """回傳 (完整回答, 參考來源)。"""
        nodes = self.retrieve(question)
        return self.llm.chat(build_prompt(question, nodes), system=SYSTEM_PROMPT), nodes

    def ask_stream(self, question: str) -> tuple[Iterator[str], list[NodeWithScore]]:
        """回傳 (文字片段, 參考來源)。"""
        nodes = self.retrieve(question)
        return self.llm.stream(build_prompt(question, nodes), system=SYSTEM_PROMPT), nodes
