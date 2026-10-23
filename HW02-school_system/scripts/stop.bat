@echo off
REM 停止 NKU portal
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq *app.py*" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *app.py*" 2>nul
REM 也用 WMI 找 command line 含 app.py 的
for /f "tokens=*" %%P in ('wmic process where "name='python.exe' or name='pythonw.exe'" get processid^,commandline /format:list 2^>nul ^| findstr /C:"app.py"') do (
    echo %%P
)
REM 簡化：直接殺掉所有 pythonw
taskkill /F /IM pythonw.exe 2>nul
echo Done.