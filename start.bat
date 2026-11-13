@echo off
rem 本文件为 GBK(ANSI) 编码，适配中文版 Windows 命令行默认代码页 936
setlocal
cd /d "%~dp0"
title OntoRegGov 数据安全管理平台

echo ============================================
echo   OntoRegGov 数据安全管理平台 · 一键启动
echo ============================================

rem ---- 1. 虚拟环境：首次双击自动创建并安装依赖 ----
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] 首次运行：创建虚拟环境并安装依赖（需联网，请稍候）...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo [错误] 虚拟环境创建失败：请确认已安装 Python 3.11+ 并加入 PATH。
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
) else (
  echo [1/4] 虚拟环境已就绪
)

rem ---- 2. 端口占用检查 ----
echo [2/4] 检查 8420 端口...
netstat -ano | findstr ":8420 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo [提示] 服务已在运行，直接打开业务台。
  start "" http://127.0.0.1:8420/
  pause
  exit /b 0
)

rem ---- 3. 种子数据：仅首次（无 app\data\app.db）时初始化 ----
if not exist "app\data\app.db" (
  echo [3/4] 初始化种子数据...
  ".venv\Scripts\python.exe" -m app.cli seed
  if errorlevel 1 (
    echo [错误] 种子初始化失败。
    pause
    exit /b 1
  )
) else (
  echo [3/4] 数据已存在，跳过初始化
)

rem ---- 4. 启动服务并自动开浏览器 ----
echo [4/4] 启动服务: http://127.0.0.1:8420/  （关闭本窗口即停止服务）
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul & start http://127.0.0.1:8420/"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8420

pause
