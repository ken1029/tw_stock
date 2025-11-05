import json
import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta
import sqlite3 # (新) 匯入 sqlite

# --- (設定) 回測日期範圍 ---
START_DATE = '2025-09-01'
END_DATE = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

# --- (設定) 檔案路徑 (與 app.py 相同) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, 'portfolio.json')
HISTORY_DB = os.path.join(BASE_DIR, 'history.db') # (修改) .db

# --- (新) DB 連線輔助函式 ---
def get_db_conn():
    conn = sqlite3.connect(HISTORY_DB)
    return conn

# --- (輔助函式) ---
def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"錯誤：找不到 {PORTFOLIO_FILE}")
        return []

# --- (移除 load_history 和 save_history) ---

# --- (主要的回測邏輯) ---
def run_backfill():
    print(f"--- 歷史資料回填腳本 (v2-SQLite) ---")
    print(f"回測範圍: {START_DATE} 至 {END_DATE}")

    # 1. 讀取持股
    portfolio = load_portfolio()
    if not portfolio:
        return
        
    # 2. 準備要下載的 Tickers
    stock_tickers = [stock['ticker'] for stock in portfolio]
    currency_tickers = []
    for stock in portfolio:
        if stock.get('currency') not in [None, "TWD"] and f"{stock['currency']}TWD=X" not in currency_tickers:
            currency_tickers.append(f"{stock['currency']}TWD=X")
            
    all_tickers = list(set(stock_tickers + currency_tickers))
    print(f"將下載 {len(all_tickers)} 個 Tickers 的歷史資料...")
    print(all_tickers)

    # 3. 下載所有歷史資料 (股價 + 匯率)
    try:
        data = yf.download(all_tickers, start=START_DATE, end=END_DATE)
        if data.empty:
            print("錯誤：yfinance 未返回任何資料。")
            return
            
        close_prices = data['Close']
        close_prices = close_prices.ffill() 
        close_prices = close_prices.bfill() 
        
    except Exception as e:
        print(f"錯誤：yfinance 下載失敗: {e}")
        return
        
    print("歷史資料下載並填充完成。")

    # 4. (修改) 準備 SQL
    conn = get_db_conn()
    cursor = conn.cursor()
    sql = ''' INSERT OR REPLACE INTO daily_history (date, total, tw_value, cn_value)
              VALUES (?, ?, ?, ?) '''
    
    snapshots_to_save = []

    # 5. 一天一天迴圈並計算總市值
    processed_count = 0
    for date_index in close_prices.index:
        date_str = date_index.strftime('%Y-%m-%d')
        
        if date_str == datetime.now().strftime('%Y-%m-%d'):
            continue
            
        # 檢查是否為週末 (5=星期六, 6=星期日)
        weekday = date_index.weekday()
        if weekday >= 5:
            print(f"Skipping weekend data for {date_str}")
            continue
            
        total_market_value_twd = 0
        total_tw_value = 0
        total_cn_value = 0
        
        rates = {}
        for c_ticker in currency_tickers:
            if c_ticker in close_prices and not pd.isna(close_prices[c_ticker][date_index]):
                rates[c_ticker[:3]] = close_prices[c_ticker][date_index]
        
        for stock in portfolio:
            ticker = stock['ticker']
            shares = float(stock.get('shares', 0))
            currency = stock.get('currency', 'TWD')
            
            if ticker not in close_prices:
                continue
                
            price = close_prices[ticker][date_index]
            if pd.isna(price):
                continue
                
            market_value_original = price * shares
            market_value_twd = market_value_original
            
            if currency != "TWD" and currency in rates:
                market_value_twd *= rates[currency]
            
            total_market_value_twd += market_value_twd
            
            if currency == "TWD":
                total_tw_value += market_value_twd
            elif currency == "CNY":
                total_cn_value += market_value_twd

        # 6. (修改) 準備要寫入的資料
        snapshot_data = (
            date_str,
            round(total_market_value_twd, 4),
            round(total_tw_value, 4),
            round(total_cn_value, 4)
        )
        snapshots_to_save.append(snapshot_data)
        processed_count += 1

    # 7. (修改) 一次性批次寫入資料庫 (效能高)
    try:
        cursor.executemany(sql, snapshots_to_save)
        conn.commit()
        conn.close()
        print(f"計算完成。共 {processed_count} 筆資料已儲存到 history.db。")
        print(f"--- 成功！ history.db 已更新 ---")
    except Exception as e:
        print(f"錯誤：儲存到 SQLite 時發生錯誤: {e}")
        conn.rollback()
        conn.close()

# --- (執行腳本) ---
if __name__ == "__main__":
    try:
        user_home = os.path.expanduser("~")
        yf_cache_dir = os.path.join(user_home, ".cache", "py-yfinance")
        if not os.path.exists(yf_cache_dir):
            os.makedirs(yf_cache_dir)
            print(f"已建立 yfinance 快取目錄: {yf_cache_dir}")
    except Exception as e:
        print(f"警告：無法建立 yfinance 快取目錄: {e}")
        
    run_backfill()
