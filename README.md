# TW Stock Gemini

一個用於追蹤台灣和中國股票投資組合的即時儀表板應用程式。

## 功能特色

### 即時監控
- 每 5 秒自動更新股票價格和投資組合價值
- 顯示總市值、總成本、總損益和總報酬率
- 分別顯示台灣股票和中國股票的市值
- 即時人民幣匯率 (CNY/TWD) 顯示

### 投資組合管理
- 新增、編輯、刪除股票持股
- 支援多種貨幣 (TWD、CNY、USD)
- 自動抓取股票名稱
- 試算功能 (What-if Analysis) - 計算目標價格下的潛在收益

### 歷史數據追蹤
- 每日自動快照記錄 (交易日下午 3:30)
- SQLite 資料庫儲存歷史數據
- 圖表顯示歷史績效趨勢
- 支援多種時間範圍查詢 (本月 MTD、近 7 天、近 30 天、本年 YTD、近一年)

### 視覺化圖表
- 總資產歷史圖表
- 個股歷史價格圖表
- 可自訂顯示的圖表系列 (總資產、台灣股票、中國股票)
- 深色/淺色主題支援

### 通知系統
- 總報酬率閃爍通知
- 總損益閃爍通知
- 總市值閃爍通知
- 可自訂通知閾值

## 每日變動 (vs 昨收) 歸零機制

### 歸零時機
「每日變動」(vs 昨收) 會在以下情況歸零並重新計算：

1. **每個交易日開始時**：系統會自動計算當前總市值，並與前一個交易日的收盤總市值進行比較
2. **非交易日處理**：週末和假日不會記錄數據，因此在下一個交易日會繼續與最後一個交易日的數據比較

### 技術實現
- 系統使用 [`APScheduler`](app.py:10) 在每天下午 3:30 自動執行 [`save_daily_snapshot()`](app.py:146) 函數
- 快照只在週一至週五執行 ([`day_of_week='mon-fri'`](app.py:468))
- 昨日收盤價透過資料庫查詢獲得：
  ```python
  # 查詢早於今天的最後一筆總市值作為昨日收盤值
  cursor.execute("SELECT total FROM daily_history WHERE date < ? ORDER BY date DESC LIMIT 1", (today_str,))
  ```
- 每日變動 = 當前總市值 - 昨日收盤總市值
- 每日變動百分比 = (每日變動 / 昨日收盤總市值) × 100%

### 數據清理
- 系統會自動清理週末數據，確保歷史記錄只包含交易日
- [`clean_weekend_data.py`](clean_weekend_data.py:1) 腳本可用於手動清理週末數據

## 檔案結構

```
├── app.py              # 主應用程式 (Flask 伺服器)
├── portfolio.json      # 投資組合資料
├── history.db          # 歷史數據 SQLite 資料庫
├── init_db.py          # 資料庫初始化腳本
├── backfill.py         # 歷史數據回填腳本
├── check_data.py       # 資料庫查詢工具
├── clean_weekend_data.py # 週末數據清理工具
├── templates/
│   └── index.html      # 主頁面模板
└── static/
    ├── app.js          # 前端 JavaScript 邏輯
    └── style.css       # 樣式表
```

## 安裝與執行

### 環境需求
- Python 3.7+
- Flask
- yfinance
- APScheduler
- pandas
- sqlite3

### 安裝步驟
1. 安裝依賴套件：
   ```bash
   pip install flask yfinance apscheduler pandas
   ```

2. 初始化資料庫：
   ```bash
   python init_db.py
   ```

3. 啟動應用程式：
   ```bash
   python app.py
   ```

4. 開啟瀏覽器訪問 `http://localhost:5000`

### 回填歷史數據
如需回填歷史數據，可執行：
```bash
python backfill.py
```

## 使用說明

### 新增股票
1. 點擊「新增持股」按鈕
2. 輸入股票代號 (如 2317.TW)
3. 輸入股數和平均成本
4. 選擇貨幣類型 (TWD/CNY)
5. 點擊「儲存」

### 試算功能
在持股明細的「試算」欄位中輸入目標價格，系統會自動計算：
- 目標市值
- 與現價的差異
- 差異百分比

### 圖表功能
- 點擊「歷史圖表」按鈕可查看個股歷史價格圖表
- 圖表支援深色/淺色主題
- 可通過圖例點擊來顯示/隱藏不同的數據系列

### 設定功能
點擊右上角齒輪圖示可進行以下設定：
- 資料更新頻率
- 圖表顯示範圍
- 圖表顯示系列
- 主題選擇 (深色/淺色)
- 通知設定

## API 端點

### GET 請求
- `/api/portfolio` - 獲取當前投資組合數據
- `/api/history_summary` - 獲取歷史績效摘要
- `/api/stock_history/<ticker>` - 獲取個股歷史價格

### POST/PUT 請求
- `/api/stock` - 新增股票
- `/api/stock/<ticker>` - 更新股票

### DELETE 請求
- `/api/stock/<ticker>` - 刪除股票

## 注意事項

- 系統只在交易日記錄每日快照
- 匯率數據每分鐘更新一次
- 前端數據每 5 秒更新一次 (可調整)
- 支援深色模式和淺色模式