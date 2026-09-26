"""旅行社行程 observation 的驗證與彙整。

agent 只負責判斷（寫 legs/<PatternNo>.json，內容是 JSON 陣列，格式見 tour_extraction_prompt.md），
這支腳本負責機械檢查（證據與地名必須逐字出自原文）並補上來源欄位：
    python src/extract/tour_observations.py check [PatternNo ...]   # 驗證；有 ERROR 結束碼為 1
    python src/extract/tour_observations.py build                   # 全部驗證通過後彙整成 poi_edges.json
                                                                    # （只留 id、from、to、travel_mode、travel_duration、url）
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import config  # noqa: E402

ROOT = config.DATA_DIR / "tour" / "colatour"
MODES = {"遊覽車", "步行", "電車", "纜車", "船", "飛機", "計程車", "自駕", "大眾運輸", "unspecified"}
VISIT_TYPES = {"入內參觀", "下車拍照", "行車經過", None}
KEYS = {"day", "seq", "from", "to", "mode", "mode_inferred", "vehicle_raw",
        "duration_min", "cost_text", "evidence", "notes"}
TIME_WORDS = ("分", "小時", "時間")  # duration_min 有值時，evidence 至少要出現其中之一
MAX_EVIDENCE, MAX_EVIDENCE_CHARS, MAX_NOTES_CHARS = 3, 120, 80
NOT_A_PLACE = re.compile(r"自由活動|集合")  # 活動或集合點的描述，不是地名


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def load_itinerary(pn: str) -> dict:
    return json.loads((ROOT / "itinerary" / f"{pn}.json").read_text(encoding="utf-8"))


def haystacks(itin: dict) -> dict[int, str]:
    """每天可引用的原文（項目名稱＋說明＋航班城市），去空白後用 | 分隔，避免跨欄位湊出假子字串。"""
    flights = [squash(f"{f['from']}|{f['to']}") for way in itin["flights"].values() for f in way]
    return {d["day"]: "|".join([squash(s["name"] + "|" + s["text"]) for s in d["stops"]] + flights)
            for d in itin["days"]}


def endpoint_errors(ep, label: str, hay: str) -> list[str]:
    if not (isinstance(ep, dict) and set(ep) == {"name_raw", "visit_type"}):
        return [f"{label} 必須是 {{name_raw, visit_type}}"]
    errs = []
    if not (isinstance(ep["name_raw"], str) and ep["name_raw"].strip()):
        errs.append(f"{label}.name_raw 必須是非空字串")
    elif NOT_A_PLACE.search(ep["name_raw"]):
        errs.append(f"{label}.name_raw「{ep['name_raw']}」不是地名（自由活動、集合點都不可當端點）")
    elif squash(ep["name_raw"]) not in hay:
        errs.append(f"{label}.name_raw「{ep['name_raw']}」不是當天原文的逐字片段")
    if ep["visit_type"] not in VISIT_TYPES:
        errs.append(f"{label}.visit_type「{ep['visit_type']}」不合法")
    return errs


def leg_errors(leg: dict, hays: dict[int, str]) -> list[str]:
    if not isinstance(leg, dict) or set(leg) != KEYS:
        return [f"欄位必須剛好是 {sorted(KEYS)}（多或少：{sorted(set(leg) ^ KEYS) if isinstance(leg, dict) else '非物件'}）"]
    if not (isinstance(leg["day"], int) and leg["day"] in hays):
        return [f"day={leg['day']!r} 不在這份行程的天數內"]
    hay = hays[leg["day"]]
    errs = endpoint_errors(leg["from"], "from", hay) + endpoint_errors(leg["to"], "to", hay)
    if not isinstance(leg["seq"], int) or leg["seq"] < 1:
        errs.append("seq 必須是正整數")
    if leg["mode"] not in MODES:
        errs.append(f"mode「{leg['mode']}」不在允許清單")
    if not isinstance(leg["mode_inferred"], bool):
        errs.append("mode_inferred 必須是 true/false")
    elif leg["mode"] == "unspecified" and leg["mode_inferred"]:
        errs.append("mode 是 unspecified 時 mode_inferred 必須是 false")
    for key in ("vehicle_raw", "cost_text"):
        v = leg[key]
        if v is not None and not (isinstance(v, str) and squash(v) in hay):
            errs.append(f"{key}「{v}」必須是 null 或當天原文的逐字片段")
    ev = leg["evidence"]
    if not (isinstance(ev, list) and 1 <= len(ev) <= MAX_EVIDENCE and all(isinstance(e, str) and e.strip() for e in ev)):
        errs.append(f"evidence 必須是 1～{MAX_EVIDENCE} 個非空字串的陣列")
        ev = []
    for e in ev:
        if len(e) > MAX_EVIDENCE_CHARS:
            errs.append(f"evidence 片段超過 {MAX_EVIDENCE_CHARS} 字：{e[:20]}…")
        elif squash(e) not in hay:
            errs.append(f"evidence 不是當天原文的逐字片段：{e[:30]}")
    d = leg["duration_min"]
    if d is not None:
        if not (isinstance(d, int) and not isinstance(d, bool) and d > 0):
            errs.append("duration_min 必須是正整數或 null")
        elif not any(w in "".join(ev) for w in TIME_WORDS):
            errs.append("duration_min 有值，但 evidence 沒有任何寫出時間的片段（分／小時／時間）")
    if not isinstance(leg["notes"], str) or len(leg["notes"]) > MAX_NOTES_CHARS:
        errs.append(f"notes 必須是 ≤{MAX_NOTES_CHARS} 字的字串")
    if isinstance(leg["from"], dict) and isinstance(leg["to"], dict) and leg["from"].get("name_raw") == leg["to"].get("name_raw"):
        errs.append("from 與 to 相同")
    return errs


def covers(name: str, stop_name: str) -> bool:
    a, b = squash(name), squash(stop_name)
    return bool(a) and (a in b or b in a)


def check(pn: str) -> tuple[list[dict], list[str], list[str]]:
    """回傳 (legs, errors, warnings)。"""
    path = ROOT / "legs" / f"{pn}.json"
    if not path.exists():
        return [], [f"找不到 {path}"], []
    itin = load_itinerary(pn)
    hays = haystacks(itin)
    legs, errors, warnings = [], [], []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [], [f"{path.name} 不是合法 JSON：{e}"], []
    if not isinstance(raw, list):
        return [], [f"{path.name} 最外層必須是 JSON 陣列（每個元素一筆 leg）"], []
    for n, leg in enumerate(raw, 1):
        errs = leg_errors(leg, hays)
        errors += [f"第 {n} 筆：{e}" for e in errs]
        if not errs:
            legs.append(leg)

    by_day: dict[int, list[dict]] = {}
    for leg in legs:
        by_day.setdefault(leg["day"], []).append(leg)
    if legs != sorted(legs, key=lambda x: (x["day"], x["seq"])):
        errors.append("legs 必須依 (day, seq) 排序")
    for day, ls in by_day.items():
        if [x["seq"] for x in ls] != list(range(1, len(ls) + 1)):
            errors.append(f"day {day} 的 seq 必須是 1..{len(ls)} 連續")
        for a, b in zip(ls, ls[1:]):
            if a["to"]["name_raw"] != b["from"]["name_raw"]:
                warnings.append(f"day {day} seq {a['seq']}→{b['seq']} 銜接不上：「{a['to']['name_raw']}」≠「{b['from']['name_raw']}」")
    for d in itin["days"]:
        ls = by_day.get(d["day"], [])
        if not ls:
            warnings.append(f"day {d['day']} 沒有任何 leg")
        names = [x[k]["name_raw"] for x in ls for k in ("from", "to")]
        missed = [s["name"] for s in d["stops"] if not any(covers(n, s["name"]) for n in names)]
        if missed:
            warnings.append(f"day {d['day']} 未被任何 leg 涵蓋的項目：{missed}")
    return legs, errors, warnings


def to_edge(itin: dict, leg: dict) -> dict:
    """最終交付的邊，只有 id、from、to、travel_mode、travel_duration（分鐘）、url。
    證據、是否推斷、備註等細節留在 legs/<PatternNo>.json。"""
    src = itin["source"]
    return {
        "id": f"{src['agency']}-{src['pattern_no']}-d{leg['day']}-{leg['seq']:02d}",
        "from": leg["from"]["name_raw"],
        "to": leg["to"]["name_raw"],
        "travel_mode": leg["mode"],
        "travel_duration": leg["duration_min"],
        "url": src["url"],
    }


def pattern_numbers(args: list[str]) -> list[str]:
    return args or sorted(p.stem for p in (ROOT / "legs").glob("*.json"))


def cmd_check(args: list[str]) -> int:
    bad = 0
    for pn in pattern_numbers(args):
        legs, errors, warnings = check(pn)
        print(f"[{pn}] {len(legs)} 筆 leg，{len(errors)} 個 ERROR，{len(warnings)} 個 WARNING")
        for e in errors:
            print(f"  ERROR   {e}")
        for w in warnings:
            print(f"  WARNING {w}")
        bad += bool(errors)
    return 1 if bad else 0


def cmd_build() -> int:
    all_legs, edges, per_pn = [], [], {}
    for pn in pattern_numbers([]):
        legs, errors, _ = check(pn)
        if errors:
            print(f"[{pn}] 仍有 {len(errors)} 個 ERROR，先用 check 修正")
            return 1
        itin = load_itinerary(pn)
        per_pn[pn] = len(legs)
        all_legs += legs
        edges += [to_edge(itin, leg) for leg in legs]
    out = ROOT / "poi_edges.json"
    out.write_text(json.dumps(edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    modes = Counter((r["mode"], "推斷" if r["mode_inferred"] else "明寫") for r in all_legs)
    with_dur = sum(e["travel_duration"] is not None for e in edges)
    print(f"寫入 {out}：{len(edges)} 條邊 / {len(per_pn)} 個行程 {per_pn}")
    print(f"有 travel_duration：{with_dur}/{len(edges)}")
    for (mode, how), n in sorted(modes.items(), key=lambda kv: -kv[1]):
        print(f"  {mode:<8}{how} {n}")
    return 0


def main() -> None:
    cmd, *args = sys.argv[1:] or ["check"]
    sys.exit(cmd_build() if cmd == "build" else cmd_check(args))


if __name__ == "__main__":
    main()
