@echo off
:: 強制在新 CMD 視窗中執行，避免雙擊後沒反應
if not "%LAUNCHED%"=="1" (
    set LAUNCHED=1
    start "台股分析平台" cmd /k ""%~f0""
    exit /b
)

chcp 65001 > nul
cd /d "%~dp0"

echo ====================================
echo   台股分析平台啟動中...
echo ====================================
echo.

if not exist ".venv\Scripts\activate.bat" (
    echo [錯誤] 找不到虛擬環境 .venv
    echo 請先依照 SETUP_SOP.md 的步驟建立虛擬環境
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
streamlit run app.py

echo.
echo 平台已關閉
pause
