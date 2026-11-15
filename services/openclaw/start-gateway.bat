@echo off
rem OpenClaw agent gateway for OntoRegGov self-check service (port 18789).
rem Auto-started by the platform; can also be launched directly.
setlocal
set "OC_HOME=%~dp0"
set "OPENCLAW_STATE_DIR=%OC_HOME%state"
set "OPENCLAW_CONFIG_PATH=%OC_HOME%openclaw.json"

rem 配置就绪：openclaw.json 缺失时由模板 + 环境变量渲染（密钥不入库）
if not exist "%OC_HOME%openclaw.json" (
  where python >nul 2>&1 && python "%~dp0..\..\scripts\ops\render_openclaw_config.py"
)

rem Node 运行时：环境变量 OPENCLAW_NODE_BIN 优先，其次 PATH 中的 node，最后兜底 node
set "NODE_EXE=%OPENCLAW_NODE_BIN%"
if not defined NODE_EXE set "NODE_EXE=node"

"%NODE_EXE%" "%OC_HOME%openclaw.mjs" gateway run --bind loopback --port 18789 --allow-unconfigured
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo [OpenClaw] Gateway exited with code %RC%.
  echo   If it says "another gateway owns this state directory" or "port in use",
  echo   a gateway is already running - that is fine, the platform will use it.
  echo   Otherwise check the lines above, or run: openclaw doctor
  pause
)
