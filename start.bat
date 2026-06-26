@echo off
title Lote Pro — Servidor Local

echo.
echo  =========================================
echo   Lote Pro ^| Prospeccao Inteligente de Areas
echo  =========================================
echo.

:: Verificar se o uv esta disponivel
uv --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] uv nao encontrado.
    echo        Instale em: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

cd /d "%~dp0"

:: Sincronizar dependencias (uv baixa/usa Python 3.12 via requires-python e o uv.lock)
echo  Sincronizando dependencias (uv sync)...
uv sync
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias.
    pause
    exit /b 1
)

:: Verificar se a porta 8000 ja esta ocupada
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [AVISO] Porta 8000 ja em uso. Encerrando processo anterior...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    timeout /t 1 /nobreak >nul
)

echo  Iniciando servidor em http://127.0.0.1:8000
echo  Login padrao: admin / lotepro
echo  Pressione Ctrl+C para encerrar.
echo.

start "" "http://127.0.0.1:8000"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
