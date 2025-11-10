import json
import yfinance as yf
from flask import Flask, render_template, jsonify, request, current_app
from datetime import datetime, date, timedelta, time
import os
import requests
import pandas as pd
import re # (新) 匯入 re
from time import time as timestamp
import sqlite3 # (新) 匯入 sqlite
from threading import Thread # (新) 匯入 Thread
from collections import deque
import logging


BACKFILL_STATUS = {
    "running": False,
    "message": "尚未開始"
}

# Initialize debug message storage
DEBUG_MESSAGES = deque(maxlen=100)  # Store up to 100 debug messages

# Custom print function to capture debug messages
original_print = print
def debug_print(*args, **kwargs):
    # Capture the message
    message = ' '.join(str(arg) for arg in args)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    debug_entry = f"[{timestamp}] {message}"
    
    # Add to debug message buffer
    DEBUG_MESSAGES.append(debug_entry)
    
    # Call original print function
    original_print(*args, **kwargs)

# Override the built-in print function
import builtins
builtins.print = debug_print

# Custom logging handler to capture log messages
class DebugMessageHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        DEBUG_MESSAGES.append(log_entry)

# Set up logging to use our custom handler
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
debug_handler = DebugMessageHandler()
debug_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logger.addHandler(debug_handler)

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

def get_current_prices(tickers):
    """
    (已修改) 三路混合：獲取即時價格
    - .TW 股票: 優先使用 get_mis_tw_prices
    - .SS/.SZ 股票: 優先使用 get_sina_current_prices
    - 其他股票 (及備援): 使用 get_yfinance_current_prices
    """
    if not tickers:
        return {}
    
    print(f"\n[Hybrid Prices] Fetching: {' '.join(tickers)}")
    
    # 1. 分離 Tickers
    tw_tickers = [t for t in tickers if t.endswith('.TW') or t.endswith('.TWO')] # (修改)
    china_tickers = [t for t in tickers if t.endswith('.SS') or t.endswith('.SZ')]
    yfinance_tickers = [t for t in tickers if 
                        not t.endswith('.TW') and 
                        not t.endswith('.TWO') and
                        not t.endswith('.SS') and 
                        not t.endswith('.SZ')]
    
    all_stock_data = {}
    
    # 2. 抓取 .TW 股票 (使用 MIS API)
    if tw_tickers:
        mis_data = get_mis_tw_prices(tw_tickers)
        # (新) 注入來源標籤
        for ticker, data in mis_data.items():
            data['source'] = 'MIS'
        all_stock_data.update(mis_data)
        
        failed_tw_tickers = [t for t in tw_tickers if t not in mis_data]
        if failed_tw_tickers:
            print(f"[Hybrid Prices] MIS API failed for: {failed_tw_tickers}. Adding to yfinance fallback.")
            yfinance_tickers.extend(failed_tw_tickers) 

    # 3. 抓取陸股 (使用 Sina)
    if china_tickers:
        print(f"[Hybrid Prices] Fetching {len(china_tickers)} China stocks via Sina...")
        sina_data = get_sina_current_prices(china_tickers)
        # (新) 注入來源標籤
        for ticker, data in sina_data.items():
            data['source'] = 'Sina'
        all_stock_data.update(sina_data)
        
        failed_sina_tickers = [t for t in china_tickers if t not in sina_data]
        if failed_sina_tickers:
            print(f"[Hybrid Prices] Sina failed for: {failed_sina_tickers}. Adding to yfinance fallback.")
            yfinance_tickers.extend(failed_sina_tickers) 

    # 4. 抓取其他股票 (及抓取失敗的) (使用 yfinance)
    if yfinance_tickers:
        print(f"[Hybrid Prices] Fetching {len(yfinance_tickers)} stocks via yfinance...")
        yfinance_data = get_yfinance_current_prices(yfinance_tickers)
        # (新) 注入來源標籤
        for ticker, data in yfinance_data.items():
            data['source'] = 'yfinance'
        all_stock_data.update(yfinance_data)
        
    # 5. 最終檢查 (不變)
    for ticker in tickers:
        if ticker not in all_stock_data:
            print(f"Warning: No price data found for {ticker} from any source.")
            # (新) 標記來源為 N/A
            all_stock_data[ticker] = {"price": 0, "previous_close": 0, "source": "N/A"}

    return all_stock_data

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

def get_previous_day_data(target_date):
    """
    獲取指定日期前一天的資料
    """
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        
        # 查找早於目標日期的最後一筆資料
        cursor.execute("SELECT date, total, tw_value, cn_value FROM daily_history WHERE date < ? ORDER BY date DESC LIMIT 1",
                      (target_date.strftime('%Y-%m-%d'),))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "date": row['date'],
                "total": row['total'],
                "tw_value": row['tw_value'],
                "cn_value": row['cn_value']
            }
        return None
    except Exception as e:
        print(f"Error getting previous day data: {e}")
        return None

def get_mis_tw_prices(tickers):
    """
    (已修改) 使用 mis.twse.com.tw API 批次抓取台股即時價格
    - 新增對 .TWO (OTC) 的支援
    - 新增 'stock_code' 到 'yfinance_ticker' 的映射表
    """
    if not tickers:
        return {}

    base_url = "http://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    
    query_parts = []
    # (新) 建立一個 '查詢代碼' (e.g., '00679B') 到 '原始YF Ticker' (e.g., '00679B.TWO') 的映射
    code_to_yf_map = {} 
    
    for ticker_str in tickers:
        try:
            # '2330.TW' -> '2330'
            # '00679B.TWO' -> '00679B'
            stock_code = ticker_str.split('.')[0]
            query_key = f"{stock_code}.tw" # 統一的查詢格式, e.g., '00679B.tw'
            
            if ticker_str.endswith('.TW'):
                query_parts.append(f"tse_{query_key}")
            elif ticker_str.endswith('.TWO'):
                # 根據您的資訊，.TWO (OTC) 對應 otc_
                query_parts.append(f"otc_{query_key}")
            else:
                # (備援) 如果是不明的 .TW/.TWO 結尾，兩個都查
                query_parts.append(f"tse_{query_key}")
                query_parts.append(f"otc_{query_key}")
            
            # (新) 儲存映射: '00679B': '00679B.TWO'
            code_to_yf_map[stock_code] = ticker_str
            
        except Exception as e:
            print(f"[MIS API] Error processing ticker_str {ticker_str}: {e}")

    if not query_parts:
        return {}
        
    # (新) 使用 set() 移除重複的查詢 (例如 'tse_2330.tw|otc_2330.tw')
    query_string = '|'.join(list(set(query_parts)))
    
    params = {
        "ex_ch": query_string,
        "_": int(timestamp()) # 避免 cache
    }
    
    stock_data = {}
    try:
        print(f"[MIS API] Fetching {len(tickers)} TW/TWO stocks...")
        res = requests.get(base_url, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()

        if data.get("rtcode") != "0000" or "msgArray" not in data:
            print("[MIS API] Error: Invalid response from MIS API")
            return {}

        for stock in data.get("msgArray", []):
            stock_code = stock.get("c") # e.g., '00679B'
            if not stock_code:
                continue

            # (修改) 使用映射表找回原始的 yfinance Ticker
            # e.g., '00679B' -> '00679B.TWO'
            yfinance_key = code_to_yf_map.get(stock_code)
            
            if not yfinance_key:
                # 找不到對應的 key (例如 API 回傳了我們沒查詢的東西)
                continue

            current_price = stock.get("z", "0")
            prev_close = stock.get("y", "0")

            if current_price == "-" or current_price == "": current_price = "0"
            if prev_close == "-" or prev_close == "": prev_close = "0"
                
            if float(current_price) == 0:
                # 新增從 a/b 欄位提取第一個數值的邏輯
                # 嘗試從 a 欄位取得第一個數值
                a_field = stock.get("a", "")
                if a_field and a_field != "-":
                    try:
                        # 分離第一個數值
                        first_a_value = a_field.split("_")[0]
                        if first_a_value and float(first_a_value) > 0:
                            current_price = first_a_value
                        else:
                            raise ValueError("First a value is zero or invalid")
                    except (ValueError, IndexError):
                        # 如果 a 欄位無法取得有效值，嘗試從 b 欄位取得
                        b_field = stock.get("b", "")
                        if b_field and b_field != "-":
                            try:
                                # 分離第一個數值
                                first_b_value = b_field.split("_")[0]
                                if first_b_value and float(first_b_value) > 0:
                                    current_price = first_b_value
                                else:
                                    raise ValueError("First b value is zero or invalid")
                            except (ValueError, IndexError):
                                # 如果 a/b 欄位都無法取得有效值，使用開盤價或昨收價
                                open_price = stock.get("o", "0")
                                if open_price != "0" and open_price != "-":
                                    current_price = open_price
                                else:
                                    current_price = prev_close
                        else:
                            # 如果 b 欄位為空，使用開盤價或昨收價
                            open_price = stock.get("o", "0")
                            if open_price != "0" and open_price != "-":
                                current_price = open_price
                            else:
                                current_price = prev_close
                else:
                    # 如果 a 欄位為空，嘗試從 b 欄位取得
                    b_field = stock.get("b", "")
                    if b_field and b_field != "-":
                        try:
                            # 分離第一個數值
                            first_b_value = b_field.split("_")[0]
                            if first_b_value and float(first_b_value) > 0:
                                current_price = first_b_value
                            else:
                                raise ValueError("First b value is zero or invalid")
                        except (ValueError, IndexError):
                            # 如果 b 欄位無法取得有效值，使用開盤價或昨收價
                            open_price = stock.get("o", "0")
                            if open_price != "0" and open_price != "-":
                                current_price = open_price
                            else:
                                current_price = prev_close
                    else:
                        # 如果 b 欄位也為空，使用開盤價或昨收價
                        open_price = stock.get("o", "0")
                        if open_price != "0" and open_price != "-":
                            current_price = open_price
                        else:
                            current_price = prev_close

            stock_data[yfinance_key] = {
                "price": float(current_price),
                "previous_close": float(prev_close)
            }
        
        print(f"[MIS API] Success. Found {len(stock_data)} stocks.")
        return stock_data

    except Exception as e:
        print(f"[MIS API] Request failed: {e}. Will fall back to yfinance.")
        return {}


def get_sina_current_prices(tickers):
    """
    (新) 使用 Sina 即時 API 批次抓取陸股價格
    tickers: ['601138.SS']
    """
    stock_data = {}
    if not tickers:
        return stock_data

    # 1. 轉換為 Sina 格式 (e.g., '601138.SS' -> 'sh601138')
    sina_symbols = []
    # 建立一個地圖，讓我們能從 'sh601138' 找回 '601138.SS'
    yf_to_sina_map = {}
    
    for yf_ticker in tickers:
        try:
            code, market = yf_ticker.split('.')
            if market.upper() == 'SS':
                sina_symbol = f"sh{code}"
            elif market.upper() == 'SZ':
                sina_symbol = f"sz{code}"
            else:
                continue # 不是可識別的陸股代號
                
            sina_symbols.append(sina_symbol)
            # 儲存 'sh601138': '601138.SS' 的對應關係
            yf_to_sina_map[sina_symbol] = yf_ticker
            
        except Exception as e:
            print(f"[Sina] Error splitting ticker {yf_ticker}: {e}")

    if not sina_symbols:
        return {}

    # 2. 建立批次 API 請求
    api_url = f"http://hq.sinajs.cn/list={','.join(sina_symbols)}"
    headers = {'Referer': 'http://finance.sina.com.cn/'}
    print(f"[Sina] Fetching: {api_url}")

    try:
        res = requests.get(api_url, headers=headers, timeout=5)
        res.raise_for_status()
        raw_text = res.text
        
        # 3. 解析 (Sina 會回傳多行，每行用 ; 分隔)
        lines = raw_text.strip().split(';\n')
        for line in lines:
            if not line:
                continue
            
            # 找出 hq_str_sh601138="...
            match = re.search(r'var hq_str_(\w+)="([^"]+)"', line)
            if not match:
                continue
                
            sina_symbol = match.group(1) # e.g., 'sh601138'
            data_string = match.group(2)
            parts = data_string.split(',')
            
            # 欄位 2: 昨日收盤價
            # 欄位 3: 目前市價
            if len(parts) > 3:
                prev_close = parts[2]
                current_price = parts[3]
                
                # 用地圖找回 yfinance 的 key
                yf_ticker = yf_to_sina_map.get(sina_symbol)

                if yf_ticker and float(current_price) > 0:
                    stock_data[yf_ticker] = {
                        "price": float(current_price),
                        "previous_close": float(prev_close)
                    }
                elif yf_ticker:
                    # (備援) 如果目前市價為 0 (例如剛開盤)，使用昨收
                    stock_data[yf_ticker] = {
                        "price": float(prev_close),
                        "previous_close": float(prev_close)
                    }
    except Exception as e:
        print(f"Error [Sina] processing request: {e}")
        # 發生錯誤時回傳空 dict，主控函式會改用 yfinance 備援
        
    return stock_data

def get_yfinance_current_prices(tickers):
    if not tickers:
        return {}
    print(f"[yfinance] Fetching prices: {' '.join(tickers)}")
    data = yf.Tickers(' '.join(tickers))
    stock_data = {}
    today = datetime.now().date()

    for ticker_str, ticker_obj in data.tickers.items():
        try:
            original_ticker_key = next(t for t in tickers if t.upper() == ticker_str.upper())
            
            price = None
            prev_close = None

            # --- 步驟 1: 優先獲取 "昨日收盤價" (來源: history) ---
            # 這是最可靠的昨收來源
            try:
                hist = ticker_obj.history(period='5d')
                if not hist.empty:
                    # 確保索引是日期 (無時間)
                    hist.index = hist.index.date
                    # 找出所有 "今天以前" 的資料
                    past_data = hist[hist.index < today]
                    if not past_data.empty:
                        # 取得 "今天以前" 的最後一筆收盤價
                        prev_close = past_data['Close'].iloc[-1]
            except Exception as e:
                print(f"  -> [yfinance hist] Error processing history for {ticker_str}: {e}")

            # --- 步驟 2: 優先獲取 "目前市價" (來源: fast_info) ---
            # 這是最快的即時價來源
            try:
                info = ticker_obj.fast_info
                price = info.get('last_price', info.get('regularMarketPrice'))
                
                # 如果 fast_info 失敗，且 history 有資料，使用 history 的 "最後一筆" (可能是今天)
                if (not price or price == 0) and not hist.empty:
                    price = hist['Close'].iloc[-1]

                # 如果 fast_info 的昨收是唯一來源 (步驟1 失敗時)
                if (not prev_close or prev_close == 0):
                    prev_close = info.get('previousClose')
                    
            except Exception as e:
                print(f"  -> [yfinance fast_info] Error processing fast_info for {ticker_str}: {e}")


            # --- 步驟 3: 最終備援與清理 (嚴格邏輯) ---
            
            # 情況 1: 盤前/盤中 (市價為 0，但昨收有值)
            if (not price or price == 0) and (prev_close and prev_close > 0):
                price = prev_close
            
            # 情況 2: 新股/資料不全 (市價有值，但昨收為 0)
            elif (price and price > 0) and (not prev_close or prev_close == 0):
                prev_close = price
            
            # 情況 3: 找不到任何資料
            elif (not price or price == 0) and (not prev_close or prev_close == 0):
                price = 0
                prev_close = 0

            stock_data[original_ticker_key] = {
                "price": float(price), 
                "previous_close": float(prev_close)
            }
        
        except Exception as e:
            print(f"Error [yfinance price] processing {ticker_str}: {e}")
            matching_tickers = [t for t in tickers if t.upper() == ticker_str.upper()]
            if matching_tickers:
                stock_data[matching_tickers[0]] = {"price": 0, "previous_close": 0}
                
    return stock_data

def get_yfinance_prices_for_date(tickers, target_date):
    """
    (已更名) 這是 yfinance 的版本，作為備用
    """
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

            price_found = False
            if not price_series.empty:
                # 獲取該日期的收盤價
                price = price_series.iloc[-1]
                if not pd.isna(price): 
                    stock_data[ticker] = {"price": price}
                    price_found = True

            if not price_found:
                 # 如果當天沒有資料，嘗試往前找最近的一個交易日
                temp_end = target_date
                temp_start = temp_end - timedelta(days=14) # 最多往前找7天
                temp_hist = yf.download(ticker, start=temp_start, end=temp_end, interval="1d")
                if not temp_hist.empty:
                    price = temp_hist['Close'].iloc[-1]
                    print(f"  -> [yfinance] {ticker} on {target_date.strftime('%Y-%m-%d')} has no data, using last valid price: {price:.2f} on {temp_hist.index[-1].strftime('%Y-%m-%d')}")
                    stock_data[ticker] = {"price": price}
                else:
                    price = 0
                    print(f"  -> [yfinance] Could not find any recent price for {ticker}")
                    stock_data[ticker] = {"price": 0}

        except Exception as e:
            print(f"[yfinance] Error processing historical data for {ticker}: {e}")
            stock_data[ticker] = {"price": 0}
            
    return stock_data


def get_prices_for_date(tickers, target_date):
    """
    (已修改) 簡化混合：獲取指定日期的收盤價
    - .TW 股票: 使用 yfinance
    - 其他股票 (包含 .SS/.SZ 及備援): 使用 yfinance
    """
    if not tickers:
        return {}
    
    print(f"\n[Hybrid Backfill] Getting prices for {target_date.strftime('%Y-%m-%d')}")
    
    target_date_str = target_date.strftime('%Y-%m-%d')
    
    # 1. 分離 Tickers
    china_tickers = []
    yfinance_tickers = []
    
    for t in tickers:
        if t.endswith('.SS') or t.endswith('.SZ'):
            # 將中國股票單獨分離出來
            china_tickers.append(t)
        else:
            yfinance_tickers.append(t)
            
    stock_data = {}
    
    # 2. 處理中國股票 (.SS/.SZ)
# (這是新的程式碼，使用 Sina 優先)
    if china_tickers:
       print(f"[Hybrid Backfill] Querying Sina for {len(china_tickers)} China tickers (for Snapshot)...")
    
       # 優先呼叫 Sina API 獲取即時 (收盤) 價
       sina_data = get_sina_current_prices(china_tickers) #
    
       # 遍歷所有要求的陸股
       for ticker in china_tickers:
           # 檢查 Sina 是否成功回傳了這支股票
           if ticker in sina_data and sina_data[ticker].get("price", 0) > 0:
               # 成功：Sina 的 'price' 在 15:30 就是收盤價
               stock_data[ticker] = {"price": sina_data[ticker].get("price")}
    
           else:
               # 失敗：Sina 抓不到，降級改用 Yahoo Finance (yfinance) 作為備援
               print(f"  -> [Hybrid Backfill] Sina failed for {ticker}, falling back to yfinance...")
    
               # 呼叫 yfinance 函式 (這也是原有的邏輯)
               price_data = get_yfinance_prices_for_date([ticker], target_date) #
    
               if ticker in price_data and price_data[ticker].get("price", 0) != 0:
                   stock_data[ticker] = {"price": price_data[ticker]["price"]}
               else:
                   # 備援也失敗
                   print(f"  -> [Hybrid Backfill] YFinance (fallback) also failed for {ticker}.")
                   stock_data[ticker] = {"price": 0}

    # 3. (修改) 處理所有其他股票 (使用 yfinance)
    if yfinance_tickers:
        print(f"[Hybrid Backfill] Calling yfinance fallback for {len(yfinance_tickers)} tickers...")
        yfinance_data = get_yfinance_prices_for_date(yfinance_tickers, target_date)
        stock_data.update(yfinance_data)
        
    # 4. 最終檢查
    for ticker in tickers:
        if ticker not in stock_data:
            print(f"Warning: No price data found for {ticker} from any source.")
            stock_data[ticker] = {"price": 0}
        elif stock_data[ticker].get("price", 0) == 0:
            # 如果價格為 0，嘗試往前查找
            print(f"Warning: Price is 0 for {ticker} on {target_date_str}, attempting backfill...")
            if ticker.endswith('.SS') or ticker.endswith('.SZ'):
                # 中國股票使用 yfinance 往前查找
                price_data = get_yfinance_prices_for_date([ticker], target_date)
                if ticker in price_data and price_data[ticker]["price"] != 0:
                    stock_data[ticker] = price_data[ticker]
                # 如果 yfinance 也無法獲取有效價格，保持原來的 0 值
            else:
                # 其他股票使用 yfinance 往前查找
                price_data = get_yfinance_prices_for_date([ticker], target_date)
                if ticker in price_data:
                    stock_data[ticker] = price_data[ticker]
            
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

def save_daily_snapshot():
    with app.app_context(): 
        # (重要) 建議將排程器時間改為 18:00，以確保 TWSE 資料已發布
        print(f"\n[Scheduler] Running Daily Snapshot Job... ({datetime.now()})")
        portfolio = load_portfolio() #
        tickers = list(set(stock['ticker'] for stock in portfolio)) #
        if not tickers:
            print("[Scheduler] No portfolio found. Skipping snapshot.")
            return
            
        rate_cny_twd = get_cny_to_twd_rate() #
        
        # --- *** (這就是您需要修改的地方) *** ---
        # (舊) prices_data = get_prices_for_date(tickers, datetime.now().date()) 
        # (新) 改用即時API。因為快照在15:30執行，即時價=收盤價。
        prices_data = get_current_prices(tickers) 
        # --- *** (修改結束) *** ---
        
        total_market_value_twd = 0 #
        total_tw_value = 0 #
        total_cn_value = 0 #
        for stock in portfolio:
            # ... (此函式的其餘部分 完全保持不變) ...
            ticker = stock['ticker']
            shares = float(stock.get('shares', 0))
            currency = stock.get("currency", "TWD") 
            
            # 這裡的 .get('price', 0) 保持不變，因為 get_current_prices 的回傳結構是相容的
            current_price_original = prices_data.get(ticker, {}).get('price', 0) #
            
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
        data_source = ticker_data.get('source', 'N/A') # <--- (新) 在這裡加入
        
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
            "pl_percent": (pl_twd / cost_basis_twd) * 100 if cost_basis_twd != 0 else 0,
            "data_source": data_source # <--- (新) 在這裡加入
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

def get_prices_for_date_yahoo_only(tickers, target_date):
    """
    (新) 為了簡化回補邏輯，此函式 *只* 使用 yfinance 抓取 *所有* 股票。
    它會嚴格抓取 'target_date' 當天的收盤價。
    如果 'target_date' 當天無資料（休市），則回傳 0。
    (此版本 *移除* 了 yfinance 往前 14 天查找的備援邏輯)
    """
    if not tickers:
        return {}
    
    # yfinance 抓取需要一個區間
    start_date = target_date
    end_date = target_date + timedelta(days=1)
    
    print(f"[Backfill Yahoo Only] Fetching historical prices for {target_date.strftime('%Y-%m-%d')} for tickers: {' '.join(tickers)}")
    
    try:
        hist_data = yf.download(
            ' '.join(tickers),
            start=start_date,
            end=end_date,
            interval="1d",
            group_by='ticker',
            progress=False # 關閉下載進度條
        )
    except Exception as e:
        print(f"[Backfill Yahoo Only] yf.download FAILED: {e}")
         # 如果 yf.download 本身失敗，為所有股票回傳 0
        return {ticker: {"price": 0} for ticker in tickers}

    stock_data = {}
    for ticker in tickers:
        try:
            price_series = None
            
            # 處理 yf.download 在不同情況下的回傳結構
            if len(tickers) == 1:
                # 情況1: 只查詢一支股票
                if hist_data.empty:
                    price_series = pd.Series(dtype=float) # 建立空的 Series
                else:
                    price_series = hist_data['Close']
            else:
                # 情況2: 查詢多支股票
                if ticker not in hist_data or hist_data[ticker].empty:
                     price_series = pd.Series(dtype=float) # 建立空的 Series
                else:
                    price_series = hist_data[ticker]['Close']

            price_found = False
            if price_series is not None and not price_series.empty:
                # 獲取該日期的收盤價 (iloc[0] 應該就是 start_date)
                price = price_series.iloc[0] 
                if not pd.isna(price) and price > 0: 
                    stock_data[ticker] = {"price": price}
                    price_found = True

            if not price_found:
                 # (*** 關鍵變更 ***)
                 # 找不到 'target_date' 當天的資料（休市或錯誤）
                 # 我們*不再*往前查找，直接回傳 0
                 # print(f"  -> [Backfill Yahoo Only] No data for {ticker} on {target_date.strftime('%Y-%m-%d')}. Returning 0.")
                 stock_data[ticker] = {"price": 0}

        except Exception as e:
            print(f"[Backfill Yahoo Only] Error processing {ticker}: {e}")
            stock_data[ticker] = {"price": 0}
            
    return stock_data

def _run_backfill_for_single_date(target_date):
    """
    (已重寫) 執行單日回補的核心邏輯。
    - 使用 'get_prices_for_date_strict' 嚴格獲取當天價格。
    - 獨立檢查 'tw_value' 和 'cn_value'，如果任一為 0，則 *僅* 回填該市場。
    """
    print(f"\n[Backfill Logic] Running job for {target_date}...")
    
    portfolio = load_portfolio()
    tickers = list(set(stock['ticker'] for stock in portfolio))
    if not tickers:
        print("[Backfill Logic] No portfolio found. Skipping.")
        return {"status": "skipped", "message": "No portfolio found."}, None, None

    rate_cny_twd = get_cny_to_twd_rate()
    
    # (*** 變更點 1: 使用新的嚴格抓取函式 ***)
    # 這個函式只會抓 'target_date' 當天的價格，如果休市或失敗則回傳 0
    prices_data = get_prices_for_date_yahoo_only(tickers, target_date) 

    total_tw_value = 0
    total_cn_value = 0
    detailed_info = []
    
    for stock in portfolio:
        ticker = stock['ticker']
        shares = float(stock.get('shares', 0))
        currency = stock.get("currency", "TWD")
        
        # 'price' 可能是 0 (如果當天休市或抓取失敗)
        close_price_original = prices_data.get(ticker, {}).get('price', 0) 
        
        market_value_original = close_price_original * shares
        market_value_twd = market_value_original
        if currency == "CNY":
            market_value_twd *= rate_cny_twd
        
        # (*** 變更點 2: 分開累計市值 ***)
        # 我們只關心 TWD 和 CNY
        if currency == "TWD":
            total_tw_value += market_value_twd
        elif currency == "CNY":
            total_cn_value += market_value_twd
        # (其他貨幣如 USD 暫不計入 tw_value 或 cn_value)

        detailed_info.append({
            "ticker": ticker, "name": stock.get("name", ticker), "shares": shares,
            "currency": currency, "close_price_original": round(close_price_original, 4),
            "market_value_original": round(market_value_original, 4),
            "market_value_twd": round(market_value_twd, 4),
            "rate_used": rate_cny_twd if currency == "CNY" else 1.0
        })
    
    # (*** 變更點 3: 獨立的回填 (Backfill) 邏輯 ***)
    
    # 這是 'target_date' 當天計算出來的 "原始" 市值
    final_tw_value = round(total_tw_value, 4)
    final_cn_value = round(total_cn_value, 4)
    
    # 檢查是否需要從 "前一天" 繼承數據
    # 只要任一市場為 0，就觸發檢查
    if final_tw_value == 0 or final_cn_value == 0:
        print(f"[Backfill Logic] '{target_date}' TW or CN market value is 0. Fetching previous day data...")
        
        # 撈取 'target_date' 之前的 *最後一筆* 有效資料
        previous_day_data = get_previous_day_data(target_date) #
        
        if previous_day_data:
            print(f"[Backfill Logic] Found previous data from {previous_day_data['date']}")
            
            # 獨立判斷 (A): 如果 'target_date' 的台股市值為 0 (例如休市)，則使用前一天的台股市值
            if final_tw_value == 0:
                final_tw_value = previous_day_data.get("tw_value", 0)
                print(f"  -> [Backfill] Using previous TW value: {final_tw_value}")
            else:
                # (例如台股開市，但陸股休市)
                print(f"  -> [Backfill] Using 'target_date' TW value: {final_tw_value}")

            # 獨立判斷 (B): 如果 'target_date' 的陸股市值為 0 (例如休市)，則使用前一天的陸股市值
            if final_cn_value == 0:
                final_cn_value = previous_day_data.get("cn_value", 0)
                print(f"  -> [Backfill] Using previous CN value: {final_cn_value}")
            else:
                # (例如陸股開市，但台股休市)
                print(f"  -> [Backfill] Using 'target_date' CN value: {final_cn_value}")
                
        else:
            # 這是歷史記錄的第一天，找不到更早的資料
            print(f"[Backfill Logic] No previous day data found for {target_date}. Using 0.")
    else:
         print(f"[Backfill Logic] Both TW and CN values are non-zero for '{target_date}'. No backfill needed.")

    # (*** 變更點 4: 儲存最終結果 ***)
    
    # 總市值 = (可能被回填的台股) + (可能被回填的陸股)
    final_total = round(final_tw_value + final_cn_value, 4)
    
    snapshot_data = {
        "total": final_total,
        "tw_value": final_tw_value,
        "cn_value": final_cn_value
    }
    
    # 使用 INSERT OR REPLACE 儲存或覆蓋
    update_history_log(snapshot_data, target_date) #
    
    print(f"[Backfill Logic] Job for {target_date} finished.")
    
    # 回傳結果供 API 顯示
    return snapshot_data, detailed_info, rate_cny_twd

@app.route('/api/backfill_history', methods=['POST'])
def backfill_history():
    """
    (已修改)
    手動回補 "指定單日" 的歷史資料
    """
    data = request.json
    date_str = data.get('date')
    if not date_str:
        return jsonify({"status": "error", "message": "Missing date parameter"}), 400

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    try:
        # (新) 呼叫重構後的函式
        snapshot_data, detailed_info, rate_cny_twd = _run_backfill_for_single_date(target_date)
        
        if isinstance(snapshot_data, dict) and snapshot_data.get("status") == "skipped":
            return jsonify(snapshot_data)

        return jsonify({
            "status": "success",
            "date": date_str,
            "snapshot": snapshot_data,
            "detailed_info": detailed_info,
            "rate_cny_twd": rate_cny_twd
        })
    except Exception as e:
        print(f"[Manual Backfill] Error for {date_str}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def _execute_range_backfill(app, start_date_str, end_date_str):
    """
    (已修改) "範圍回補" 的背景執行緒，
    (新) 會更新 BACKFILL_STATUS 全域變數
    """
    global BACKFILL_STATUS
    
    with app.app_context():
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            if start_date > end_date:
                print("[Range Backfill] Error: Start date is after end date.")
                BACKFILL_STATUS = {"running": False, "message": "錯誤：開始日期晚於結束日期"}
                return

            print(f"[Range Backfill] Job started from {start_date_str} to {end_date_str}...")
            
            # (新) 初始化狀態
            BACKFILL_STATUS = {
                "running": True,
                "message": f"任務已啟動..."
            }
            
            current_date = start_date
            
            while current_date <= end_date:
                if not BACKFILL_STATUS["running"]: # (新) 允許外部中斷 (雖然目前沒做中斷按鈕)
                    print("[Range Backfill] Job aborted.")
                    break
                    
                if current_date.weekday() >= 5:
                    print(f"[Range Backfill] Skipping {current_date} (Weekend)")
                else:
                    msg = f"正在處理 {current_date}..."
                    print(f"[Range Backfill] {msg}")
                    BACKFILL_STATUS["message"] = msg
                    
                    try:
                        _run_backfill_for_single_date(current_date)
                        print(f"[Range Backfill] Successfully processed {current_date}.")
                    except Exception as e:
                        print(f"[Range Backfill] ERROR processing {current_date}: {e}")
                    
                    print(f"[Range Backfill] Waiting 6.1s to respect MIS API rate limit...")
                    import time as time_module
                    time_module.sleep(6.1)
                
                current_date += timedelta(days=1)
            
            print("[Range Backfill] Job finished.")
            BACKFILL_STATUS = {"running": False, "message": f"回補完成"}
        
        except Exception as e:
            print(f"[Range Backfill] FATAL ERROR: {e}")
            BACKFILL_STATUS = {"running": False, "message": f"嚴重錯誤: {e}"}


@app.route('/api/backfill_status', methods=['GET'])
def get_backfill_status():
    """
    (新) 獲取目前的回補任務狀態
    """
    global BACKFILL_STATUS
    return jsonify(BACKFILL_STATUS)

@app.route('/api/backfill_range', methods=['POST'])
def backfill_range():
    """
    (新)
    手動觸發 "範圍回補" 歷史資料
    """
    data = request.json
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')

    if not start_date_str or not end_date_str:
        return jsonify({"status": "error", "message": "Missing start_date or end_date"}), 400

    try:
        # 簡單驗證格式
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            return jsonify({"status": "error", "message": "Start date cannot be after end date"}), 400
        
        num_days = (end_date - start_date).days + 1

    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}), 400

    # (重要) 啟動背景執行緒
    # 我們傳遞 'app._get_current_object()' 來確保執行緒能正確取得 app context
    thread = Thread(target=_execute_range_backfill, args=(
        current_app._get_current_object(), # <-- 修正點 
        start_date_str, 
        end_date_str
    ))
    thread.daemon = True # 允許主程式退出
    thread.start()

    print(f"Starting range backfill thread for {num_days} days...")
    
    # (重要) 立即回傳 202 Accepted
    return jsonify({
        "status": "success", 
        "message": f"Range backfill job started for {num_days} days (from {start_date_str} to {end_date_str}). Check server logs for progress."
    }), 202

@app.route('/api/delete_history', methods=['POST'])
def delete_history():
    """
    刪除指定日期的歷史資料
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

    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        
        # 檢查資料是否存在
        cursor.execute("SELECT COUNT(*) FROM daily_history WHERE date = ?", (date_str,))
        count = cursor.fetchone()[0]
        
        if count == 0:
            conn.close()
            return jsonify({"status": "error", "message": f"No data found for date {date_str}"}), 404
            
        # 刪除指定日期的資料
        cursor.execute("DELETE FROM daily_history WHERE date = ?", (date_str,))
        conn.commit()
        conn.close()
        
        print(f"[Delete History] Data for {date_str} deleted successfully.")
        return jsonify({"status": "success", "message": f"Data for {date_str} deleted successfully."})
        
    except Exception as e:
        print(f"Error deleting history data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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

@app.route('/api/debug_messages', methods=['GET'])
def get_debug_messages():
    """
    獲取最新的除錯訊息
    """
    # Convert deque to list for JSON serialization
    messages = list(DEBUG_MESSAGES)
    return jsonify({
        "status": "success",
        "messages": messages
    })

if __name__ == '__main__':
    print("Starting Flask app...")
    app.run(debug=True, host='0.0.0.0', port=5000)
