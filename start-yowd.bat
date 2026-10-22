@echo off
setlocal
pushd "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python run.py %*
) else (
    py -3 run.py %*
)
set "YOWD_EXIT=%ERRORLEVEL%"
if not "%YOWD_EXIT%"=="0" pause
popd
exit /b %YOWD_EXIT%
