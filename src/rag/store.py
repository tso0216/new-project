"""Chroma 向量庫的連線與索引載入。"""

import chromadb
from chromadb.api import ClientAPI
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

from config import config


def chroma_client() -> ClientAPI:
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(config.CHROMA_DIR))


def vector_store(client: ClientAPI) -> tuple[ChromaVectorStore, chromadb.Collection]:
    collection = client.get_or_create_collection(config.CHROMA_COLLECTION)
    return ChromaVectorStore(chroma_collection=collection), collection


def reset_collection(client: ClientAPI) -> None:
    if config.CHROMA_COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(config.CHROMA_COLLECTION)


def load_index() -> VectorStoreIndex:
    store, collection = vector_store(chroma_client())
    if collection.count() == 0:
        raise RuntimeError("向量庫是空的，請先執行：python src/main.py ingest")
    return VectorStoreIndex.from_vector_store(store)
