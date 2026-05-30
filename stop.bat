@echo off
chcp 65001 >nul 2>&1
title FANZA Ultimate Manager - 停止

echo ============================================
echo   FANZA Ultimate Manager - 停止中...
echo ============================================
echo.

REM Pythonバックエンドプロセスの停止
echo [1/2] バックエンドサーバーを停止中...
for /f "tokens=2" %%i in ('tasklist /fi "WINDOWTITLE eq FANZA Backend*" /fo list ^| findstr "PID"') do (
    taskkill /PID %%i /T /F >nul 2>&1
)
taskkill /f /im python.exe /fi "WINDOWTITLE eq FANZA Backend" >nul 2>&1

REM Nodeフロントエンドプロセスの停止
echo [2/2] フロントエンドサーバーを停止中...
for /f "tokens=2" %%i in ('tasklist /fi "WINDOWTITLE eq FANZA Frontend*" /fo list ^| findstr "PID"') do (
    taskkill /PID %%i /T /F >nul 2>&1
)

echo.
echo ============================================
echo   停止完了！
echo ============================================
pause
