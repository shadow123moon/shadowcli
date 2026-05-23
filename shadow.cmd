@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
conda run --no-capture-output -n lc python cli.py %*
endlocal
