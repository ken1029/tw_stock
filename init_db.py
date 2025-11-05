import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'history.db')

def create_database():
    """
    建立資料庫和資料表
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 建立 daily_history 資料表
        # date 是主鍵 (PRIMARY KEY)，確保不會有重複日期
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_history (
            date TEXT PRIMARY KEY,
            total REAL NOT NULL,
            tw_value REAL,
            cn_value REAL
        )
        ''')
        
        conn.commit()
        conn.close()
        print(f"資料庫 '{DB_FILE}' 已成功建立。")
        print("資料表 'daily_history' 已成功建立。")
        
    except Exception as e:
        print(f"建立資料庫時發生錯誤: {e}")

if __name__ == "__main__":
    create_database()
