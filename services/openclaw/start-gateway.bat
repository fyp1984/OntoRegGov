@echo off
rem OpenClaw agent gateway for OntoRegGov self-check service (port 18789).
rem Auto-started by the platform; can also be launched directly.
setlocal
set "OC_HOME=%~dp0"
set "OPENCLAW_STATE_DIR=%OC_HOME%state"
set "OPENCLAW_CONFIG_PATH=%OC_HOME%openclaw.json"

set "NODE_EXE=C:\Users\fpcug\.openclaw\tools\cli-node\tools\node\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=D:\program\nodejs\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

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
