# ============================================================
#  AI Trading Bot v2 - Launcher
#  Usage:  .\trading_bot.ps1            (dry run, no orders sent)
#          .\trading_bot.ps1 --live     (live order execution!)
#          .\trading_bot.ps1 --once     (single cycle, then exit)
# ============================================================

$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BotDir

Write-Host "Starting AI Trading Bot v2 from $BotDir ..." -ForegroundColor Cyan
python main_v2.py @args

if ($LASTEXITCODE -ne 0) {
    Write-Host "Bot exited with code $LASTEXITCODE" -ForegroundColor Red
}
