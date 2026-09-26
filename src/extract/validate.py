"""檢查 LLM 抽取結果的內容（欄位、型別、列舉值已由 schema 保證）。

    python src/extract/validate.py <llm輸出.json> <文章.md>   # 單獨檢查一份輸出

validate() 回傳錯誤清單（空＝通過），錯誤訊息會原樣丟回 LLM 要它修正，所以要寫出位置與正確做法。
"""
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 extract 可被 import

from extract.schema import Extraction

# mode_basis → (mode 必須是, mode_inferred 必須是)；"原文明寫" 的 mode 只要不是 null
BASIS_RULES = {
    "原文明寫": ("非 null", False),
    "同園區步行範圍": ("走路", True),
    "旅行社跟團預設遊覽車": ("自駕", True),
    "途經車站": ("大眾運輸", True),
    "遊記起訖點記成車站": ("大眾運輸", True),
    "原文未寫": (None, False),
}


def tidy(ext: Extraction) -> None:
    """程式能直接修的就修，不丟回 LLM：months 排序去重。"""
    ext.months = sorted(set(ext.months))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate(ext: Extraction, body: str) -> list[str]:
    errors = []
    if bad := [m for m in ext.months if not 1 <= m <= 12]:
        errors.append(f"months 只能是 1–12 的整數，出現了 {bad}")

    ids = [n.poi_id for n in ext.nodes]
    for i, n in enumerate(ext.nodes):
        if not re.fullmatch(r"P\d{3}", n.poi_id):
            errors.append(f'nodes[{i}].poi_id "{n.poi_id}" 格式錯誤，應為 "P" + 3 位數，例如 P001')
        if not n.observations:
            errors.append(f"{n.poi_id}（{n.poi_name}）沒有 observations，至少要有一筆")
    for pid in sorted({p for p in ids if ids.count(p) > 1}):
        errors.append(f"poi_id {pid} 重複，每個 node 要有不同的 poi_id")

    names: dict[str, str] = {}
    for n in ext.nodes:
        if n.poi_name in names:
            errors.append(f"{names[n.poi_name]} 與 {n.poi_id} 都叫「{n.poi_name}」，同一景點只建一個 node，請把 observations 合併到同一個 node")
        names.setdefault(n.poi_name, n.poi_id)

    text = _compact(body)
    for n in ext.nodes:
        for j, o in enumerate(n.observations):
            if _compact(o.name_raw) not in text:
                errors.append(f"{n.poi_id}.observations[{j}].name_raw「{o.name_raw}」在原文找不到，請逐字照抄原文的寫法")
            if o.stay_min is not None and o.stay_min <= 0:
                errors.append(f"{n.poi_id}.observations[{j}].stay_min 是 {o.stay_min}，必須是正整數或 null")

    known = set(ids)
    for i, e in enumerate(ext.edges):
        for end in ("from_", "to"):
            if getattr(e, end) not in known:
                errors.append(f"edges[{i}].{end.rstrip('_')} 是 {getattr(e, end)}，但 nodes 裡沒有這個 poi_id")
        if e.from_ == e.to:
            errors.append(f"edges[{i}] 起點和終點都是 {e.to}，不可以建 A → A 的邊")
        if e.day < 1:
            errors.append(f"edges[{i}].day 是 {e.day}，必須 ≥ 1")
        if e.duration_min is not None and e.duration_min <= 0:
            errors.append(f"edges[{i}].duration_min 是 {e.duration_min}，必須是正整數或 null")
        mode, inferred = BASIS_RULES[e.mode_basis]
        if mode == "非 null" and e.mode is None:
            errors.append(f"edges[{i}] mode_basis 是「原文明寫」，mode 不可以是 null")
        elif mode != "非 null" and e.mode != mode:
            errors.append(f"edges[{i}] mode_basis 是「{e.mode_basis}」，mode 應為 {json.dumps(mode, ensure_ascii=False)}，目前是 {json.dumps(e.mode, ensure_ascii=False)}")
        if e.mode_inferred != inferred:
            errors.append(f"edges[{i}] mode_basis 是「{e.mode_basis}」，mode_inferred 應為 {str(inferred).lower()}")
        if e.mode_basis == "原文未寫" and e.vehicle is not None:
            errors.append(f"edges[{i}] mode_basis 是「原文未寫」，vehicle 應為 null（原文有寫交通工具就不是「原文未寫」）")
    return errors


def main(output_path: Path, article_path: Path) -> int:
    from extract.article import read_article

    _, body = read_article(article_path)
    try:
        ext = Extraction.model_validate_json(output_path.read_text(encoding="utf-8"))
    except ValidationError as e:
        print(f"格式錯誤：\n{e}")
        return 1
    tidy(ext)
    errors = validate(ext, body)
    for i, err in enumerate(errors, 1):
        print(f"{i}. {err}")
    print(f"{len(ext.nodes)} 個 node、{len(ext.edges)} 條 edge：" + (f"{len(errors)} 個錯誤" if errors else "通過"))
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
