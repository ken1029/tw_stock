import pytest
import tempfile
import os
import json
import sqlite3
from app import app

# 建立測試用的臨時資料庫和portfolio文件
@pytest.fixture
def client():
    # 建立臨時目錄
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    portfolio_fd, portfolio_path = tempfile.mkstemp(suffix='.json')
    
    # 設定應用配置
    app.config['TESTING'] = True
    app.config['HISTORY_DB'] = db_path
    app.config['PORTFOLIO_FILE'] = portfolio_path
    
    # 設置應用上下文
    with app.app_context():
        pass
    
    with app.test_client() as client:
        with app.app_context():
            # 初始化測試資料庫
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
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
            
            # 建立空的測試portfolio文件
            with open(portfolio_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
        
        yield client
        
    # 測試結束後清理臨時文件
    os.close(db_fd)
    os.unlink(db_path)
    os.close(portfolio_fd)
    os.unlink(portfolio_path)