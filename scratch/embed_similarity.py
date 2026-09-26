"""用 embedding 比對「雷門」和「淺草寺」的相似度（cosine similarity）。

    python scratch/embed_similarity.py
    python scratch/embed_similarity.py 雷門 淺草寺          # 自訂兩段文字
    python scratch/embed_similarity.py --model 模型名稱      # 換模型

預設比兩組：只有名稱、名稱加簡短描述。另外附上一個不相關的景點（東京晴空塔）當對照，
方便判斷分數的相對高低。
"""

import argparse

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

DEFAULT_MODEL = "BAAI/bge-m3"

NAMES = {"雷門": "雷門", "淺草寺": "淺草寺", "東京晴空塔": "東京晴空塔"}
DESCS = {
    "雷門": "雷門是淺草寺的正門，門前掛著巨大的紅燈籠，是淺草的象徵與熱門拍照地標。",
    "淺草寺": "淺草寺是東京最古老的寺廟，從雷門穿過仲見世通商店街即可抵達本堂。",
    "東京晴空塔": "東京晴空塔高 634 公尺，是世界最高的自立式電波塔，可購票登上展望台俯瞰東京。",
}


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)


def compare(embed, title, texts):
    keys = list(texts)
    vecs = {k: embed.get_text_embedding(texts[k]) for k in keys}
    print(f"\n== {title} ==")
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            print(f"{a} vs {b}: {cosine(vecs[a], vecs[b]):.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("texts", nargs="*", help="要比對的兩段文字（省略則用內建的雷門／淺草寺）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    embed = HuggingFaceEmbedding(model_name=args.model)
    print(f"model: {args.model}")

    if len(args.texts) == 2:
        compare(embed, "自訂文字", {"A": args.texts[0], "B": args.texts[1]})
        return

    compare(embed, "只用名稱", NAMES)
    compare(embed, "名稱＋描述", DESCS)


if __name__ == "__main__":
    main()
