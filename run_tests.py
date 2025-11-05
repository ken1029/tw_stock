#!/usr/bin/env python3
"""
測試執行腳本
此腳本會執行所有測試並生成報告
"""

import subprocess
import sys
import os

def run_backend_tests():
    """執行後端測試"""
    print("執行後端測試...")
    result = subprocess.run([
        sys.executable, "-m", "pytest", "tests/backend", "-v"
    ], capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("錯誤訊息:", result.stderr)
    
    return result.returncode == 0

def run_integration_tests():
    """執行整合測試"""
    print("\n執行整合測試...")
    result = subprocess.run([
        sys.executable, "-m", "pytest", "tests/integration", "-v"
    ], capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("錯誤訊息:", result.stderr)
    
    return result.returncode == 0

def main():
    """主執行函式"""
    print("開始執行股票儀表板測試套件...")
    
    # 執行後端測試
    backend_success = run_backend_tests()
    
    # 執行整合測試
    integration_success = run_integration_tests()
    
    # 總結結果
    print("\n=== 測試結果總結 ===")
    if backend_success and integration_success:
        print("✅ 所有測試通過!")
        return 0
    else:
        print("❌ 部分測試失敗!")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)