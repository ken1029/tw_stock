#!/usr/bin/env python3
"""
獨立的排程器腳本，用於定期執行 save_daily_snapshot。
"""

import os
import sys
import requests
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# 將 app.py 所在目錄加入 Python 路徑，以便 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 從 app.py import 必要的函式
from app import save_daily_snapshot

def trigger_snapshot():
    """
    觸發快照任務。
    這個函式會向 Flask API 發送請求，而不是直接呼叫 save_daily_snapshot。
    """
    try:
        response = requests.post('http://localhost:5000/api/trigger_snapshot', timeout=30)
        if response.status_code == 200:
            print(f"[Scheduler] Snapshot triggered successfully at {datetime.now()}")
        else:
            print(f"[Scheduler] Failed to trigger snapshot. Status code: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[Scheduler] Error triggering snapshot: {e}")

def main():
    """
    主函式，用於啟動排程器。
    """
    scheduler = BlockingScheduler()
    
    # 設定每天下午 3:30 執行，僅限週一至週五
    scheduler.add_job(
        trigger_snapshot,
        trigger=CronTrigger(
            hour=15,
            minute=30,
            day_of_week='mon-fri'
        ),
        id='daily_snapshot_job'
    )
    
    print("Starting scheduler...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Scheduler stopped.")
        scheduler.shutdown()

if __name__ == '__main__':
    main()