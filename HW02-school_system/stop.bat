@echo off
REM 停止 5000 port 上的 Flask server
setlocal
echo [INFO] 正在停止 5000 port 上的伺服器 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    echo   kill PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo [DONE] 完成
timeout /t 2 >nul
