import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 config/ 可被 import

from rag import embedding
from rag.ingest import ingest
from rag.retriever import Retriever
from service.rag_service import RAGService


def _print_sources(nodes, full: bool = False) -> None:
    print("\n--- 參考來源 ---")
    for i, n in enumerate(nodes, 1):
        name = n.node.metadata.get("file_name", "?")
        text = n.node.get_content().strip()
        if full:
            print(f"[{i}] {name}  (score={n.score:.3f})\n{text}\n")
        else:
            snippet = text.replace("\n", " ")[:80]
            print(f"[{i}] {name}  (score={n.score:.3f})  {snippet}…")


def _answer(service: RAGService, question: str) -> None:
    tokens, nodes = service.ask_stream(question)
    for token in tokens:
        print(token, end="", flush=True)
    print()
    _print_sources(nodes)


def main() -> None:
    parser = argparse.ArgumentParser(description="LlamaIndex + Chroma + LLM Gateway 簡易 RAG")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="讀取文件並建立向量索引")
    p_ingest.add_argument("--data", type=Path, help="文件資料夾")

    p_ask = sub.add_parser("ask", help="單次問答")
    p_ask.add_argument("question")

    sub.add_parser("chat", help="互動式問答")

    p_search = sub.add_parser("search", help="只做檢索，不呼叫 LLM")
    p_search.add_argument("query")
    p_search.add_argument("-k", "--top-k", type=int, help="取回的 chunk 數（預設用 config.TOP_K）")

    args = parser.parse_args()
    embedding.setup()

    if args.cmd == "ingest":
        n_docs, n_chunks = ingest(args.data)
        print(f"完成：{n_docs} 份文件 → {n_chunks} 個 chunk")
    elif args.cmd == "ask":
        _answer(RAGService(), args.question)
    elif args.cmd == "chat":
        service = RAGService()
        print("輸入問題開始對話（exit 離開）")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("exit", "quit"):
                break
            if q:
                _answer(service, q)
    elif args.cmd == "search":
        service = RAGService(retriever=Retriever(top_k=args.top_k))
        _print_sources(service.retrieve(args.query), full=True)


if __name__ == "__main__":
    main()
