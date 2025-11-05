import sqlite3

conn = sqlite3.connect('history.db')
cursor = conn.cursor()

# 查詢2025-11-02的資料
cursor.execute('SELECT * FROM daily_history WHERE date = "2025-11-02"')
rows = cursor.fetchall()
print('Data for 2025-11-02:', rows)

# 查詢所有資料
cursor.execute('SELECT * FROM daily_history ORDER BY date DESC LIMIT 10')
rows = cursor.fetchall()
print('\nRecent data:')
for row in rows:
    print(row)

conn.close()