
```
data/ ──SimpleDirectoryReader──▶ SentenceSplitter ──HuggingFace Embedding──▶ Chroma (storage/chroma)
                                                                                 │ top-k
問題 ──Embedding──▶ 相似度檢索 ──▶ 組 prompt ──▶ LLMClient.chat()（Vercel AI Gateway）──▶ 回答 + 來源
```

## 快速開始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# 在 config/.env 填入 AI_GATEWAY_API_KEY（格式見 config/.env.example）
python src/main.py ingest            # 把 data/ 內的文件建成索引（每次會重建）
python src/main.py ask "特休可以遞延嗎？"
python src/main.py chat              # 互動模式
python src/main.py search "遠端工作"  # 只看檢索結果，不呼叫 LLM
```

## 目錄結構

```
new-project/
├── config/
│   ├── config.py          # 讀取 .env，集中匯出設定
│   ├── .env               # 實際設定（不進 git）
│   └── .env.example       # 設定範本
├── data/                  # 放要被檢索的文件（md、txt、pdf、docx…）
├── storage/chroma/        # Chroma 向量庫（自動產生，不進 git）
├── src/
│   ├── main.py            # CLI 入口
│   ├── rag/
│   │   ├── embedding.py   # Embedding 模型、切塊設定
│   │   ├── store.py       # Chroma 連線、載入索引
│   │   ├── ingest.py      # 文件 → 切塊 → 向量 → 寫入 Chroma
│   │   ├── retriever.py   # 相似度檢索
│   │   └── prompt.py      # System prompt、組 prompt
│   └── service/
│       ├── llm_client.py  # LLMClient：chat() / stream()，走 Vercel AI Gateway
│       └── rag_service.py # RAGService：檢索 → prompt → LLM
└── requirements.txt
```

依賴方向：`main → service → rag → config`。


