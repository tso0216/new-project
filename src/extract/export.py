"""data/graph.db → data/node.json、data/edge.json（人工檢查、scratch/render_graph.py 用）。

    python src/extract/export.py

duration（停留分鐘中位數）、months（各篇月份聯集）、source_count（出現在幾篇）在這裡統計。
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 extract 可被 import

from extract import db

DATA = Path(__file__).resolve().parents[2] / "data"


def node_key(node_id: int) -> str:
    return f"N{node_id:04d}"  # 對應 nodes.node_id


def main():
    conn = db.connect(DATA / "graph.db")
    articles = {r["trip_id"]: dict(r, months=json.loads(r["months"])) for r in conn.execute("SELECT * FROM articles")}
    aliases = defaultdict(list)
    for r in conn.execute("SELECT node_id, raw FROM aliases ORDER BY rowid"):
        aliases[r["node_id"]].append(r["raw"])
    obs = defaultdict(list)
    for r in conn.execute("SELECT * FROM observations ORDER BY id"):
        obs[r["node_id"]].append(r)

    nodes, names = [], {}
    for r in conn.execute("SELECT * FROM nodes ORDER BY node_id"):
        names[r["node_id"]] = r["name"]
        observations = [{"trip_id": o["trip_id"], "months": articles[o["trip_id"]]["months"], "name_raw": o["name_raw"],
                         "visit_type": o["visit_type"], "stay_min": o["stay_min"], "as_area": bool(o["as_area"])}
                        for o in obs[r["node_id"]]]
        stays = [o["stay_min"] for o in observations if o["stay_min"] is not None]
        trips = list(dict.fromkeys(o["trip_id"] for o in observations))
        nodes.append({
            "poi_id": node_key(r["node_id"]),
            "poi_name": r["name"],
            "google_name": r["google_name"],
            "place_id": r["place_id"],
            "lat": r["lat"],
            "lon": r["lon"],
            "opening_hours": json.loads(r["opening_hours"]) if r["opening_hours"] else None,
            "utc_offset_min": r["utc_offset_min"],
            "business_status": r["business_status"],
            "primary_type": r["primary_type"],
            "types": json.loads(r["types"]) if r["types"] else [],
            "address": r["address"],
            "maps_uri": r["maps_uri"],
            "rating_count": r["rating_count"],
            "resolved_by": r["resolved_by"],
            "aliases": aliases[r["node_id"]],
            "duration": round(statistics.median(stays)) if stays else None,
            "months": sorted({m for o in observations for m in o["months"]}),
            "source_count": len(trips),
            "url": [articles[t]["url"] for t in trips],
            "observations": observations,
        })

    name_raw = {}  # (trip_id, node_id) → 該篇原文寫法
    for node_obs in obs.values():
        for o in node_obs:
            name_raw.setdefault((o["trip_id"], o["node_id"]), o["name_raw"])

    def end(trip_id, node_id):
        return {"poi_id": node_key(node_id), "poi_name": names[node_id], "name_raw": name_raw.get((trip_id, node_id))}

    edges = []
    for r in conn.execute("SELECT * FROM edges ORDER BY trip_id, day, seq"):
        a = articles[r["trip_id"]]
        edges.append({
            "edge_id": f"E{r['edge_id']:04d}",  # 對應 edges.edge_id
            "from": end(r["trip_id"], r["from_node"]),
            "to": end(r["trip_id"], r["to_node"]),
            "mode": r["mode"],
            "mode_inferred": bool(r["mode_inferred"]),
            "mode_basis": r["mode_basis"],
            "vehicle": r["vehicle"],
            "duration_min": r["duration_min"],
            "via": json.loads(r["via"]),
            "months": a["months"],
            "trip_id": r["trip_id"],
            "day": r["day"],
            "seq": r["seq"],
            "source_type": a["source_type"],
            "url": a["url"],
        })

    for name, rows in (("node.json", nodes), ("edge.json", edges)):
        (DATA / name).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"匯出 {len(nodes)} 個節點、{len(edges)} 條邊 → data/node.json、data/edge.json")


if __name__ == "__main__":
    main()
