@echo off
title Lote Pro — Servidor Local

echo.
echo  =========================================
echo   Lote Pro ^| Prospeccao Inteligente de Areas
echo  =========================================
echo.

:: Verificar se Python 3.14 esta disponivel
py -3.14 --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python 3.14 nao encontrado.
    echo        Instale em: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verificar dependencias criticas
py -3.14 -c "import fastapi, geopandas, osmnx" >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Dependencias ausentes. Instalando...
    py -3.14 -m pip install -r requirements.txt
    echo.
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

cd /d "%~dp0"
start "" "http://127.0.0.1:8000"
py -3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
