"""RAG 問答用的 prompt。"""

from llama_index.core.schema import NodeWithScore

SYSTEM_PROMPT = (
    "你是一個根據參考資料回答問題的助理。"
    "請只根據使用者提供的參考資料回答，並使用與問題相同的語言作答。"
    "若資料中找不到答案，請直接說明找不到，不要自行編造。"
)


def build_prompt(question: str, nodes: list[NodeWithScore]) -> str:
    context = "\n\n".join(
        f"[{i}] ({n.node.metadata.get('file_name', '?')})\n{n.node.get_content()}"
        for i, n in enumerate(nodes, 1)
    )
    return f"參考資料：\n---------------------\n{context}\n---------------------\n\n問題：{question}"
