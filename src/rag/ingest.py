"""讀取文件 → 切塊 → Embedding → 寫入 Chroma。"""

from pathlib import Path

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex

from config import config
from rag import store


def ingest(data_dir: Path | None = None) -> tuple[int, int]:
    """讀取資料夾內所有文件，重建 Chroma collection。回傳 (文件數, chunk 數)。"""
    data_dir = data_dir or config.DATA_DIR
    documents = SimpleDirectoryReader(str(data_dir), recursive=True).load_data()

    client = store.chroma_client()
    # 每次重建，避免重複 ingest 造成重複的 chunk
    store.reset_collection(client)
    vector_store, collection = store.vector_store(client)

    VectorStoreIndex.from_documents(
        documents,
        storage_context=StorageContext.from_defaults(vector_store=vector_store),
        show_progress=True,
    )
    return len(documents), collection.count()
