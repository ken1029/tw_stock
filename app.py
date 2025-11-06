import json
import yfinance as yf
from flask import Flask, render_template, jsonify, request
from datetime import datetime, date, timedelta, time
import os
import requests
import pandas as pd
from time import time as timestamp
import sqlite3 # (新) 匯入 sqlite

from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 使用配置中的文件路徑，如果沒有則使用默認路徑
PORTFOLIO_FILE = os.path.join(BASE_DIR, 'portfolio.json')
HISTORY_DB = os.path.join(BASE_DIR, 'history.db') # (修改) 從 .json 改為 .db

def get_portfolio_file():
    """獲取portfolio文件路徑"""
    return app.config.get('PORTFOLIO_FILE', PORTFOLIO_FILE)

def get_history_db():
    """獲取歷史數據庫文件路徑"""
    return app.config.get('HISTORY_DB', HISTORY_DB)

# --- (匯率、load/save portfolio 函式... 保持不變) ---
cny_rate_cache = {"rate": None, "timestamp": 0}
CACHE_DURATION_SECONDS = 60

def get_cny_to_twd_rate():
    global cny_rate_cache
    now = timestamp()
    if cny_rate_cache["rate"] and (now - cny_rate_cache["timestamp"] < CACHE_DURATION_SECONDS):
        return cny_rate_cache["rate"]
    try:
        print("Fetching new CNY to TWD exchange rate...")
        response = requests.get('https://open.er-api.com/v6/latest/CNY')
        response.raise_for_status() 
        rate = response.json()['rates']['TWD']
        cny_rate_cache["rate"] = rate
        cny_rate_cache["timestamp"] = now
        print(f"New CNY Rate: {rate}")
        return rate
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        return cny_rate_cache["rate"] if cny_rate_cache["rate"] else 4.6 

def load_portfolio():
    # (修改) 從配置中獲取文件路徑
    try:
        with open(get_portfolio_file(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_portfolio(portfolio):
    # (修改) 儲存到配置中指定的文件路徑
    try:
        with open(get_portfolio_file(), 'w', encoding='utf-8') as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving portfolio: {e}")

# --- (修改) 移除 load_history 和 save_history ---

# (新) DB 連線輔助函式
def get_db_conn():
    conn = sqlite3.connect(get_history_db())
    conn.row_factory = sqlite3.Row # (讓回傳結果可以用欄位名稱存取)
    return conn

def get_current_prices(tickers):
    if not tickers:
        return {}
    print(f"[yfinance] Fetching prices: {' '.join(tickers)}")
    data = yf.Tickers(' '.join(tickers))
    stock_data = {}
    for ticker_str, ticker_obj in data.tickers.items():
        try:
            original_ticker_key = next(t for t in tickers if t.upper() == ticker_str.upper())
            
            # 獲取目前市價
            info = ticker_obj.fast_info
            price = info.get('last_price', info.get('regularMarketPrice'))
            
            # 更準確地獲取昨日收盤價
            # 使用history方法獲取最近幾天的資料以確保能獲取到正確的昨日收盤價
            hist = ticker_obj.history(period='5d') # 넉넉하게 5일치 가져오기

            # 오늘 날짜 (시간 정보 제외)
            today = datetime.now().date()

            # 어제 종가 초기화
            prev_close = None

            if not hist.empty:
                # 인덱스를 날짜 형식으로 변환
                hist.index = hist.index.date
                # 오늘 이전의 데이터만 필터링
                past_data = hist[hist.index < today]
                if not past_data.empty:
                    # 가장 최근 날짜의 종가를 어제 종가로 사용
                    prev_close = past_data['Close'].iloc[-1]

            # 만약 위 방법으로 종가를 못찾으면 원래 방법으로 대체
            if prev_close is None:
                prev_close = info.get('previousClose')
                
            if not price or not prev_close:
                if not hist.empty:
                    if not price:
                        price = hist['Close'].iloc[-1]
                    if not prev_close and len(hist) > 1:
                        prev_close = hist['Close'].iloc[-2]
                    elif not prev_close:
                        prev_close = price
                else:
                    print(f"Warning [yfinance]: Could not find price data for {original_ticker_key}")
                    price = 0
                    prev_close = 0
                    
            stock_data[original_ticker_key] = {"price": price, "previous_close": prev_close}
        except Exception as e:
            print(f"Error [yfinance price] processing {ticker_str}: {e}")
            matching_tickers = [t for t in tickers if t.upper() == ticker_str.upper()]
            if matching_tickers:
                stock_data[matching_tickers[0]] = {"price": 0, "previous_close": 0}
    return stock_data

def get_prices_for_date(tickers, target_date):
    """獲取指定日期範圍內的收盤價"""
    if not tickers:
        return {}
    
    # yfinance 需要一個結束日期，所以我們將目標日期加一天
    start_date = target_date
    end_date = target_date + timedelta(days=1)
    
    print(f"[yfinance] Fetching historical prices for {target_date.strftime('%Y-%m-%d')} for tickers: {' '.join(tickers)}")
    
    hist_data = yf.download(
        ' '.join(tickers),
        start=start_date,
        end=end_date,
        interval="1d",
        group_by='ticker'
    )
    
    stock_data = {}
    for ticker in tickers:
        try:
            # 處理單一股票和多股票時 hist_data 的不同結構
            if len(tickers) == 1:
                price_series = hist_data['Close']
            else:
                price_series = hist_data[ticker]['Close']

            if not price_series.empty:
                # 獲取該日期的收盤價
                price = price_series.iloc[-1]
                if pd.isna(price): # 處理假日或無交易日的情況
                     # 如果當天沒有資料，嘗試往前找最近的一個交易日
                    temp_end = target_date
                    temp_start = temp_end - timedelta(days=7) # 最多往前找7天
                    temp_hist = yf.download(ticker, start=temp_start, end=temp_end, interval="1d")
                    if not temp_hist.empty:
                        price = temp_hist['Close'].iloc[-1]
                        print(f"  -> {ticker} on {target_date.strftime('%Y-%m-%d')} has no data, using last valid price: {price:.2f} on {temp_hist.index[-1].strftime('%Y-%m-%d')}")
                    else:
                        price = 0
                        print(f"  -> Could not find any recent price for {ticker}")
                stock_data[ticker] = {"price": price}
            else:
                stock_data[ticker] = {"price": 0}
                print(f"Warning: No historical data found for {ticker} on {target_date.strftime('%Y-%m-%d')}")

        except Exception as e:
            print(f"Error processing historical data for {ticker}: {e}")
            stock_data[ticker] = {"price": 0}
            
    return stock_data

# --- (修改) 儲存邏輯改為 SQL ---
def update_history_log(snapshot_data, target_date=None):
    """
    (已修改) 
    儲存 snapshot 物件到 history.db
    """
    # 如果提供了 target_date，就使用它，否則使用今天
    date_str = target_date.strftime('%Y-%m-%d') if target_date else datetime.now().strftime('%Y-%m-%d')

    # (使用 INSERT OR REPLACE 進行 "Upsert"，如果日期已存在則覆蓋)
    sql = ''' INSERT OR REPLACE INTO daily_history (date, total, tw_value, cn_value)
              VALUES (?, ?, ?, ?) '''
              
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(sql, (
            date_str,
            snapshot_data['total'],
            snapshot_data['tw_value'],
            snapshot_data['cn_value']
        ))
        conn.commit()
        conn.close()
        print(f"Saving history snapshot for {date_str}: {snapshot_data}")
    except Exception as e:
        print(f"Error saving history to SQLite: {e}")

# (save_daily_snapshot 保持不變 - 它只負責計算，然後呼叫 update_history_log)
def save_daily_snapshot():
    with app.app_context(): 
        print(f"\n[Scheduler] Running 15:30 snapshot job... ({datetime.now()})")
        portfolio = load_portfolio()
        tickers = list(set(stock['ticker'] for stock in portfolio))
        if not tickers:
            print("[Scheduler] No portfolio found. Skipping snapshot.")
            return
        rate_cny_twd = get_cny_to_twd_rate()
        prices_data = get_current_prices(tickers) 
        total_market_value_twd = 0
        total_tw_value = 0
        total_cn_value = 0
        for stock in portfolio:
            ticker = stock['ticker']
            shares = float(stock.get('shares', 0))
            currency = stock.get("currency", "TWD") 
            current_price_original = prices_data.get(ticker, {}).get('price', 0)
            market_value_original = current_price_original * shares
            market_value_twd = market_value_original
            if currency == "CNY":
                market_value_twd *= rate_cny_twd
            total_market_value_twd += market_value_twd
            if currency == "TWD":
                total_tw_value += market_value_twd
            elif currency == "CNY":
                total_cn_value += market_value_twd
        snapshot_data = {
            "total": round(total_market_value_twd, 4),
            "tw_value": round(total_tw_value, 4),
            "cn_value": round(total_cn_value, 4)
        }
        # 在儲存時傳入今天的日期
        update_history_log(snapshot_data, datetime.now().date())
        print("[Scheduler] Snapshot job finished.")


@app.route('/')
def index():
    return render_template('index.html')

# --- (修改) 讀取邏輯改為 SQL ---
@app.route('/api/portfolio', methods=['GET'])
def get_portfolio():
    portfolio = load_portfolio()
    tickers = list(set(stock['ticker'] for stock in portfolio))
    if not tickers:
        return jsonify({"stocks": [], "totals": {}})
    rate_cny_twd = get_cny_to_twd_rate()
    live_data = get_current_prices(tickers) 
    
    # (檢查名稱快取 - 邏輯不變)
    need_to_save_portfolio = False
    for stock in portfolio:
        if not stock.get("name") or stock.get("name") == stock.get("ticker"):
            try:
                print(f"Metadata missing. Fetching name for {stock['ticker']}...")
                ticker_info = yf.Ticker(stock['ticker']).info
                stock["name"] = ticker_info.get('shortName', ticker_info.get('longName', stock['ticker']))
                print(f"Found name: {stock['name']}")
                need_to_save_portfolio = True
            except Exception as e:
                print(f"Error fetching metadata for {stock['ticker']}: {e}")
                stock["name"] = stock['ticker']
                need_to_save_portfolio = True
    if need_to_save_portfolio:
        print("Saving new names to portfolio.json...")
        save_portfolio(portfolio)

    # (計算總覽 - 邏輯不變)
    total_market_value_twd = 0
    total_cost_basis_twd = 0
    total_today_pl_twd = 0
    total_prev_close_value_twd = 0 # (新) 增加一個變數來計算昨日收盤總市值
    total_tw_value = 0
    total_cn_value = 0
    processed_stocks = []
    for stock in portfolio:
        ticker = stock['ticker']
        shares = float(stock.get('shares', 0))
        avg_cost = float(stock.get('avg_cost', 0))
        currency = stock.get("currency", "TWD") 
        stock_name = stock.get("name") 
        ticker_data = live_data.get(ticker, {})
        current_price_original = ticker_data.get('price', 0)
        prev_close_original = ticker_data.get('previous_close', 0)
        
        # (新) 計算昨日收盤市值 (原始貨幣)
        prev_close_market_value_original = prev_close_original * shares
        
        cost_basis_original = avg_cost * shares
        market_value_original = current_price_original * shares
        cost_basis_twd = cost_basis_original
        market_value_twd = market_value_original
        
        # (新) 計算昨日收盤市值 (台幣)
        prev_close_market_value_twd = prev_close_market_value_original

        if currency == "CNY":
            cost_basis_twd *= rate_cny_twd
            market_value_twd *= rate_cny_twd
            prev_close_market_value_twd *= rate_cny_twd # (新) 同樣要乘上匯率
            
        pl_twd = market_value_twd - cost_basis_twd
        today_pl_original = (current_price_original - prev_close_original) * shares
        today_pl_twd = today_pl_original
        if currency == "CNY":
            today_pl_twd *= rate_cny_twd
        total_market_value_twd += market_value_twd
        total_cost_basis_twd += cost_basis_twd
        total_today_pl_twd += today_pl_twd
        total_prev_close_value_twd += prev_close_market_value_twd # (新) 累加昨日收盤總市值
        if currency == "TWD":
            total_tw_value += market_value_twd
        elif currency == "CNY":
            total_cn_value += market_value_twd
        # 計算漲幅百分比
        change_percent = ((current_price_original - prev_close_original) / prev_close_original) * 100 if prev_close_original != 0 else 0
        
        processed_stocks.append({
            "ticker": ticker, "name": stock_name, "currency": currency,
            "shares": shares, "avg_cost": avg_cost,
            "current_price": current_price_original,
            "previous_close": prev_close_original,
            "change_percent": change_percent,  # 新增漲幅欄位
            "market_value": market_value_twd,
            "pl": pl_twd,
            "today_pl": today_pl_twd,
            "pl_percent": (pl_twd / cost_basis_twd) * 100 if cost_basis_twd != 0 else 0
        })
    total_pl_twd = total_market_value_twd - total_cost_basis_twd
    total_pl_percent = (total_pl_twd / total_cost_basis_twd) * 100 if total_cost_basis_twd != 0 else 0
    
    # (*** 修正點 ***)
    # (讀取 "last_close_value" 從 DB 讀取)
    today_str = datetime.now().strftime('%Y-%m-%d')
    last_close_value = 0
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        # (SQL 查詢：抓取早於 "今天" 的最後一筆 "total")
        cursor.execute("SELECT total FROM daily_history WHERE date < ? ORDER BY date DESC LIMIT 1", (today_str,))
        row = cursor.fetchone()
        if row:
            last_close_value = row['total']
        conn.close()
    except Exception as e:
        print(f"Error reading last_close_value from SQLite: {e}")

    # (*** 修正點 ***)
    # (改用新計算的昨日總市值來計算每日變動)
    daily_diff = total_market_value_twd - total_prev_close_value_twd
    daily_diff_percent = (daily_diff / total_prev_close_value_twd) * 100 if total_prev_close_value_twd != 0 else 0
    
    return jsonify({
        "stocks": processed_stocks,
        "totals": {
            "market_value": total_market_value_twd,
            "cost_basis": total_cost_basis_twd,
            "pl": total_pl_twd,
            "pl_percent": total_pl_percent,
            "today_pl": total_today_pl_twd,
            "daily_diff": daily_diff,
            "daily_diff_percent": daily_diff_percent,
            "last_close_value": last_close_value,
            "tw_value": total_tw_value,
            "cn_value": total_cn_value,
            "cny_rate": rate_cny_twd
        }
    })

# --- (修改) 讀取邏輯改為 SQL ---
@app.route('/api/history_summary', methods=['GET'])
def get_history_summary():
    
    daily_data = {}
    month_start_val = 0
    month_end_val = 0
    year_start_val = 0
    year_end_val = 0
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    current_month_prefix = today_str[:7] + '%' # "2025-10%"
    current_year_prefix = today_str[:4] + '%' # "2025%"

    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        # 1. (新) 取得所有 daily data (用於圖表)
        cursor.execute("SELECT date, total, tw_value, cn_value FROM daily_history ORDER BY date ASC")
        rows = cursor.fetchall()
        for row in rows:
            daily_data[row['date']] = {
                "total": row['total'],
                "tw_value": row['tw_value'],
                "cn_value": row['cn_value']
            }

        # 2. (新) 取得本月(MTD)資料
        cursor.execute("SELECT total FROM daily_history WHERE date LIKE ? ORDER BY date ASC LIMIT 1", (current_month_prefix,))
        row = cursor.fetchone()
        if row: month_start_val = row['total']
        
        cursor.execute("SELECT total FROM daily_history WHERE date LIKE ? ORDER BY date DESC LIMIT 1", (current_month_prefix,))
        row = cursor.fetchone()
        if row: month_end_val = row['total']

        # 3. (新) 取得本年(YTD)資料
        cursor.execute("SELECT total FROM daily_history WHERE date LIKE ? ORDER BY date ASC LIMIT 1", (current_year_prefix,))
        row = cursor.fetchone()
        if row: year_start_val = row['total']
        
        cursor.execute("SELECT total FROM daily_history WHERE date LIKE ? ORDER BY date DESC LIMIT 1", (current_year_prefix,))
        row = cursor.fetchone()
        if row: year_end_val = row['total']
        
        conn.close()
        
    except Exception as e:
        print(f"Error reading history_summary from SQLite: {e}")

    month_diff = month_end_val - month_start_val
    month_diff_percent = (month_diff / month_start_val) * 100 if month_start_val != 0 else 0
    
    year_diff = year_end_val - year_start_val
    year_diff_percent = (year_diff / year_start_val) * 100 if year_start_val != 0 else 0

    return jsonify({
        "daily": daily_data, # (傳回 v2 物件結構)
        "monthly": {
            "start_value": month_start_val, "end_value": month_end_val,
            "diff": month_diff, "percent": month_diff_percent
        },
        "yearly": {
            "start_value": year_start_val, "end_value": year_end_val,
            "diff": year_diff, "percent": year_diff_percent
        }
    })

# (CRUD 路由 ... 保持不變)
@app.route('/api/stock', methods=['POST'])
def add_stock():
    data = request.json
    if not data or 'ticker' not in data or 'shares' not in data or 'avg_cost' not in data:
        return jsonify({"status": "error", "message": "Missing data"}), 400
    portfolio = load_portfolio()
    ticker = data['ticker']
    existing = next((s for s in portfolio if s['ticker'] == ticker), None)
    if existing:
        return jsonify({"status": "error", "message": "Ticker already exists. Use update instead."}), 409
    stock_name = data.get('name')
    if not stock_name:
        try:
            print(f"Fetching metadata for new stock: {ticker}...")
            ticker_info = yf.Ticker(ticker).info
            stock_name = ticker_info.get('shortName', ticker_info.get('longName', ticker))
        except Exception as e:
            print(f"Could not fetch name for {ticker}: {e}")
            stock_name = ticker
    else:
        print(f"Using user-provided name: {stock_name}")
    new_stock = {
        "ticker": ticker,
        "shares": float(data['shares']),
        "avg_cost": float(data['avg_cost']),
        "currency": data.get('currency', 'TWD'),
        "name": stock_name
    }
    portfolio.append(new_stock)
    save_portfolio(portfolio)
    return jsonify({"status": "success", "stock": new_stock}), 201

@app.route('/api/stock/<path:ticker_key>', methods=['PUT'])
def update_stock(ticker_key):
    data = request.json
    if not data or 'shares' not in data or 'avg_cost' not in data:
        return jsonify({"status": "error", "message": "Missing data"}), 400
    portfolio = load_portfolio()
    stock_to_update = next((s for s in portfolio if s['ticker'] == ticker_key), None)
    if not stock_to_update:
        return jsonify({"status": "error", "message": "Ticker not found"}), 404
    stock_to_update['shares'] = float(data['shares'])
    stock_to_update['avg_cost'] = float(data['avg_cost'])
    stock_to_update['currency'] = data.get('currency', 'TWD')
    if 'name' in data:
        stock_name = data['name']
        if not stock_name:
            stock_to_update['name'] = ticker_key
        else:
            stock_to_update['name'] = stock_name
    save_portfolio(portfolio)
    return jsonify({"status": "success", "stock": stock_to_update})

@app.route('/api/stock/<path:ticker_key>', methods=['DELETE'])
def delete_stock(ticker_key):
    portfolio = load_portfolio()
    new_portfolio = [s for s in portfolio if s['ticker'] != ticker_key]
    if len(new_portfolio) == len(portfolio):
        return jsonify({"status": "error", "message": "Ticker not found"}), 404
    save_portfolio(new_portfolio)
    return jsonify({"status": "success"})

@app.route('/api/stock_history/<path:ticker>', methods=['GET'])
def get_stock_history(ticker):
    try:
        # 使用yfinance獲取歷史數據 (近30天)
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(period="30d")
        
        if hist.empty:
            return jsonify({"status": "error", "message": "No historical data found"}), 404
            
        # 轉換為JSON格式
        history_data = []
        for index, row in hist.iterrows():
            history_data.append({
                "date": index.strftime('%Y-%m-%d'),
                "close": round(row['Close'], 4)
            })
            
        return jsonify({
            "status": "success",
            "ticker": ticker,
            "history": history_data
        })
    except Exception as e:
        print(f"Error fetching stock history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/backfill_history', methods=['POST'])
def backfill_history():
    """
    手動回補指定日期的歷史資料
    需要一個 'date' 參數，格式為 'YYYY-MM-DD'
    """
    data = request.json
    date_str = data.get('date')
    if not date_str:
        return jsonify({"status": "error", "message": "Missing date parameter"}), 400

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    print(f"\n[Manual Backfill] Running job for {date_str}...")
    
    # 這裡的邏輯與 save_daily_snapshot 非常相似
    portfolio = load_portfolio()
    tickers = list(set(stock['ticker'] for stock in portfolio))
    if not tickers:
        print("[Manual Backfill] No portfolio found. Skipping.")
        return jsonify({"status": "skipped", "message": "No portfolio found."})

    # 注意：回補時我們無法得知當天的確切匯率，因此會使用目前的即時匯率
    # 這可能會造成微小誤差，但對於補資料來說是可以接受的
    rate_cny_twd = get_cny_to_twd_rate()
    prices_data = get_prices_for_date(tickers, target_date)

    total_market_value_twd = 0
    total_tw_value = 0
    total_cn_value = 0
    for stock in portfolio:
        ticker = stock['ticker']
        shares = float(stock.get('shares', 0))
        currency = stock.get("currency", "TWD")
        
        # 從 get_prices_for_date 獲取價格
        close_price_original = prices_data.get(ticker, {}).get('price', 0)
        
        market_value_original = close_price_original * shares
        market_value_twd = market_value_original
        if currency == "CNY":
            market_value_twd *= rate_cny_twd
            
        total_market_value_twd += market_value_twd
        if currency == "TWD":
            total_tw_value += market_value_twd
        elif currency == "CNY":
            total_cn_value += market_value_twd
            
    snapshot_data = {
        "total": round(total_market_value_twd, 4),
        "tw_value": round(total_tw_value, 4),
        "cn_value": round(total_cn_value, 4)
    }
    
    # 傳入 target_date 以儲存到正確的日期
    update_history_log(snapshot_data, target_date)
    
    print(f"[Manual Backfill] Job for {date_str} finished.")
    return jsonify({
        "status": "success",
        "date": date_str,
        "snapshot": snapshot_data
    })

@app.route('/api/trigger_snapshot', methods=['POST'])
def trigger_snapshot():
    """
    觸發快照任務。
    這個端點會被獨立的排程器腳本呼叫。
    """
    try:
        save_daily_snapshot()  # 執行快照任務
        return jsonify({"status": "success", "message": "Snapshot triggered successfully."})
    except Exception as e:
        print(f"Error triggering snapshot: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("Starting Flask app...")
    app.run(debug=True, host='0.0.0.0', port=5000)
