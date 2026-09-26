# 景點人工查詢：使用說明

程式會一篇一篇讀旅行社行程，由 AI 找出行程裡的景點。遇到資料庫裡還沒有的景點，程式會停下來，請你查出正確的地點並貼上兩樣資料：**place_id** 和 **Google 地圖網址**。

## 第一次使用：安裝套件

在專案資料夾裡執行：

macOS / Linux：
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows：
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

之後每次開新的終端機，都要先啟用環境（macOS／Linux：`source .venv/bin/activate`；Windows：`.venv\Scripts\activate`）再執行程式。第一次執行時會自動下載一個約 400 MB 的比對模型，只會下載一次。

## 步驟

### 1. 執行程式

```bash
python src/extract/main.py --manual
```

每篇文章 AI 要先讀 20～40 秒，然後才會開始問。資料庫已經有的景點不會再問。

### 2. 看程式要查哪個景點

```
── 人工查詢：箱根神社
原文：箱根神社
文章：colatour_246129｜【APP限定獨享、日本東京】蘆之湖海盜船、大室山纜車、富士絕景餐廳、雙溫泉巨蛋飯店五日
Google 地圖：https://www.google.com/maps/search/?api=1&query=...
Place ID Finder：https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder
place_id（直接按 Enter＝查不到）：
```

「文章」是行程標題，可以看出景點大概在哪個地區。

### 3. 在 Google 地圖找出正確的地點

點「Google 地圖」連結，從搜尋結果找出正確的地點，並**點開它**。

- 有同名地點時，選在行程地區裡的那個（例如行程在伊豆，「城崎海岸」就選伊豆的）。
- 選景點本身，不要選旁邊的停車場、車站、飯店或商店。
- Google 上顯示日文名也沒關係，只要是同一個地方就好。

### 4. 貼 place_id

點「Place ID Finder」連結，在左上角的搜尋框輸入景點名稱，從下拉選單選**同一個地點**。地圖上跳出的小框裡會有 `Place ID: ChIJ...`，複製那串英數字，貼到 `place_id：` 後面，按 Enter。

### 5. 貼 Google 地圖網址

回到步驟 3 點開的地點，複製瀏覽器網址列的網址（網址裡要有 `/maps/place/`），貼到 `Google 地圖網址：` 後面，按 Enter。

程式會顯示讀到的名稱和座標，例如 `→ 箱根神社（35.2048, 139.0253）`，然後繼續下一個。

### 6. 查不到或不確定時

在 `place_id：` 直接按 Enter 跳過。**不確定就跳過，不要亂選**，選錯的地點會一直影響之後的資料。

## 中途停止

按 **Ctrl + C**。已經做完的文章會保存；停下來的那一篇不會保存，下次會重做。要繼續時，再執行一次同一個指令。

## 做完之後

最後出現「人工查詢 N 次」就是結束了。把整個 `data/` 資料夾交回。

如果發現之前貼錯了地點，記下「文章」那一行的編號和景點名稱，一起告訴我。

## 常見問題

| 訊息 | 處理 |
|---|---|
| `缺少 GOOGLE_PLACES_API_KEY` | 忘了加 `--manual` |
| `網址裡找不到座標` | 複製到搜尋結果的網址了，先點開地點再複製 |
| `place_id 格式不對` | 只貼那串英數字，不要包含空格或「Place ID:」 |
| `[3/9] 失敗 xxx.md` | 這篇 AI 處理失敗，不用管，程式會繼續下一篇 |
| `data/raw/ 裡沒有待解析的文章` | 全部做完了 |
