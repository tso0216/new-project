# 抽取（extract）實作企劃書

把 `data/raw/<source>/*.md`（爬蟲輸出）解析成 POI 節點與移動邊，存進 SQLite。

---

## 1. 已確定的決策

| # | 決策 |
|---|---|
| 1 | POI 對應順序：別名完全比對 → 模糊比對 → embedding → Google Places。前三步先擋，目的是減少 API 呼叫 |
| 2 | 景點粒度由 Google Places 決定（place_id 相同就是同一個節點） |
| 3 | 一次 LLM 呼叫同時輸出 nodes 與 edges；poi_id 是「文章內暫時編號」，對應資料庫的工作由程式在 LLM 之後做 |
| 4 | 座標、營業時間等外部資料只由程式寫入資料庫，不出現在提示詞 |
| 5 | `months` 一律由 LLM 判斷（不是每家旅行社都會把出團月份寫進 front matter），在**文章層級**輸出一次，程式再套到每條邊與每筆 observation |
| 6 | LLM 用 GPT，優先用 Structured Outputs 限制格式；模型不支援時改在提示詞裡寫格式規則 |
| 7 | 資料庫用 SQLite |
| 8 | Google 回傳車站、飯店等類型時不擋 |
| 9 | 提示詞改成「原文有並列的景點就分開輸出」，不讓 LLM 自己合併 |
| 10 | 格式驗證失敗時，把錯誤原因丟回 LLM 重新生成 |

---

## 2. 整體流程

```
data/raw/<source>/<trip_id>.md
  │
  ├─ ① 讀檔：拆出 front matter 與內文；trip_id = 檔名（colatour_246129）
  │
  ├─ ② LLM 抽取（一次呼叫）→ { months, nodes[P001…], edges[P001→P002…] }
  │
  ├─ ③ 驗證 ──錯誤──→ 帶錯誤清單丟回 LLM 重生（最多重試 2 次）
  │     │                         └ 仍失敗 → 寫進 data/extract_failures/，跳過這篇
  │     └ 可由程式直接修的（月份排序去重、seq 編號）直接修，不重試
  │
  ├─ ④ 逐一解析 node（P001 → 資料庫 node_id）
  │     正規化 → 別名完全比對 → 模糊比對 → embedding → Google Places
  │       Google 回傳 place_id：資料庫已有 → 用既有節點；沒有 → 建新節點
  │       成功後把 poi_name、name_raw 存成別名
  │       Google 查無結果 → 帶「哪些名稱查不到」丟回 LLM 重生，回到 ③（見 §8.5）
  │
  ├─ ⑤ 改寫 edge 的 from/to 成 node_id；兩端變成同一個節點（例如同篇兩個名稱被 Google 判成同一地點）→ 丟掉這條邊
  │
  └─ ⑥ 一個 transaction 寫進 data/graph.db（任何一步失敗整篇還原）
```

驗證放在呼叫 Google 之前，格式錯誤的輸出不會浪費 API 費用。

---

## 3. 檔案規劃

| 檔案 | 內容 |
|---|---|
| `src/extract/per_article.py` | 入口，串起整個流程 |
| `src/extract/per_article_prompt.md` | 提示詞（改版，見 §5） |
| `src/extract/schema.py` | LLM 輸出的 pydantic 模型（同時產生給 Structured Outputs 的 JSON Schema） |
| `src/extract/validate.py` | 內容驗證；也可以單獨執行，檢查一份既有的 LLM 輸出 |
| `src/extract/resolve.py` | POI 對應：正規化、別名、模糊比對、embedding、呼叫 Google |
| `src/extract/places.py` | Google Places API（New）Text Search |
| `src/extract/db.py` | SQLite 建表與讀寫 |
| `src/extract/export.py` | `graph.db` → `data/node.json`、`data/edge.json`（人工檢查、`scratch/render_graph.py` 用） |

指令：

```bash
python src/extract/per_article.py data/raw/colatour/colatour_246129.md   # 單篇
python src/extract/per_article.py data/raw/colatour/                     # 整個資料夾
python src/extract/per_article.py data/raw/colatour/ --force             # 已處理過的也重跑
python src/extract/validate.py <llm輸出.json> <文章.md>                   # 單獨檢查一份輸出
python src/extract/export.py                                             # 匯出 JSON
```

已處理過的判斷：`articles` 表裡有同一個 trip_id 且檔案內容 hash 沒變 → 跳過。重跑時先刪掉該篇舊的 observations 與 edges 再寫入（節點與別名保留）。

---

## 4. LLM 輸出格式（改版）

只保留「需要讀懂文章」的欄位；其他欄位由程式或 Google 填。

```json
{
  "months": [9, 10, 11],
  "nodes": [
    {
      "poi_id": "P001",
      "poi_name": "淺草寺",
      "observations": [
        { "name_raw": "淺草寺（雷門）", "visit_type": "入內參觀", "stay_min": 60, "as_area": false }
      ]
    }
  ],
  "edges": [
    {
      "from": "P001", "to": "P002",
      "mode": "自駕", "mode_inferred": true, "mode_basis": "旅行社跟團預設遊覽車",
      "vehicle": null, "duration_min": 20, "via": ["免稅店"], "day": 2
    }
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `months`（文章層級） | front matter 有出團月份就用它；否則用內文寫的出團／旅行月份；都沒有就 `[]` |
| `edges` 的順序 | 每天內依原文順序輸出，程式依此編 `seq` |

### 欄位分工

| 欄位 | 誰填 |
|---|---|
| `months`、`poi_id`、`poi_name`、observation 各欄、edge 的 `from`/`to`/`mode`/`mode_inferred`/`mode_basis`/`vehicle`/`duration_min`/`via`/`day` | LLM |
| `trip_id`（檔名）、`url`（front matter）、`source_type`（front matter 的 `source` 查對照表）、`edge_id`、`seq` | 程式 |
| `duration`（中位數）、node 的 `months`（聯集）、`source_count` | 程式，匯出或查詢時從資料庫統計（不另存，避免數字過期） |
| `lat`、`lon`、營業時間等 | Google |

`source_type` 對照表放在程式裡，例如 `{"colatour": "旅行社", "pixnet": "遊記", …}`。遇到表裡沒有的 source 就直接報錯，提醒加上。

所有爬蟲輸出的 front matter 至少要有 `source`、`url`，檔名要是 `<trip_id>.md`。

---

## 5. 提示詞改版重點（`per_article_prompt.md`）

- 刪掉已改由程式、Google 填的欄位與相關規則（lat/lon、duration、各處 months、source_count、url、trip_id、edge_id、seq、source_type）。
- 新增文章層級的 `months` 規則。
- 新增規則：原文**並列**的景點分開輸出，不要合併；是否合併交給後續處理。
- 使用 Structured Outputs 時，「輸出格式」一節只保留一句說明，細節交給 schema；不支援時保留目前的格式規則與自我檢查清單。
- 保留：什麼算景點、建邊規則（同日相鄰、不跨天、不用建議清單建邊）、交通方式判斷順序。

---

## 6. LLM 呼叫與格式限制

- 使用 OpenAI SDK 的 `chat.completions.parse(response_format=<pydantic 模型>)`（Structured Outputs，strict 模式），保證欄位、型別、列舉值正確。
- 目前 `config.LLM_MODEL` 是 `gpt-6-luna`，實作時先確認它支援 Structured Outputs。不支援就改用 `response_format={"type": "json_object"}` 並保留提示詞的格式規則，再用 pydantic 解析；解析失敗一樣進重試流程。
- 在 `src/service/llm_client.py` 加一個 `parse()` 方法，沿用現有的 API key 與 base_url 設定。

---

## 7. 驗證規則（`validate.py`）

### 7.1 由 schema 保證（pydantic）

- 欄位齊全、型別正確
- 列舉值：`visit_type`、`mode`、`mode_basis`

### 7.2 內容檢查（錯誤 → 丟回 LLM）

| 規則 | 錯誤訊息範例 |
|---|---|
| `poi_id` 格式 `P\d{3}`、不重複 | `nodes[4].poi_id "P3" 格式錯誤，應為 P004` |
| 兩個 node 的 `poi_name` 相同 | `P002 與 P007 都叫「明治神宮」，同一景點只建一個 node，請合併 observations` |
| 每個 node 至少一筆 observation | `P005 沒有 observations` |
| `name_raw` 能在原文逐字找到 | `P003.observations[0].name_raw「淺草觀音寺」在原文找不到，請照抄原文` |
| edge 的 `from`/`to` 存在於 nodes | `edges[3].to 是 P009，但 nodes 裡沒有 P009` |
| `from` ≠ `to` | `edges[2] 起訖點相同（P004）` |
| `day` ≥ 1 | |
| `mode`、`mode_inferred`、`mode_basis` 三者一致 | `edges[1] mode_basis 是「同園區步行範圍」，mode 應為「走路」` |
| `mode_basis` 為「原文未寫」時 `vehicle` 必須是 null | |
| `months` 每個值都在 1–12 | |

一致性規則對照：

| mode_basis | mode | mode_inferred |
|---|---|---|
| 原文明寫 | 任一非 null | false |
| 同園區步行範圍 | 走路 | true |
| 旅行社跟團預設遊覽車 | 自駕 | true |
| 途經車站、遊記起訖點記成車站 | 大眾運輸 | true |
| 原文未寫 | null | false |

### 7.3 程式直接修（不重試）

- `months` 排序、去重
- `edge_id`、`seq` 由程式編號

### 7.4 重試訊息

把上一次的完整輸出與編號錯誤清單一起送回：

```
你上一次的輸出有以下問題，請修正後輸出完整 JSON（不要只輸出修改的部分）：
1. edges[3].to 是 P009，但 nodes 裡沒有 P009
2. P003.observations[0].name_raw「淺草觀音寺」在原文找不到，請照抄原文
```

最多重試 2 次（共 3 次呼叫）。仍失敗就把最後一次輸出與錯誤寫進 `data/extract_failures/<trip_id>.json`，跳過這篇，不寫資料庫。

**限制**：驗證只能抓格式與內部一致性，抓不到漏掉的景點或建錯的邊，這部分要人工抽查。

---

## 8. POI 對應（`resolve.py`）

對每個 node，依序：

### 8.1 正規化

- OpenCC：簡轉繁、日文新字體轉繁體（浅→淺、駅→站）
- 全形半形統一、去空白
- 去掉括號與括號內文字

正規化結果當別名的 key。

### 8.2 別名完全比對

先用正規化後的 `poi_name` 查，再用 `name_raw` 查。命中就結束。

### 8.3 模糊比對（rapidfuzz）

- 跟所有別名比對，取最高分。
- 初始門檻 `fuzz.ratio ≥ 90`。
- 門檻刻意設得很嚴，避免「淺草」併進「淺草寺」這種錯誤合併，寧可交給 Google。

### 8.4 embedding

- 沿用專案現有的 `BAAI/bge-base-zh-v1.5`。
- 每個別名的向量存在資料庫，比對時全部載入做 cosine。
- 初始門檻 `≥ 0.92`，同樣刻意設嚴：語意相近但不同的地點（雷門／淺草寺）容易在這步被合併，搶走 Google 決定粒度的機會。

### 8.5 Google Places Text Search

- 查詢字串：`poi_name`，`languageCode = "zh-TW"`，只取第一筆。
- 回傳的 place_id 已存在於資料庫 → 用既有節點（前面三步漏掉的同一地點在這裡接住，不重複建節點）。
- 不存在 → 建新節點，寫入 Google 資料。
- 查無結果 → 丟回 LLM 重生，訊息範例：

  ```
  以下景點在 Google Maps 查不到，請確認後輸出完整 JSON：
  1. P003「淺草觀音寺」：名稱可能不是正式名稱，請改用通行的正式名稱
  若它其實不是景點，請刪掉這個 node 與相關的 edge
  ```

  重生的輸出重新走 ③ 驗證與 ④ 解析。為了不重複花 API 費用：
  - 這篇處理期間，Google 的查詢結果（包括查無結果）暫存在記憶體，同一個名稱不再查第二次。
  - 解析結果先不寫資料庫，整篇通過才在 ⑥ 一起寫入。
  - 重試上限見 §14。

### 8.6 記錄

- 每次命中都把 `poi_name`、`name_raw`（正規化後）存成別名，並記錄命中方式與分數。
- 模糊比對與 embedding 命中的別名可以用 SQL 列出來人工檢查；門檻之後依檢查結果調整。

門檻放在 `resolve.py` 開頭當常數，跟爬蟲的 `DELAY` 一樣。

---

## 9. Google Places（`places.py`）

- API：Places API (New) Text Search，`POST https://places.googleapis.com/v1/places:searchText`
- 金鑰：`config/.env` 新增 `GOOGLE_PLACES_API_KEY`，`config/config.py` 讀取
- Field mask（決定計費等級；含營業時間屬於較高等級）：

| 欄位 | 用途 |
|---|---|
| `id` | place_id，判斷同一景點 |
| `displayName` | Google 上的名稱 |
| `location` | 座標 |
| `regularOpeningHours` | 營業時間，存結構化的 `periods`，排程用 |
| `utcOffsetMinutes` | 時區，換算營業時間 |
| `businessStatus` | 排除永久歇業 |
| `primaryType`、`types` | 類型 |
| `formattedAddress` | 地址 |
| `viewport` | 區域範圍，之後可用來判斷「同園區步行範圍」 |
| `googleMapsUri` | 連結 |
| `userRatingCount` | 熱門程度，排序路線可用 |

---

## 10. SQLite 結構（`data/graph.db`）

```sql
CREATE TABLE nodes (
  node_id          INTEGER PRIMARY KEY,
  name             TEXT NOT NULL,      -- 第一次出現時 LLM 給的 poi_name（繁中）
  place_id         TEXT NOT NULL UNIQUE,
  google_name      TEXT,
  lat              REAL,
  lon              REAL,
  opening_hours    TEXT,               -- JSON（regularOpeningHours.periods）
  utc_offset_min   INTEGER,
  business_status  TEXT,
  primary_type     TEXT,
  types            TEXT,               -- JSON 陣列
  address          TEXT,
  viewport         TEXT,               -- JSON
  maps_uri         TEXT,
  rating_count     INTEGER,
  google_query     TEXT,
  resolved_at      TEXT
);

CREATE TABLE aliases (
  alias       TEXT PRIMARY KEY,        -- 正規化後的名稱
  node_id     INTEGER NOT NULL REFERENCES nodes,
  raw         TEXT,                    -- 正規化前
  matched_by  TEXT,                    -- exact / fuzzy / embedding / google / place_id
  score       REAL,
  trip_id     TEXT,                    -- 第一次出現在哪篇
  embedding   BLOB                     -- float32 向量
);

CREATE TABLE articles (
  trip_id       TEXT PRIMARY KEY,
  source        TEXT,
  source_type   TEXT,
  url           TEXT,
  title         TEXT,
  path          TEXT,
  content_hash  TEXT,
  months        TEXT,                  -- JSON 陣列，LLM 判斷
  llm_model     TEXT,
  attempts      INTEGER,               -- 用了幾次 LLM 呼叫
  llm_output    TEXT,                  -- 最後一次通過驗證的原始輸出，除錯用
  extracted_at  TEXT
);

CREATE TABLE observations (
  id          INTEGER PRIMARY KEY,
  trip_id     TEXT NOT NULL REFERENCES articles,
  node_id     INTEGER NOT NULL REFERENCES nodes,
  name_raw    TEXT,
  visit_type  TEXT,
  stay_min    INTEGER,
  as_area     INTEGER
);

CREATE TABLE edges (
  edge_id        INTEGER PRIMARY KEY,
  trip_id        TEXT NOT NULL REFERENCES articles,
  from_node      INTEGER NOT NULL REFERENCES nodes,
  to_node        INTEGER NOT NULL REFERENCES nodes,
  mode           TEXT,
  mode_inferred  INTEGER,
  mode_basis     TEXT,
  vehicle        TEXT,
  duration_min   INTEGER,
  via            TEXT,                 -- JSON 陣列
  day            INTEGER,
  seq            INTEGER,
  UNIQUE (trip_id, day, seq)
);
```

- `months` 存在 `articles`，observations 與 edges 透過 `trip_id` 取得，符合「同一篇所有邊月份相同」。
- `duration`、node 的 `months`、`source_count` 在匯出或查詢時計算。
- 找路線時把 nodes、edges 讀進 networkx（已安裝）。

---

## 11. 新增套件

| 套件 | 用途 |
|---|---|
| `rapidfuzz` | 模糊比對 |
| `opencc` | 簡繁與日文字體轉換（要確認有 `jp2t` 設定；`opencc-python-reimplemented` 可能沒有） |

sentence-transformers、numpy、httpx、pydantic、networkx 已安裝。

---

## 12. 實作順序

| 階段 | 內容 | 完成的判斷 |
|---|---|---|
| 1 | `schema.py`、提示詞改版、LLM 呼叫、`validate.py`、重試；輸出先存成 JSON，不碰資料庫 | 5 篇 colatour 都通過驗證，記錄每篇重試次數 |
| 2 | `db.py` 建表、寫入；`--force` 重跑 | 重跑同一篇，資料不重複 |
| 3 | `resolve.py` 正規化、別名、模糊比對、embedding；Google 先不接，沒命中的名稱先列出來 | 5 篇跑完，列出所有模糊比對與 embedding 命中，人工檢查 |
| 4 | `places.py` 接 Google | 統計 API 呼叫次數；檢查 place_id 合併結果 |
| 5 | `export.py`；更新 `node.json.sample`、`edge.json.sample` 為匯出格式；確認 `scratch/render_graph.py` 能讀 | 瀏覽器看得到圖 |
| 6（選做） | 門檻校準腳本：用舊 `poi_rules.py`（commit `0ce2ffd`）的人工對應畫分數分布 | 決定最終門檻 |

---

## 13. 風險

| 風險 | 對策 |
|---|---|
| 模糊比對或 embedding 合錯，之後同名稱都跟著錯 | 門檻設嚴；命中方式與分數記在 aliases，可列出檢查；錯的別名刪掉即可重跑 |
| 同名地點（中華街：橫濱／神戶／長崎）：Google 查詢不帶地區、別名也不分地區 | 目前先不處理；place_id、google_name、address 都有存，發生時可以從地址看出來 |
| Google 回傳錯誤地點（同名店家） | place_id、google_name 都存下來，方便人工檢查 |
| Google 把兩個名稱判成同一地點，產生 A→A 的邊 | 程式丟掉該邊，observations 合併到同一節點 |
| 模型不支援 Structured Outputs | 退回 json_object + 提示詞格式規則 + pydantic 驗證 |

---

## 14. 已確認

- `data/graph.db`、`data/raw/`、`data/extract_failures/` 不進 git（已加進 `.gitignore`）。
- 不另外呼叫 Google 取日文名稱。
- Google 查無結果 → 丟回 LLM 重生（§8.5）。
- 不加文章層級的 `region`，Google 只用 `poi_name` 查。

## 15. 待確認

1. 並列景點（例如「淺草寺（雷門）」）拆成兩個 node 之後，前後的邊怎麼接。
2. Google 查無結果時的重試上限，以及用完重試仍查不到時怎麼處理。
