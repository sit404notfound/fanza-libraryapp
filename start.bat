@echo off
chcp 65001 >nul 2>&1
title FANZA Ultimate Manager

echo ============================================
echo   FANZA Ultimate Manager - 起動中...
echo ============================================
echo.

REM プロジェクトルートディレクトリの取得
set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "VENV_PYTHON=%ROOT_DIR%.venv\Scripts\python.exe"

REM 仮想環境の存在確認
if not exist "%VENV_PYTHON%" (
    echo [エラー] 仮想環境が見つかりません: %VENV_PYTHON%
    echo .venv を作成してください: python -m venv .venv
    pause
    exit /b 1
)

REM node_modulesの存在確認
if not exist "%FRONTEND_DIR%\node_modules" (
    echo [情報] node_modules が未インストールです。npm install を実行します...
    cd /d "%FRONTEND_DIR%"
    call npm install
    if errorlevel 1 (
        echo [エラー] npm install に失敗しました。
        pause
        exit /b 1
    )
)

echo [1/2] バックエンドサーバーを起動中 (port 5000)...
start "FANZA Backend" cmd /c "cd /d "%BACKEND_DIR%" && "%VENV_PYTHON%" app.py"

REM バックエンドの起動待ち
timeout /t 2 /nobreak >nul

echo [2/2] フロントエンドサーバーを起動中 (port 5173)...
start "FANZA Frontend" cmd /c "cd /d "%FRONTEND_DIR%" && npm run dev"

REM フロントエンドの起動待ち
timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo   起動完了！
echo   フロントエンド: http://localhost:5173/
echo   バックエンド:   http://localhost:5000/
echo ============================================
echo.
echo このウィンドウを閉じてもサーバーは動作し続けます。
echo サーバーを停止するには各ウィンドウを閉じてください。
echo.

REM ブラウザで自動的にフロントエンドを開く
start "" "http://localhost:5173/"

pause
