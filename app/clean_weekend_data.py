import sqlite3
from datetime import datetime

conn = sqlite3.connect('history.db')
cursor = conn.cursor()

# 刪除週末的資料
cursor.execute("SELECT date FROM daily_history ORDER BY date ASC")
all_dates = cursor.fetchall()

deleted_count = 0
for date_row in all_dates:
    date_str = date_row[0]
    # 將字串轉換為日期物件
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    # 獲取星期幾 (0=星期一, 6=星期日)
    weekday = date_obj.weekday()
    
    # 如果是週六(5)或週日(6)，則刪除該筆資料
    if weekday >= 5:
        cursor.execute("DELETE FROM daily_history WHERE date = ?", (date_str,))
        print(f"Deleted weekend data for {date_str}")
        deleted_count += 1

conn.commit()
print(f"\nTotal {deleted_count} weekend records deleted.")

# 顯示前10筆最新的資料
cursor.execute('SELECT * FROM daily_history ORDER BY date DESC LIMIT 10')
rows = cursor.fetchall()
print('\nRecent data after cleaning:')
for row in rows:
    print(row)

conn.close()