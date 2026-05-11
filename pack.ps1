# pack.ps1 — 台股分析平台打包腳本
# 執行方式: cd "d:\投資"; .\pack.ps1
# 輸出: 桌面的 tw-stock-platform_YYYYMMDD.zip

$date     = Get-Date -Format "yyyyMMdd"
$zipName  = "tw-stock-platform_$date.zip"
$desktop  = [Environment]::GetFolderPath("Desktop")
$zipPath  = Join-Path $desktop $zipName
$srcRoot  = $PSScriptRoot   # 腳本所在目錄（d:\投資）

# 要打包的檔案清單（相對路徑）
$include = @(
    # ── 核心 Python 模組 ──
    "app.py",
    "quant_model.py",
    "finmind_loader.py",
    "twse_institutional.py",
    "news_analyzer.py",
    "signal_engine.py",
    "portfolio.py",
    "config.py",
    "utils.py",
    "tech_analyzer.py",
    "us_market.py",
    "backtest.py",
    "data_loader.py",
    "financials.py",
    "news.py",
    # ── scripts ──
    "scripts\daily_report.py",
    # ── GitHub Actions ──
    ".github\workflows\daily_report.yml",
    # ── Streamlit 設定 ──
    ".streamlit\config.toml",
    ".streamlit\secrets.toml.example",
    # ── 專案設定 ──
    "requirements.txt",
    "CLAUDE.md",
    "DEPLOY.md",
    "SETUP_SOP.md",
    ".gitignore",
    # ── 個人資料（持倉/自選股/權重）──
    "tw_quant_data\portfolio.json",
    "tw_quant_data\watchlist.json",
    "tw_quant_data\weights.json"
)

# 清理舊 zip
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')

$copied = 0
$missing = @()

foreach ($rel in $include) {
    $full = Join-Path $srcRoot $rel
    if (Test-Path $full) {
        # 壓縮時保留子目錄結構
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $full, $rel, [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
        $copied++
        Write-Host "  + $rel"
    } else {
        $missing += $rel
        Write-Host "  - MISSING: $rel" -ForegroundColor Yellow
    }
}

$zip.Dispose()

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "打包完成: $zipPath" -ForegroundColor Green
Write-Host "已包含 $copied 個檔案" -ForegroundColor Green
if ($missing.Count -gt 0) {
    Write-Host "以下 $($missing.Count) 個檔案不存在（可忽略）:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "接下來：將 $zipName 複製到新電腦，解壓後依 SETUP_SOP.md 操作" -ForegroundColor White
