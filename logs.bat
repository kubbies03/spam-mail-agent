@echo off
setlocal

cd /d "%~dp0"

if not exist "logs\system.stdout.log" (
    echo [ERROR] Missing logs\system.stdout.log
    exit /b 1
)

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Get-Content 'logs\system.stdout.log' -Tail 0 -Wait"
