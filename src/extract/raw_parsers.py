"""把 data/raw/<站名>/ 的爬蟲結果解析成統一的「行程」結構，只做機械切分，不做判斷。

每個行程（trip）：
    {"trip_id", "source", "source_type", "url", "title",
     "months": 出團月份（旅行社的出發日期清單；遊記沒有結構化日期，留空由規則補）,
     "days": [{"day": int, "stops": [stop, ...], "lines": 當天區塊的原文行（旅行社才有）}],
     "text": 去空白後的全文（供驗證逐字引用）}
每個停留點（stop）：
    {"name_raw", "segment", "visit_type", "stay_min", "lat", "lon", "ext_id", "km_from_prev", "notes"}
    segment 是 name_raw 所在的整段原文（行程標題以「→」切開的一段），供規則判斷「自由活動建議」這類整段描述。
    notes 是掛在這個 stop 上的原文：可樂的景點注意事項、Funliday 作者寫的遊記段落。

哪些 stop 是景點、要合併成哪個 POI，由 build_graph.py 依 poi_rules.py 的人工規則決定。
"""

import html as htmllib
import json
import re
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

KM = re.compile(r"^約\s*([\d.]+)\s*km$")
BRACKET = re.compile(r"【\s*(.*?)\s*】")
AIRPORT = re.compile(r"(機場|空港)$")
PHOTO_CREDIT = re.compile(r"写真提供|照片取自|圖片來源|©")


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def new_stop(name_raw: str, **kw) -> dict:
    stop = {"name_raw": name_raw, "segment": name_raw, "visit_type": None, "stay_min": None, "lat": None, "lon": None,
            "ext_id": None, "km_from_prev": None, "notes": []}
    stop.update(kw)
    return stop


def split_route(route: str) -> list[dict]:
    """「A→約 6 km →【B】～說明→C」切成 stop；【】內是景點名，沒有【】就整段當名稱。"""
    stops, km = [], None
    for seg in route.split("→"):
        seg = seg.strip()
        if not seg:
            continue
        m = KM.match(seg)
        if m:
            km = float(m.group(1))
            continue
        for name in BRACKET.findall(seg) or [seg]:
            stops.append(new_stop(name.strip(), segment=seg, km_from_prev=km))
            km = None
    return stops


def trip_base(raw: dict, trip_id: str, source_type: str) -> dict:
    return {"trip_id": trip_id, "source": raw["source"], "source_type": source_type,
            "url": raw["url"], "title": raw["title"], "months": [], "days": [],
            "text": squash("|".join(raw["lines"]))}


def months_of(dates) -> list[int]:
    """"2026/11/21"、"2026/11" 之類的日期字串 → 排序後不重複的月份。"""
    return sorted({int(re.match(r"\d{4}[/-](\d{1,2})", d).group(1)) for d in dates})


# ---------- 可樂旅遊 ----------

def next_data(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads(f'"{c}"') for c in chunks)


def next_value(data: str, key: str):
    i = data.find(f'"{key}":')
    return json.JSONDecoder().raw_decode(data, i + len(key) + 3)[0] if i >= 0 else None


def colatour_sights(data: str) -> dict[tuple[int, str], dict]:
    """Next.js 內嵌資料裡的「全部景點介紹」：(day, 名稱) → {visit_type, content}。"""
    sight_list = next_value(data, "Sight_List")
    if not sight_list:
        return {}
    out = {}
    for d in sight_list:
        day = int(d["Day_No"].lstrip("D"))
        for s in d["SightContentsList"]:
            text = htmllib.unescape(re.sub(r"<[^>]+>", "", s.get("Sight_Content") or ""))
            out[(day, s["Sight_Name"])] = {"visit_type": s.get("MarkText") or None, "content": text}
    return out


def parse_colatour(raw: dict, html: str, trip_id: str) -> dict:
    trip = trip_base(raw, trip_id, "旅行社")
    data = next_data(html)
    sights = colatour_sights(data)
    trip["months"] = months_of(d["Tour_Date"] for m in next_value(data, "Departure_Date_List") or []
                               for d in m["Departure_Date_Detail"])
    trip["text"] += "|" + squash("|".join(s["content"] for s in sights.values()))
    lines = raw["lines"]
    start = lines.index("每日安排")
    end = lines.index("訂購須知", start)
    day, in_stops, current = None, False, None
    for line in lines[start:end]:
        m = re.fullmatch(r"D(\d+)", line)
        if m:
            day = {"day": int(m.group(1)), "stops": [], "lines": []}
            trip["days"].append(day)
            in_stops, current = True, None
            continue
        if day is None:
            continue
        day["lines"].append(line)
        if in_stops:
            if line in ("早", "午", "晚"):  # 餐食區開始，stop 清單結束
                in_stops = False
            elif line != "看景點圖文介紹":
                s = sights.get((day["day"], line), {})
                day["stops"].append(new_stop(line, visit_type=s.get("visit_type")))
            continue
        # 餐食、住宿之後：與某個 stop 同名的行開始的是該 stop 的注意事項
        named = next((s for s in day["stops"] if s["name_raw"] == line), None)
        if named:
            current = named
        elif current and not PHOTO_CREDIT.search(line) and line not in ("看景點圖文介紹", "/") \
                and not line.isdigit():
            current["notes"].append(line)
    for d in trip["days"]:
        for s in d["stops"]:
            s["notes"] = ["".join(s["notes"])] if s["notes"] else []
    return trip


# ---------- Funliday（Remix turbo-stream 內嵌資料）----------

TURBO_SPECIAL = {-1: None, -2: None, -3: None, -4: 0, -5: None, -6: None, -7: None}


def turbo_decode(html: str):
    chunks = [json.loads(c) for c in re.findall(r'streamController\.enqueue\((".*?")\);', html, re.S)]
    flat = list(json.loads(chunks[0]))
    promises = {}
    for c in chunks[1:]:
        m = re.match(r"P(\d+):(.*)", c, re.S)
        if m:
            promises[int(m.group(1))] = len(flat)
            flat.extend(json.loads(m.group(2)))
    memo = {}

    def hyd(i):
        if i < 0:
            return TURBO_SPECIAL.get(i)
        if i in memo:
            return memo[i]
        v = flat[i]
        if isinstance(v, dict):
            memo[i] = out = {}
            for k, vi in v.items():
                out[flat[int(k[1:])]] = hyd(vi)
            return out
        if isinstance(v, list):
            if v and v[0] == "P":
                return hyd(promises[v[1]]) if v[1] in promises else None
            if v and v[0] == "D":
                return v[1]
            memo[i] = out = []
            out.extend(hyd(x) for x in v)
            return out
        memo[i] = v
        return v

    return hyd(0)


def parse_funliday(raw: dict, html: str, trip_id: str) -> dict:
    trip = trip_base(raw, trip_id, "遊記")
    route = turbo_decode(html)["loaderData"]["routes/_layout.$userId.journals.$journalId._index"]
    detail = route["detail"]
    pois = [p for d in detail["days"] for p in d["pois"]]
    coords = detail.get("productRecallCoords") or []
    if len(coords) != len(pois):  # 對不上就不用座標，避免錯位
        coords = [{}] * len(pois)
    k = 0
    for d in detail["days"]:
        day = {"day": d["dayNumber"], "stops": [], "lines": []}
        for p in d["pois"]:
            c = coords[k]
            k += 1
            desc = (p.get("description") or "").strip()
            day["stops"].append(new_stop(
                p["name"].strip(), stay_min=p["stayTime"] // 60 if p.get("stayTime") else None,
                lat=c.get("lat"), lon=c.get("lon"), ext_id=p.get("poiBankId"),
                notes=[desc] if desc else []))
            trip["text"] += "|" + squash(desc)
        trip["days"].append(day)
    return trip


# ---------- 雄獅旅遊 ----------

def parse_liontravel(raw: dict, html: str, trip_id: str) -> dict:
    trip = trip_base(raw, trip_id, "旅行社")
    lines = raw["lines"]
    # 出發日期月曆（爬蟲只載入當月，所以通常只有一個月）
    trip["months"] = months_of(f"{a[:-1]}/{b[:-1]}" for a, b in zip(lines, lines[1:])
                               if re.fullmatch(r"\d{4}年", a) and re.fullmatch(r"\d{1,2}月", b))
    end = next(i for i, l in enumerate(lines) if l in ("防疫規範", "行程特殊提醒"))
    i = 0
    while i < end:
        if lines[i] == "DAY" and lines[i + 1].isdigit():
            n, i = int(lines[i + 1]), i + 2
            block_end = next((j for j in range(i, end) if lines[j] == "DAY"), end)
            # 標題可能被拆成多行（機場名單獨一行），連續收集含「→」或是機場名的行
            header = []
            while i < end and ("→" in lines[i] or (AIRPORT.search(lines[i]) and len(lines[i]) < 20)):
                header.append(lines[i])
                i += 1
            if not header:  # 沒有箭頭的一日遊（例：全日迪士尼、自由活動）
                header, i = [lines[i]], i + 1
            trip["days"].append({"day": n, "stops": split_route("→".join(header)),
                                 "lines": lines[i:block_end]})
            i = block_end
        else:
            i += 1
    return trip


# ---------- 山富旅遊 ----------

def parse_travel4u(raw: dict, html: str, trip_id: str) -> dict:
    trip = trip_base(raw, trip_id, "旅行社")
    m = re.search(r'<script[^>]*id="sorted_product_list"[^>]*>(.*?)</script>', html, re.S)
    if m:  # {"2026/11": [各梯次…], …}，只算這個行程（mgrup_cd）的梯次
        code = trip_id.removeprefix("travel4u_")
        trip["months"] = months_of(ym for ym, groups in json.loads(m.group(1)).items()
                                   if any(g.get("mgrup_cd") == code for g in groups))
    lines = [l.strip() for l in raw["lines"]]
    starts = [i for i, l in enumerate(lines) if re.fullmatch(r"DAY \d+", l)]
    end = next((i for i in range(starts[-1], len(lines)) if lines[i] == "額外費用"), len(lines))
    for i, j in zip(starts, starts[1:] + [end]):
        trip["days"].append({"day": int(lines[i][4:]), "stops": split_route(lines[i + 1]),
                             "lines": lines[i + 2:j]})
    return trip


PARSERS = {"colatour": parse_colatour, "funliday": parse_funliday,
           "liontravel": parse_liontravel, "travel4u": parse_travel4u}


def load_trips(raw_dir: Path = RAW_DIR) -> list[dict]:
    """依 (站名, 檔名) 排序解析所有行程；這個順序也決定 POI「先加入」的先後。"""
    trips = []
    for path in sorted(raw_dir.glob("*/*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        html_path = path.with_suffix(".html")
        html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
        trips.append(PARSERS[raw["source"]](raw, html, path.stem))
    return trips


if __name__ == "__main__":
    for t in load_trips():
        print(f"== {t['trip_id']}  {t['title']}")
        for d in t["days"]:
            print(f"  D{d['day']}: " + " → ".join(
                s["name_raw"] + (f" [{s['km_from_prev']}km]" if s["km_from_prev"] else "")
                + (f" ({s['stay_min']}m)" if s["stay_min"] else "")
                + (f" <{s['visit_type']}>" if s["visit_type"] else "") for s in d["stops"]))
