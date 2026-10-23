@echo off
REM ============================================================
REM  NKU 校務資訊系統 - 啟動器（Windows）
REM  雙擊即可啟動 Flask dev server
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "instance\" (
    echo [SETUP] 第一次啟動，安裝依賴中 ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] 依賴安裝失敗
        pause
        exit /b 1
    )
)

set FLASK_DEBUG=0
title NKU Portal - http://127.0.0.1:5000
echo.
echo ============================================================
echo   NKU 校務資訊系統
echo   URL : http://127.0.0.1:5000
echo   預設帳號: feng / pass1234  (student)
echo            admin / admin1234 (admin)
echo   按 Ctrl+C 停止伺服器
echo ============================================================
echo.

python app.py

echo.
echo [INFO] 伺服器已停止
pause
