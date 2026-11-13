@echo off
rem 本文件为 GBK(ANSI) 编码，适配中文版 Windows 命令行默认代码页 936
setlocal
cd /d "%~dp0"
title OntoRegGov 数据安全管理平台 · 一键启动

echo ============================================
echo   OntoRegGov 数据安全管理平台 · 一键启动
echo   （平台服务 8420 + OpenClaw 智能体服务 18789）
echo ============================================

rem ---- 1. Python 虚拟环境：首次自动创建并安装依赖 ----
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
  echo [1/4] Python 环境已就绪
)

rem ---- 2. OpenClaw 智能体服务（独立服务，端口 18789）----
echo [2/4] 检查 OpenClaw 智能体服务（127.0.0.1:18789）...
netstat -ano | findstr ":18789 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo       智能体服务已在运行，跳过启动
) else (
  echo       正在启动 OpenClaw 智能体服务（最小化窗口，关闭该窗口即停止）...
  start "OpenClaw 智能体服务" /min cmd /c ""%~dp0services\openclaw\start-gateway.bat""
)

rem ---- 3. 平台服务端口检查 + 种子数据 ----
echo [3/4] 检查平台服务端口 8420...
netstat -ano | findstr ":8420 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo [提示] 平台服务已在运行，直接打开业务台。
  start "" http://127.0.0.1:8420/
  pause
  exit /b 0
)
if not exist "app\data\app.db" (
  echo       初始化种子数据...
  ".venv\Scripts\python.exe" -m app.cli seed
  if errorlevel 1 (
    echo [错误] 种子初始化失败。
    pause
    exit /b 1
  )
)

rem ---- 4. 启动平台服务并自动开浏览器 ----
rem 平台启动钩子也会自动探测并拉起智能体网关（双保险），合规自查依赖该服务。
echo [4/4] 启动平台服务: http://127.0.0.1:8420/  （关闭本窗口即停止平台）
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul & start http://127.0.0.1:8420/"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8420

pause
