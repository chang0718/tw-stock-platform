@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ====================================
echo   台股分析平台啟動中...
echo ====================================

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo [錯誤] 找不到虛擬環境 .venv
    echo 請先依照 SETUP_SOP.md 的步驟建立虛擬環境
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
streamlit run app.py

pause
