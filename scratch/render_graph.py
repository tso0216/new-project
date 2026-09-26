"""data/node.json、data/edge.json → scratch/graph.html（單檔、用瀏覽器直接打開）。

    python scratch/render_graph.py

節點 = POI，畫成圓圈、圈內數字是 source_count（圈的大小也依它），名稱寫在圈下，顏色依 area；有證據段落的節點加黑框。
同一對景點的多條邊（多次觀測）合併成一條，粗細依觀測次數，顏色依 mode，推測的交通方式畫虛線。
點節點或邊，右側會列出原始觀測、證據與出處。
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MODE_COLOR = {"自駕": "#4a7fd6", "走路": "#3aa36b", "大眾運輸": "#d9822b", None: "#999999"}
AREA_PALETTE = ["#e15759", "#4e79a7", "#f28e2b", "#76b7b2", "#59a14f", "#edc948",
                "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


def build():
    nodes = json.loads((DATA / "node.json").read_text())
    edges = json.loads((DATA / "edge.json").read_text())

    area_count = defaultdict(int)
    for n in nodes:
        area_count[n["area"]] += 1
    top_areas = sorted(area_count, key=lambda a: -area_count[a])[: len(AREA_PALETTE) - 1]
    area_color = {a: AREA_PALETTE[i] for i, a in enumerate(top_areas)}
    other = AREA_PALETTE[-1]

    vis_nodes = [{
        "id": n["poi_id"],
        "label": n["poi_name"],
        "color": area_color.get(n["area"], other),
        "has_ev": bool(n["evidence"]),
        "count": n["source_count"],
        "title": f'{n["poi_name"]}｜{n["area"]}｜{n["category"]}｜{n["source_count"]} 個來源',
        "raw": n,
    } for n in nodes]

    # 同一對景點（有方向）＋同一 mode 合併
    merged = defaultdict(list)
    for e in edges:
        merged[(e["from"]["poi_id"], e["to"]["poi_id"], e["mode"])].append(e)
    vis_edges = []
    for (src, dst, mode), obs in merged.items():
        inferred = all(o["mode_inferred"] for o in obs)
        has_ev = any(o["evidence"] for o in obs)
        vis_edges.append({
            "id": "|".join(o["edge_id"] for o in obs),
            "from": src, "to": dst,
            "mode": mode or "未知",
            "sources": sorted({o["source_type"] for o in obs}),
            "color": MODE_COLOR.get(mode, MODE_COLOR[None]),
            "dashes": inferred,
            "width": 2 + 2 * (len(obs) - 1),
            "title": f'{mode or "未知"}｜{len(obs)} 次觀測' + ("（推測）" if inferred else "") + ("｜有證據" if has_ev else ""),
            "raw": obs,
        })

    stats = {
        "nodes": len(nodes), "edges": len(edges), "merged_edges": len(vis_edges),
        "trips": len({e["trip_id"] for e in edges}),
        "isolated": len({n["poi_id"] for n in nodes} - {e["from"]["poi_id"] for e in edges} - {e["to"]["poi_id"] for e in edges}),
    }
    legend = {"area": area_color, "other": other, "mode": {k or "未知": v for k, v in MODE_COLOR.items()}}
    html = TEMPLATE.replace("__DATA__", json.dumps(
        {"nodes": vis_nodes, "edges": vis_edges, "stats": stats, "legend": legend}, ensure_ascii=False))
    out = ROOT / "scratch" / "graph.html"
    out.write_text(html)
    print(f"寫入 {out}：{stats}")


TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>POI 路線圖</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body{margin:0;font:13px/1.5 -apple-system,"PingFang TC",sans-serif;display:flex;height:100vh;color:#222;background:#fafafa}
  #net{flex:1;background:#fff;border-right:1px solid #ddd}
  aside{width:380px;overflow:auto;padding:12px 14px}
  h3{margin:12px 0 6px;font-size:14px}
  .sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
  .ln{display:inline-block;width:22px;height:0;border-top:3px solid;margin-right:4px;vertical-align:middle}
  .leg span{margin-right:10px;white-space:nowrap}
  .obs{border:1px solid #e3e3e3;border-radius:6px;padding:6px 8px;margin:6px 0;background:#fff}
  .ev{background:#fff8e1;border-left:3px solid #f2b400;padding:4px 6px;margin:4px 0}
  .muted{color:#888} a{color:#2a6fdb;word-break:break-all}
  label{margin-right:10px} input[type=search]{width:100%;padding:5px;box-sizing:border-box}
</style></head><body>
<div id="net"></div>
<aside>
  <div id="stats" class="muted"></div>
  <h3>篩選</h3>
  <input type="search" id="q" placeholder="搜尋景點名稱，Enter 聚焦">
  <div id="modeF" style="margin-top:6px"></div>
  <div id="srcF"></div>
  <label><input type="checkbox" id="hideIso"> 隱藏孤立節點</label>
  <h3>圖例</h3>
  <div class="leg" id="leg"></div>
  <div class="muted">圈內數字＝來源數（source_count）；黑框＝有證據段落；線粗＝觀測次數；虛線＝交通方式為推測</div>
  <h3>詳細</h3>
  <div id="detail" class="muted">點選節點或邊</div>
</aside>
<script>
const D = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const link = u => u ? `<a href="${esc(u)}" target="_blank">${esc(u)}</a>` : "";
const byId = Object.fromEntries(D.nodes.map(n => [n.id, n]));
document.getElementById("stats").textContent =
  `${D.stats.nodes} 節點・${D.stats.edges} 條觀測邊（合併後 ${D.stats.merged_edges}）・${D.stats.trips} 個行程・孤立節點 ${D.stats.isolated}`;
document.getElementById("leg").innerHTML =
  Object.entries(D.legend.area).map(([a,c]) => `<span><i class="sw" style="background:${c}"></i>${esc(a)}</span>`).join("")
  + `<span><i class="sw" style="background:${D.legend.other}"></i>其他地區</span><br>`
  + Object.entries(D.legend.mode).map(([m,c]) => `<span><i class="ln" style="border-color:${c}"></i>${esc(m)}</span>`).join("");

// 圓圈＋圈內數字＋圈下名稱
const radius = n => 10 + 5 * Math.sqrt(n.count - 1);
function drawPoi({ctx, id, x, y, state: {selected, hover}}) {
  const n = byId[id], r = radius(n);
  return {
    drawNode() {
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = n.color; ctx.fill();
      ctx.lineWidth = n.has_ev ? 3 : 1.5; ctx.strokeStyle = n.has_ev ? "#222" : "#fff"; ctx.stroke();
      if (selected || hover) { ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 2 * Math.PI); ctx.lineWidth = 2; ctx.strokeStyle = "#2a6fdb"; ctx.stroke(); }
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `bold ${Math.round(r * .9 + 4)}px -apple-system,sans-serif`; ctx.fillStyle = "#fff";
      ctx.fillText(n.count, x, y + 1);
      ctx.font = '12px -apple-system,"PingFang TC",sans-serif'; ctx.fillStyle = "#333"; ctx.textBaseline = "top";
      ctx.fillText(n.label, x, y + r + 3);
    },
    nodeDimensions: {width: 2 * r, height: 2 * r},
  };
}

const nodes = new vis.DataSet(D.nodes.map(n => ({id: n.id, title: n.title, shape: "custom", ctxRenderer: drawPoi, size: radius(n)})));
const edges = new vis.DataSet(D.edges.map(e => ({id: e.id, from: e.from, to: e.to, title: e.title, width: e.width,
  dashes: e.dashes, color: {color: e.color, opacity: .8}})));
const edgeById = Object.fromEntries(D.edges.map(e => [e.id, e]));

const modes = [...new Set(D.edges.map(e => e.mode))], srcs = [...new Set(D.edges.flatMap(e => e.sources))];
const box = (id, vals, name) => document.getElementById(id).innerHTML =
  vals.map(v => `<label><input type="checkbox" data-${name}="${esc(v)}" checked> ${esc(v)}</label>`).join("");
box("modeF", modes, "mode"); box("srcF", srcs, "src");
const on = attr => new Set([...document.querySelectorAll(`[data-${attr}]`)].filter(x => x.checked).map(x => x.dataset[attr]));
const edgeOk = e => { const m = on("mode"), s = on("src"); return m.has(e.mode) && e.sources.some(x => s.has(x)); };
const nodeOk = n => !document.getElementById("hideIso").checked
  || D.edges.some(e => edgeOk(e) && (e.from === n.id || e.to === n.id));
const nv = new vis.DataView(nodes, {filter: nodeOk}), ev = new vis.DataView(edges, {filter: e => edgeOk(edgeById[e.id])});
document.querySelectorAll("aside input[type=checkbox]").forEach(x => x.onchange = () => { ev.refresh(); nv.refresh(); });

const net = new vis.Network(document.getElementById("net"), {nodes: nv, edges: ev}, {
  edges: {arrows: {to: {enabled: true, scaleFactor: .6}}, smooth: {type: "dynamic"}},
  physics: {solver: "forceAtlas2Based", forceAtlas2Based: {gravitationalConstant: -60, springLength: 100}, stabilization: {iterations: 300}},
  interaction: {hover: true},
});

const evHtml = list => (list || []).map(x => typeof x === "string"
  ? `<div class="ev">${esc(x)}</div>`
  : `<div class="ev"><b>${esc(x.kind)}</b> ${esc(x.text)}<br>${link(x.url)}</div>`).join("");
const detail = document.getElementById("detail");
function showNode(id) {
  const n = byId[id].raw;
  const deg = D.edges.filter(e => e.from === n.poi_id || e.to === n.poi_id).length;
  detail.innerHTML = `<b style="font-size:15px">${esc(n.poi_name)}</b> <span class="muted">${n.poi_id}</span><br>
    ${esc(n.area)}・${esc(n.category)}・${n.source_count} 個來源・${deg} 條相連邊<br>
    ${n.aliases.length ? "別名：" + esc(n.aliases.join("、")) + "<br>" : ""}
    月份：${n.months.join(", ") || "—"}・停留：${n.duration ?? "—"}・營業時間：${esc(JSON.stringify(n.hours))}<br>
    座標：${n.lat ?? "—"}, ${n.lon ?? "—"}
    <h3>證據（${n.evidence.length}）</h3>${evHtml(n.evidence) || '<span class="muted">無</span>'}
    <h3>觀測（${n.observations.length}）</h3>` +
    n.observations.map(o => `<div class="obs">${esc(o.trip_id)}・${esc(o.name_raw)}・${esc(o.visit_type ?? "")}・月份 ${o.months.join(",")}</div>`).join("") +
    `<h3>來源</h3>` + n.url.map(u => `<div>${link(u)}</div>`).join("");
}
function showEdge(id) {
  const e = edgeById[id];
  detail.innerHTML = `<b style="font-size:15px">${esc(e.raw[0].from.poi_name)} → ${esc(e.raw[0].to.poi_name)}</b><br>${esc(e.mode)}・${e.raw.length} 次觀測` +
    e.raw.map(o => `<div class="obs"><b>${o.edge_id}</b> ${esc(o.trip_id)}・第 ${o.day} 天第 ${o.seq} 段・${esc(o.source_type)}<br>
      ${esc(o.from.name_raw)} → ${esc(o.to.name_raw)}<br>
      交通：${esc(o.mode ?? "未知")}${o.vehicle ? "（" + esc(o.vehicle) + "）" : ""}${o.mode_inferred ? ' <span class="muted">推測：' + esc(o.mode_basis) + "</span>" : ""}<br>
      時間：${o.duration_min ?? "—"} 分・距離：${o.distance_km ?? "—"} km${o.via.length ? "<br>途經：" + esc(o.via.join("、")) : ""}
      ${evHtml(o.evidence)}${link(o.url)}</div>`).join("");
}
net.on("click", p => { if (p.nodes.length) showNode(p.nodes[0]); else if (p.edges.length) showEdge(p.edges[0]); });
document.getElementById("q").onkeydown = e => {
  if (e.key !== "Enter") return;
  const q = e.target.value;
  const hit = D.nodes.find(n => n.label.includes(q) || (n.raw.aliases || []).some(a => a.includes(q)));
  if (hit) { net.selectNodes([hit.id]); net.focus(hit.id, {scale: 1.4, animation: true}); showNode(hit.id); }
};
</script></body></html>
"""

if __name__ == "__main__":
    build()
