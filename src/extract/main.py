"""解析 data/raw/ 裡還沒解析的文章，寫進 data/graph.db。

    python src/extract/main.py            # 用 Google Places API 查景點
    python src/extract/main.py --manual   # 暫定模式：查景點那一步改成在終端機人工查、貼上結果（見 manual.py）

解析成功的文章移到 data/parsed/<來源>/，所以 data/raw/ 裡剩下的就是還沒解析的；
失敗的留在 data/raw/（下次執行會再試），原因寫在 data/extract_failures/<trip_id>.json。
Google 重試用完仍查不到的景點會被丟掉（連同相關的邊），文章照常寫入，丟掉的名稱也記在 extract_failures/。
要有行程的景點才建節點：沒有任何邊的景點（只出現在介紹、建議清單裡的）不建。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 讓 config/ 可被 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 extract、service 可被 import

from config import config
from extract import db, manual, places
from extract.per_article import ExtractError, process_article
from extract.resolve import Resolver
from service.llm_client import LLMClient

DATA = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA / "raw"
PARSED_DIR = DATA / "parsed"
FAILURE_DIR = DATA / "extract_failures"
DB_PATH = DATA / "graph.db"


def write_failure(trip_id: str, detail: dict) -> None:
    FAILURE_DIR.mkdir(parents=True, exist_ok=True)
    (FAILURE_DIR / f"{trip_id}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")


def main(manual_mode: bool):
    if not manual_mode and not config.GOOGLE_PLACES_API_KEY:
        sys.exit("缺少 GOOGLE_PLACES_API_KEY，請在 config/.env 設定，或用 --manual 人工查詢")
    paths = sorted(RAW_DIR.glob("*/*.md"))
    if not paths:
        print("data/raw/ 裡沒有待解析的文章")
        return
    print(f"待解析：{len(paths)} 篇")

    conn = db.connect(DB_PATH)
    resolver = Resolver(conn, manual.search if manual_mode else places.search)
    llm = LLMClient()
    for i, path in enumerate(paths, 1):
        trip_id = path.stem
        parsed_path = PARSED_DIR / path.parent.name / path.name
        try:
            result = process_article(path, str(parsed_path.relative_to(DATA.parent)), conn, resolver, llm)
            conn.commit()
        except KeyboardInterrupt:  # 人工查詢到一半想停：這篇還原，已完成的保留
            conn.rollback()
            print(f"\n已中斷：{path.name} 沒有寫入，留在 data/raw/")
            break
        except Exception as e:  # 驗證重試用完、API 錯誤等：整篇還原，留在 raw/ 下次再試
            conn.rollback()
            write_failure(trip_id, {"error": str(e), **(e.detail if isinstance(e, ExtractError) else {})})
            print(f"[{i}/{len(paths)}] 失敗 {path.name}：{e}")
            continue

        parsed_path.parent.mkdir(parents=True, exist_ok=True)
        path.rename(parsed_path)
        failure = FAILURE_DIR / f"{trip_id}.json"
        if result.dropped:
            write_failure(trip_id, {"error": "Google 地圖查不到，已丟掉這些景點與相關的邊", "dropped": result.dropped})
        elif failure.exists():
            failure.unlink()  # 之前失敗過，這次成功了
        print(f"[{i}/{len(paths)}] {path.name}：{result.nodes} 個景點（新增 {result.new_nodes}）、"
              f"{result.edges} 條邊、LLM {result.attempts} 次"
              + (f"、丟掉 {len(result.dropped)} 個查不到的景點：{'、'.join(result.dropped)}" if result.dropped else "")
              + (f"、略過 {len(result.unlinked)} 個沒有邊的景點" if result.unlinked else ""))
    print(f"{'人工查詢' if manual_mode else 'Google Places 呼叫'} {resolver.lookups} 次")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="解析 data/raw/ 裡還沒解析的文章")
    ap.add_argument("--manual", action="store_true", help="暫定模式：不用 Google Places API，改成人工查 place_id 與地圖網址")
    main(ap.parse_args().manual)
