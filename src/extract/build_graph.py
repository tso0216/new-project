"""data/raw → data/node.json、data/edge.json。

    python src/extract/build_graph.py          # 建圖並寫檔
    python src/extract/build_graph.py --check  # 只檢查規則與證據，不寫檔

流程：raw_parsers 切出每天的 stop 序列 → poi_rules 決定每個 stop 是哪個 POI（或略過）→
同一天內相鄰的 POI 連成一條邊（被略過的 stop 記在 via）。不跨天連邊。
每條邊是一次觀測（某個行程、某天、第幾段），同一對景點被多個行程走過就會有多條邊。
"""

import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from poi_rules import ADJACENT, ALIASES,DEFAULT_MODE, EDGE_NOTES, POIS, SKIP_SEGMENTS, STOP_MAP, TRIP_MONTHS  # noqa: E402
from raw_parsers import load_trips, squash  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[2] / "data"

# 旅行社原文裡「會遇到什麼問題」的句子：停駛、休館、預約、替代方案、退費…
CAVEAT = re.compile(r"如遇|若遇|如因|遇到|天候|停駛|停駅|休園|休館|改為|改前往|改搭|改乘|改去|改走|改用|改以|調整為"
                    r"|退費|退還|退回|預約|額滿|售完|定休|排隊|人數|無法|注意|評估")
TRANSPORT = re.compile(r"電車前往|電車往返|停車場|接駁巴士")  # 與「怎麼到這裡」有關的注意事項，也掛到進站的邊上
NOISE = re.compile(r"告知正確年齡|退費規則|不適用於嬰兒|嬰兒除外|退費金額於團體出發前|無法抗拒")  # 團費退費條款，不是現場會遇到的問題
HOURS = re.compile(r"⏰|營業時間|休園日|開放時間")
PHOTO = re.compile(r"照片提供|写真参照|画像参照|^（?\(?圖片來源")
STATION_REASONS = {"交通站點", "機場"}
MAX_TIP, MAX_STORY = 200, 800


def clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n] + "…"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？!])", text) if s.strip()]


def caveats(text: str) -> list[str]:
    out = []
    for s in sentences(text):
        s = s.removeprefix("【特別報告】").strip()
        if CAVEAT.search(s) and not NOISE.search(s) and not s.startswith("◎"):
            out.append(clip(s, MAX_TIP))
    return out


def story(note: str) -> str:
    """遊記段落去掉照片出處行。"""
    return clip("\n".join(l for l in note.splitlines() if not PHOTO.search(l.strip())).strip(), MAX_STORY)


def common_len(a: str, b: str) -> int:
    """最長共同子字串長度（標題行常把景點名寫得不完全一樣，例：「河口湖富士山全景瞭望纜車」）。"""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def segment_skip(stop: dict) -> str | None:
    return next((reason for pattern, reason in SKIP_SEGMENTS if re.search(pattern, stop["segment"])), None)


def resolve(stop: dict) -> dict:
    """回傳 {"pois": [...]} 或 {"skip": 原因} 或 {"transport": {...}}，另帶 as_area。"""
    reason = segment_skip(stop)
    if reason:
        return {"skip": reason}
    rule = STOP_MAP[stop["name_raw"]]
    if isinstance(rule, str):
        return {"pois": [rule], "as_area": False}
    if isinstance(rule, list):
        return {"pois": rule, "as_area": False}
    if "poi" in rule:
        return {"pois": rule["poi"], "as_area": rule.get("as_area", False)}
    return rule


def day_tips(trip: dict, day: dict) -> dict[int, list[str]]:
    """每個 stop（以 index 表示）的注意事項句子。
    可樂：已經掛在 stop.notes；雄獅／山富：依「標題行」判斷後面的句子屬於哪個 stop。"""
    tips = {i: [] for i in range(len(day["stops"]))}
    if trip["source"] == "colatour":
        for i, s in enumerate(day["stops"]):
            for note in s["notes"]:
                tips[i] += caveats(note)
        return tips
    if trip["source"] == "funliday":
        return tips
    keys = []
    for i, s in enumerate(day["stops"]):
        r = resolve(s)
        names = [s["name_raw"]] + r.get("pois", [])
        keys.append([squash(n) for n in names if len(squash(n)) >= 3])
    current = None
    for line in day["lines"]:
        if line in ("餐食", "住宿"):
            break
        sq = squash(line)
        if sq and len(sq) <= 60 and not sq.endswith("。"):  # 標題行：短、不是完整句子
            hit = [i for i, ks in enumerate(keys) if any(k in sq or sq in k for k in ks)] or \
                  [i for i, ks in enumerate(keys) if any(common_len(k, sq) >= 4 for k in ks)]
            if hit:
                current = hit[0]
                tips[current] += caveats(line)  # 標題本身也可能帶替代方案（例：「…，結束則改前往大石公園」）
                continue
        if current is None:  # 當天只有一個 stop 時（例：全日迪士尼），說明都屬於它
            current = 0 if len(day["stops"]) == 1 else None
        if current is not None:
            tips[current] += caveats(line)
    return tips


def build():
    trips = load_trips()
    missing = sorted({s["name_raw"] for t in trips for d in t["days"] for s in d["stops"]
                      if s["name_raw"] not in STOP_MAP and not segment_skip(s)})
    if missing:
        sys.exit("poi_rules.STOP_MAP 缺少以下 name_raw 的規則：\n" + "\n".join(f"  {m!r}" for m in missing))

    by_name = {name: {"poi_id": pid, "poi_name": name, "category": cat, "area": area}
               for pid, name, cat, area in POIS}
    unknown = sorted({p for r in STOP_MAP.values() if isinstance(r, (str, list, dict))
                      for p in ([r] if isinstance(r, str) else r if isinstance(r, list) else r.get("poi", []))
                      if p not in by_name})
    if unknown:
        sys.exit(f"STOP_MAP 用到 POIS 沒定義的名稱：{unknown}")
    if unknown := sorted(set(ALIASES) - set(by_name)):
        sys.exit(f"ALIASES 用到 POIS 沒定義的名稱：{unknown}")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    used_notes, errors = set(), []

    for trip in trips:  # 遊記的旅行月份來自人工規則（原文逐字驗證）
        rule = TRIP_MONTHS.get(trip["trip_id"])
        if rule:
            trip["months"] = rule["months"]
            errors += [f"TRIP_MONTHS {trip['trip_id']} 的 evidence 不是原文逐字片段：{ev[:30]}"
                       for ev in rule["evidence"] if squash(ev) not in trip["text"]]

    def node_of(name: str) -> dict:
        if name not in nodes:
            nodes[name] = {**by_name[name], "aliases": list(ALIASES.get(name, [])),"lat": None, "lon": None, "duration": None,
                           "duration_samples": [], "hours": [], "months": [], "source_count": 0, "url": [],
                           "evidence": [], "observations": [], "_trips": set()}
        return nodes[name]

    def add_evidence(n: dict, text: str, kind: str, url: str):
        if text and not any(e["text"] == text for e in n["evidence"]):
            n["evidence"].append({"text": text, "kind": kind, "url": url})

    for trip in trips:
        url, src = trip["url"], trip["source"]
        for day in trip["days"]:
            tips = day_tips(trip, day)
            prev = None  # 上一個 POI：{"name", "stop", "stay"}
            via, via_km, transport = [], [], None
            seq = 0
            for i, stop in enumerate(day["stops"]):
                r = resolve(stop)
                if "pois" not in r:
                    via.append(stop["name_raw"])
                    via_km.append(stop["km_from_prev"])
                    if "transport" in r:
                        transport = r["transport"]
                    elif r["skip"] in STATION_REASONS:
                        transport = transport or {"mode": "大眾運輸", "inferred": True}
                    continue
                for k, name in enumerate(r["pois"]):
                    n = node_of(name)
                    if n["lat"] is None and stop["lat"] is not None:
                        n["lat"], n["lon"] = stop["lat"], stop["lon"]
                    if url not in n["url"]:
                        n["url"].append(url)
                    n["_trips"].add(trip["trip_id"])
                    n["months"] = sorted(set(n["months"]) | set(trip["months"]))
                    n["observations"].append({"trip_id": trip["trip_id"], "months": trip["months"],
                                              "name_raw": stop["name_raw"], "visit_type": stop["visit_type"],
                                              "stay_min": stop["stay_min"], "as_area": r["as_area"]})
                    for tip in tips[i]:
                        add_evidence(n, tip, "旅行社注意事項", url)
                    for note in stop["notes"] if src == "funliday" else []:
                        add_evidence(n, story(note), "遊記", url)
                        n["hours"] += [h.strip() for h in note.splitlines() if HOURS.search(h)]

                    stay = stop["stay_min"] if k == 0 else None
                    if prev and prev["name"] == name:  # 同一個 POI 連續出現（例：江之島車站→江之島站）就合併
                        prev["stay"] = (prev["stay"] or 0) + (stay or 0) or None
                        prev["stop"] = stop
                        via, via_km, transport = [], [], None
                        continue
                    if prev:
                        seq += 1
                        edges.append(make_edge(trip, day, seq, prev, name, stop, k, via, via_km, transport,
                                               tips[i], used_notes, errors))
                        record_stay(nodes[prev["name"]], prev["stay"])
                    prev = {"name": name, "stop": stop, "stay": stay}
                    via, via_km, transport = [], [], None
            if prev:
                record_stay(nodes[prev["name"]], prev["stay"])

    for key in EDGE_NOTES.keys() - used_notes:
        errors.append(f"EDGE_NOTES {key} 沒有對應到任何邊")

    node_list = []
    for n in sorted(nodes.values(), key=lambda x: x["poi_id"]):
        n["source_count"] = len(n.pop("_trips"))
        samples = n["duration_samples"]
        n["duration"] = round(statistics.median(samples)) if samples else None
        n["hours"] = list(dict.fromkeys(n["hours"]))
        node_list.append(n)
    ids = {n["poi_name"]: n["poi_id"] for n in node_list}
    for e in edges:
        for end in ("from", "to"):
            e[end]["poi_id"] = ids[e[end]["poi_name"]]
    unused = [name for name in by_name if name not in nodes]
    if unused:
        errors.append(f"POIS 中沒被任何行程用到：{unused}")
    return node_list, edges, errors


def record_stay(n: dict, stay):
    if stay:
        n["duration_samples"].append(stay)


def make_edge(trip, day, seq, prev, name, stop, k, via, via_km, transport, to_tips, used_notes, errors):
    src, text = trip["source"], trip["text"]
    from_stop = prev["stop"]
    key = (trip["trip_id"], day["day"], from_stop["name_raw"], stop["name_raw"])
    note = EDGE_NOTES.get(key)
    mode, vehicle, duration = DEFAULT_MODE[src], None, None
    basis = "旅行社跟團，原文未寫交通方式，預設遊覽車" if mode else "原文未寫"
    if k > 0:
        mode, basis = "走路", "同一個行程項目拆出的相鄰景點"
    elif transport:
        mode, vehicle = transport["mode"], transport.get("vehicle")
        basis = "途經車站" if transport.get("inferred") else "原文明寫"
    elif any({prev["name"], name} <= group for group in ADJACENT):
        mode, basis = "走路", "同園區／步行範圍內（人工規則）"
    elif src == "funliday" and (from_stop["name_raw"].endswith("站") or stop["name_raw"].endswith("站")):
        mode, basis = "大眾運輸", "遊記起訖點記成車站"
    evidence = []
    if src != "funliday":  # 旅行社：兩端所在的行程標題片段就是「順序」的證據
        evidence = [from_stop["segment"], stop["segment"]] if k == 0 else [stop["segment"]]
        evidence = [clip(e, 120) for e in dict.fromkeys(evidence)]
    if note:
        used_notes.add(key)
        mode, basis = note.get("mode", mode), "原文明寫"
        vehicle = note.get("vehicle", vehicle)
        duration = note.get("duration_min")
        for ev in note["evidence"]:
            if squash(ev) not in text:
                errors.append(f"{key} 的 evidence 不是原文逐字片段：{ev[:30]}")
        evidence += note["evidence"]
    evidence += [t for t in to_tips if TRANSPORT.search(t)]
    legs = via_km + [stop["km_from_prev"]] if k == 0 else [None]
    return {
        "edge_id": None,
        "from": {"poi_id": None, "poi_name": prev["name"], "name_raw": from_stop["name_raw"],
                 "visit_type": from_stop["visit_type"]},
        "to": {"poi_id": None, "poi_name": name, "name_raw": stop["name_raw"], "visit_type": stop["visit_type"]},
        "mode": mode,
        "mode_inferred": mode is not None and basis != "原文明寫",
        "mode_basis": basis,
        "vehicle": vehicle,
        "duration_min": duration,
        "distance_km": sum(legs) if legs and all(x is not None for x in legs) else None,
        "via": list(via),
        "months": trip["months"],
        "trip_id": trip["trip_id"],
        "day": day["day"],
        "seq": seq,
        "source_type": trip["source_type"],
        "evidence": evidence,
        "url": trip["url"],
    }


def main():
    nodes, edges, errors = build()
    for i, e in enumerate(edges, 1):
        e["edge_id"] = f"E{i:04d}"
    for err in errors:
        print("ERROR", err)
    if errors:
        sys.exit(1)
    print(f"{len(nodes)} 個 POI、{len(edges)} 條邊")
    if "--check" in sys.argv:
        return
    for name, data in (("node.json", nodes), ("edge.json", edges)):
        (OUT_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"寫入 {OUT_DIR / name}")


if __name__ == "__main__":
    main()
