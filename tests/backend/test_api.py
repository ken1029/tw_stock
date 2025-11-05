import pytest
import json
import sqlite3
from app import app

class TestAPIEndpoints:
    """測試Flask API端點"""
    
    def test_get_portfolio_empty(self, client):
        """測試當portfolio.json為空時，API回傳正確格式"""
        # Arrange: 清空portfolio文件
        portfolio_path = app.config['PORTFOLIO_FILE']
        with open(portfolio_path, 'w', encoding='utf-8') as f:
            json.dump([], f)
        
        # Act: 調用/portfolio端點
        response = client.get('/api/portfolio')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳格式
        assert response.status_code == 200
        assert data['stocks'] == []
        assert data['totals'] == {}
    
    def test_get_portfolio_with_data(self, client):
        """測試當portfolio有數據時，API正確計算市值和損益"""
        # Arrange: 準備測試用的portfolio數據
        portfolio_path = app.config['PORTFOLIO_FILE']
        test_portfolio = [
            {
                "ticker": "2330.TW",
                "shares": 1000,
                "avg_cost": 500.0,
                "currency": "TWD",
                "name": "台積電"
            },
            {
                "ticker": "0050.TW",
                "shares": 2000,
                "avg_cost": 100.0,
                "currency": "TWD",
                "name": "元大台灣50"
            }
        ]
        
        with open(portfolio_path, 'w', encoding='utf-8') as f:
            json.dump(test_portfolio, f, indent=2, ensure_ascii=False)
        
        # Act: 調用/portfolio端點
        response = client.get('/api/portfolio')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳數據結構
        assert response.status_code == 200
        assert 'stocks' in data
        assert 'totals' in data
        assert len(data['stocks']) > 0
        assert 'market_value' in data['totals']
        assert 'cost_basis' in data['totals']
        assert 'pl' in data['totals']
        assert 'pl_percent' in data['totals']
    
    def test_get_history_summary(self, client):
        """測試歷史數據API回傳正確格式"""
        # Arrange: 準備測試歷史數據
        db_path = app.config['HISTORY_DB']
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO daily_history 
                          (date, total, tw_value, cn_value) 
                          VALUES (?, ?, ?, ?)''', 
                       ('2025-10-01', 1000000, 600000, 400000))
        conn.commit()
        conn.close()
        
        # Act: 調用/history_summary端點
        response = client.get('/api/history_summary')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳格式
        assert response.status_code == 200
        assert 'daily' in data
        assert 'monthly' in data
        assert 'yearly' in data
    
    def test_add_stock(self, client):
        """測試新增股票功能"""
        # Arrange: 準備股票數據 (使用不重複的ticker)
        new_stock = {
            "ticker": "2412.TW",
            "shares": 1000,
            "avg_cost": 45.0,
            "currency": "TWD",
            "name": "中華電信"
        }
        
        # Act: 調用POST /api/stock
        response = client.post('/api/stock',
                               data=json.dumps(new_stock),
                               content_type='application/json')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳結果
        assert response.status_code == 201
        assert data['status'] == 'success'
        assert data['stock']['ticker'] == '2412.TW'
        
        # 驗證股票確實加入portfolio
        portfolio_response = client.get('/api/portfolio')
        portfolio_data = json.loads(portfolio_response.data)
        tickers = [stock['ticker'] for stock in portfolio_data['stocks']]
        assert '2412.TW' in tickers
    
    def test_update_stock(self, client):
        """測試更新股票功能"""
        # Arrange: 準備測試用的portfolio數據
        portfolio_path = app.config['PORTFOLIO_FILE']
        test_portfolio = [
            {
                "ticker": "2330.TW",
                "shares": 1000,
                "avg_cost": 500.0,
                "currency": "TWD",
                "name": "台積電"
            }
        ]
        
        with open(portfolio_path, 'w', encoding='utf-8') as f:
            json.dump(test_portfolio, f, indent=2, ensure_ascii=False)
        
        # Arrange: 準備更新數據
        update_data = {
            "shares": 2000,
            "avg_cost": 85.0,
            "currency": "TWD"
        }
        
        # Act: 調用PUT /api/stock/2330.TW (使用已存在的ticker)
        response = client.put('/api/stock/2330.TW',
                              data=json.dumps(update_data),
                              content_type='application/json')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳結果
        assert response.status_code == 200
        assert data['status'] == 'success'
        assert data['stock']['shares'] == 2000
        assert data['stock']['avg_cost'] == 85.0
    
    def test_delete_stock(self, client):
        """測試刪除股票功能"""
        # Arrange: 準備測試用的portfolio數據
        portfolio_path = app.config['PORTFOLIO_FILE']
        test_portfolio = [
            {
                "ticker": "2330.TW",
                "shares": 1000,
                "avg_cost": 500.0,
                "currency": "TWD",
                "name": "台積電"
            }
        ]
        
        with open(portfolio_path, 'w', encoding='utf-8') as f:
            json.dump(test_portfolio, f, indent=2, ensure_ascii=False)
        
        # Act: 調用DELETE /api/stock/2330.TW (使用已存在的ticker)
        response = client.delete('/api/stock/2330.TW')
        data = json.loads(response.data)
        
        # Assert: 驗證回傳結果
        assert response.status_code == 200
        assert data['status'] == 'success'
        
        # 驗證股票確實從portfolio移除
        portfolio_response = client.get('/api/portfolio')
        portfolio_data = json.loads(portfolio_response.data)
        tickers = [stock['ticker'] for stock in portfolio_data['stocks']]
        assert '2330.TW' not in tickers

if __name__ == '__main__':
    pytest.main(['-v'])