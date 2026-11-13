"""OpenClaw 智能体服务对接层（合规自查 AI 引擎）。

架构（v1.18.0）：
- openclaw 作为**独立智能体服务**随项目分发于 services/openclaw/（构建产物 dist +
  node_modules + 启动器 + 专属 openclaw.json 配置 + 专属 state/ 状态目录），
  与系统其它服务并列统一管理；默认监听 127.0.0.1:18789（loopback + Bearer token）。
- 系统用户 ↔ openclaw 智能体（agent）一一映射实现轻隔离：
  注册用户经 `openclaw agents add` 在**同一 gateway 进程内**创建专属 agent
  （独立 workspace / agentDir / 会话库，非新起服务）；未注册访客共用 default agent。
  映射持久化于 SQLite 表 oc_agents。
- 对话调用走 OpenAI 兼容面 POST /v1/chat/completions，
  model = "openclaw/<agentId>" 路由到指定 agent；user 字段派生稳定会话键。
- 纪律沿用全项目红线：外部服务不可达只降级、不 5xx；所有异常返回结构化 {ok:false}。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from ..config import DB_PATH

# ---------------- 服务定位 ----------------
APP_DIR = Path(__file__).resolve().parent.parent            # .../app
PROJECT_DIR = APP_DIR.parent                                # .../OntoRegGov
OC_HOME = PROJECT_DIR / "services" / "openclaw"             # openclaw 整合目录
OC_CONFIG = OC_HOME / "openclaw.json"
OC_STATE = OC_HOME / "state"
OC_ENTRY = OC_HOME / "openclaw.mjs"

# Node 运行时优先级：openclaw 缓存运行时(v26) > 项目内置 > PATH
_NODE_CANDIDATES = [
    Path.home() / ".openclaw" / "tools" / "cli-node" / "tools" / "node" / "node.exe",
    Path("D:/program/nodejs/node.exe"),
]


def _node_exe() -> str:
    for p in _NODE_CANDIDATES:
        if p.exists():
            return str(p)
    return shutil.which("node") or "node"


def _gateway_base() -> str:
    port = os.environ.get("OPENCLAW_GATEWAY_PORT", "18789")
    return f"http://127.0.0.1:{port}"


# 本机网关必须直连：系统代理（如 Clash 7897）会劫持 127.0.0.1 请求导致 502/超时
_direct_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))


def _open(req, timeout: float):
    return _direct_opener.open(req, timeout=timeout)


def _gateway_token() -> str:
    try:
        cfg = json.loads(OC_CONFIG.read_text(encoding="utf-8"))
        return ((cfg.get("gateway") or {}).get("auth") or {}).get("token", "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------- 映射表 ----------------
# 访客/未登录共用 agent 用具体 id "guest"，不用 "default"：
# openclaw 中 `model:"openclaw/default"` 是"取配置默认 agent"的哨兵值，
# 多 agent + agents.ownership=explicit 时无法隐式解析（400 no explicit owner）；
# 具体 agent id 则始终可显式路由。
GUEST_AGENT = "guest"


def _ensure_table() -> None:
    with sqlite3.connect(str(DB_PATH), timeout=10) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS oc_agents("
            " user_key TEXT PRIMARY KEY, agent_id TEXT NOT NULL,"
            " workspace TEXT, created_at TEXT, source TEXT)")


def agent_id_for(user_key: str) -> str:
    """用户键 → agent id。注册用户提供 'u:<name>'；访客/未登录固定共用 guest agent。"""
    key = (user_key or "").strip() or "default"
    if key in ("default", "guest"):
        return GUEST_AGENT
    _ensure_table()
    with sqlite3.connect(str(DB_PATH), timeout=10) as c:
        row = c.execute("SELECT agent_id FROM oc_agents WHERE user_key=?", (key,)).fetchone()
    return row[0] if row else _slug(key)


def _slug(key: str) -> str:
    """openclaw agent id 约束：小写字母数字下划线连字符。"""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (key or "").strip().lower()).strip("-")
    if not s:
        return "user"
    if s[0].isdigit():
        s = "u-" + s
    return ("u-" + s)[:40] if not s.startswith("u-") else s[:40]


# ---------------- 进程管理 ----------------
_spawn_lock = threading.Lock()
_last_spawn_ts = 0.0


def health(timeout: float = 2.0) -> dict:
    """gateway 健康检查：GET /v1/models（Bearer）。"""
    req = urllib.request.Request(_gateway_base() + "/v1/models",
                                 headers={"Authorization": f"Bearer {_gateway_token()}"})
    try:
        with _open(req, timeout=timeout) as r:
            body = r.read(400)
        return {"ok": True, "status": r.status, "base": _gateway_base()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200], "base": _gateway_base()}


def ensure_running(auto_start: bool = True) -> dict:
    """gateway 不可达时后台拉起独立进程（幂等、防抖 20s）。永不抛错。"""
    h = health()
    if h["ok"] or not auto_start or not OC_ENTRY.exists():
        return h
    global _last_spawn_ts
    with _spawn_lock:
        if time.time() - _last_spawn_ts < 20:
            return {"ok": False, "error": "spawn debounced", "base": _gateway_base()}
        _last_spawn_ts = time.time()
        env = dict(os.environ)
        env.update({
            "OPENCLAW_STATE_DIR": str(OC_STATE),
            "OPENCLAW_CONFIG_PATH": str(OC_CONFIG),
        })
        log = open(OC_STATE / "gateway.log", "ab")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        try:
            subprocess.Popen(
                [_node_exe(), str(OC_ENTRY), "gateway", "run",
                 "--bind", "loopback", "--port", "18789", "--allow-unconfigured"],
                cwd=str(OC_HOME), env=env, stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, **kwargs)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"spawn failed: {e}"[:200]}
    for _ in range(30):  # 最多等 15s 就绪
        time.sleep(0.5)
        h = health(timeout=1.5)
        if h["ok"]:
            return h
    return {"ok": False, "error": "spawned but not ready yet", "base": _gateway_base()}


# ---------------- agent 创建 ----------------
def roster() -> set[str]:
    """gateway 当前可路由的 agent id 集合（经 /v1/models 观察）。失败返回空集。"""
    req = urllib.request.Request(_gateway_base() + "/v1/models",
                                 headers={"Authorization": f"Bearer {_gateway_token()}"})
    try:
        with _open(req, timeout=5) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        return {m["id"].split("/", 1)[1] for m in body.get("data", [])
                if m.get("id", "").startswith("openclaw/") and "/" in m["id"]}
    except Exception:  # noqa: BLE001
        return set()


def ensure_agent(user_key: str) -> dict:
    """确保用户拥有专属 agent；不存在则经 openclaw CLI 在同一 gateway 内创建。

    查表命中仍会向 gateway 花名册核验（防脏映射/状态丢失），缺失自动补建。
    返回 {ok, agentId, created, degraded?}。CLI 失败时降级返回预期 id（调用方
    仍能以 guest 兜底），绝不抛错。
    """
    key = (user_key or "").strip() or "default"
    _ensure_table()
    if key in ("default", "guest"):
        # 访客共用 guest agent：不存在则补建（幂等）
        if GUEST_AGENT in roster() or not roster():
            return {"ok": True, "agentId": GUEST_AGENT, "created": False}
        return _create_agent(GUEST_AGENT, OC_HOME / f"workspace-{GUEST_AGENT}")
    with sqlite3.connect(str(DB_PATH), timeout=10) as c:
        row = c.execute("SELECT agent_id FROM oc_agents WHERE user_key=?", (key,)).fetchone()
    if row:
        aid = row[0]
        r = roster()
        if aid in r or not r:      # 花名册核验（不可达时信任表数据）
            return {"ok": True, "agentId": aid, "created": False}
        # 脏映射：表有记录但 gateway 无此 agent → 补建
        return _create_agent(aid, OC_HOME / f"workspace-{aid}", user_key=key)
    aid = _slug(key)
    return _create_agent(aid, OC_HOME / f"workspace-{aid}", user_key=key)


def _create_agent(aid: str, ws: Path, user_key: str = "") -> dict:
    """经 CLI 创建 agent（gateway 热加载即时生效）；已存在视为成功。"""
    ws.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"OPENCLAW_STATE_DIR": str(OC_STATE), "OPENCLAW_CONFIG_PATH": str(OC_CONFIG)})
    out = {"ok": False, "agentId": aid, "created": False}
    try:
        r = subprocess.run(
            [_node_exe(), str(OC_ENTRY), "agents", "add", aid,
             "--workspace", str(ws), "--non-interactive", "--json"],
            cwd=str(OC_HOME), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180)
        m = re.search(r"\{.*\}", r.stdout or "", re.S)
        if r.returncode == 0 and m:
            info = json.loads(m.group(0))
            aid = info.get("agentId") or aid
            out = {"ok": True, "agentId": aid, "created": True, "workspace": str(ws)}
        elif "already exists" in (r.stdout + r.stderr).lower():
            out = {"ok": True, "agentId": aid, "created": False, "note": "already exists"}
        else:
            out["error"] = (r.stderr or r.stdout or "")[:300]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    if out.get("ok") and user_key:
        with sqlite3.connect(str(DB_PATH), timeout=10) as c:
            c.execute("INSERT OR REPLACE INTO oc_agents(user_key,agent_id,workspace,created_at,source)"
                      " VALUES(?,?,?,?,?)",
                      (user_key, aid, str(ws), time.strftime("%Y-%m-%dT%H:%M:%S"), "system"))
    return out


def list_agents() -> dict:
    """gateway 花名册（调试/健康面板用）。"""
    try:
        env = dict(os.environ)
        env.update({"OPENCLAW_STATE_DIR": str(OC_STATE), "OPENCLAW_CONFIG_PATH": str(OC_CONFIG)})
        r = subprocess.run([_node_exe(), str(OC_ENTRY), "agents", "list", "--json"],
                           cwd=str(OC_HOME), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return {"ok": r.returncode == 0, "raw": (r.stdout or "")[:4000]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


# ---------------- 对话调用 ----------------
def chat(agent_id: str, prompt: str, *, session_user: str = "",
          timeout: float = 600.0, temperature: float | None = 0.0,
          max_retries: int = 2) -> dict:
    """向指定 agent 发消息取回复（OpenAI 兼容面，model=openclaw/<agentId>）。

    返回 {ok, content, degraded?}；失败自动重试并回落 default agent，
    仍失败返回 {ok:false,error}（调用方降级处理，绝不抛错）。
    """
    token = _gateway_token()
    targets = [agent_id] + ([GUEST_AGENT] if agent_id != GUEST_AGENT else [])
    last_err = ""
    for attempt in range(max_retries + 1):
        for tid in targets:
            payload = {
                "model": f"openclaw/{tid}",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            if temperature is not None:
                payload["temperature"] = temperature
            if session_user:
                payload["user"] = session_user
            req = urllib.request.Request(
                _gateway_base() + "/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST")
            try:
                with _open(req, timeout=timeout) as r:
                    body = json.loads(r.read().decode("utf-8", "replace"))
                content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
                if content.strip():
                    return {"ok": True, "content": content, "agentId": tid,
                            "usage": body.get("usage") or {}}
                last_err = "empty completion"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:200]
        if attempt < max_retries:
            time.sleep(3 * (attempt + 1))
    return {"ok": False, "error": last_err or "agent call failed"}


def parse_json_reply(text: str) -> dict | list | None:
    """从模型回复中稳健提取 JSON（围栏 / 前后缀说明 / 内嵌未转义引号修复）。"""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        pass
    for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pat, t)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                continue
    # 最终兜底：json_repair 修复 LLM 常见畸形（内嵌未转义引号 / 截断 / 尾逗号）
    try:
        from json_repair import repair_json
        fixed = repair_json(t, return_objects=True)
        if isinstance(fixed, (dict, list)) and fixed:
            return fixed
    except Exception:  # noqa: BLE001
        pass
    return None
