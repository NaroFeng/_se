@echo off
REM 啟動 NKU portal，detach 完全脫離當前 console
set FLASK_DEBUG=0
start "" /B pythonw.exe "%~dp0..\app.py" > "%TEMP%\nku-flask.out.log" 2> "%TEMP%\nku-flask.err.log"
echo Started. Tail log: type "%TEMP%\nku-flask.out.log"