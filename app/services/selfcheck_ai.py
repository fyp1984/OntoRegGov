"""合规自查 AI 流水线（v1.19.0 · 智能体自主取证版）。

架构（对齐"用智能体就让它干智能体的活"原则）：
- 平台只做 **I/O 与编排**：枚举证据目录文件清单（不读取内容）、逐检查项向
  OpenClaw 智能体下发"取证+判定"任务、解析回传 JSON、落库与进度、生成 PDF 报告。
- **语义工作 100% 由智能体完成**：自己判断哪些文件相关、用 read 工具读文本/图片
  （视觉直接识别架构图等图片内容）、用 exec 调用 evidence-kit 取证工具做 office
  解析与音频逐字转写（本地 faster-whisper，零加工）、依检索口径判定、写整改建议。
- 平台代码不含关键词匹配挑文件、内容抽取或规则判定逻辑（v1.18.0 的预处理层已移除）。
- 运行态实体写通用 entities 表：type='SelfCheckRun'（含进度与逐检查项结果）。
- 红线：智能体不可达时任务标记 error 并给出降级提示，接口永不 5xx。
"""
from __future__ import annotations

import json
import re
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..db import db
from . import openclaw_svc
from . import kb_source

# ---------------- 证据目录枚举（只列清单，不读内容） ----------------
SKIP_DIR = re.compile(r"(^|[\\/])(node_modules|\.git|__pycache__|\.venv)([\\/]|$)")
MAX_LISTING_FILES = 2000


def list_files(root: str) -> dict:
    """枚举本地或 UNC 目录文件清单（相对路径/大小/时间/扩展名），不做任何内容解析。"""
    root = (root or "").strip().strip('"')
    if not root:
        return {"ok": False, "error": "目录不能为空", "files": []}
    rp = Path(root)
    try:
        if not rp.exists():
            return {"ok": False, "error": f"目录不存在或不可访问：{root}", "files": []}
        if not rp.is_dir():
            return {"ok": False, "error": f"不是目录：{root}", "files": []}
        files = []
        for p in rp.rglob("*"):
            try:
                if not p.is_file() or SKIP_DIR.search(str(p)):
                    continue
                st = p.stat()
                if st.st_size > 100 * 1024 * 1024:
                    continue
                files.append({
                    "abs": str(p.resolve()).replace("\\", "/"),
                    "rel": str(p.relative_to(rp)),
                    "ext": p.suffix.lower(),
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                })
                if len(files) >= MAX_LISTING_FILES:
                    break
            except Exception:  # noqa: BLE001
                continue
        files.sort(key=lambda f: f["rel"])
        return {"ok": True, "files": files, "root": root}
    except OSError as e:
        return {"ok": False, "error": f"目录访问失败：{str(e)[:150]}", "files": []}


# ---------------- 检查项取数 ----------------
def list_doc_checks(doc: str, priority: str = "") -> list[dict]:
    env = kb_source.fetch_checks(doc=doc, priority=priority)
    return (env or {}).get("content", {}).get("checks", []) or []


def fetch_check_full(code: str) -> dict:
    env = kb_source.fetch_check(code)
    return (env or {}).get("content") or {}


# ---------------- 任务组织（智能体自主取证提示词） ----------------
def _kit_paths() -> tuple[str, str]:
    """evidence-kit 取证工具路径（venv python, read_evidence.py）。"""
    kit = Path(__file__).resolve().parent.parent.parent / "services" / "openclaw" / "evidence-kit"
    return (str(kit / ".venv" / "Scripts" / "python.exe").replace("\\", "/"),
            str(kit / "read_evidence.py").replace("\\", "/"))


PROMPT_TMPL = """你是数据安全合规检查智能体，现在执行一项"实地取证 + 合规研判"任务。检查依据与取证条件如下。**证据文件的内容获取与相关性判断由你自主完成**（这是你的核心职责，不是别人替你挑好的）。

# 检查依据（{doc_no}）
检查项编号：{code}　标题：{title}（优先级 {priority}，领域 {domain_label}）

## 条文原文
{article_text}

## 检查清单（要素 · 口径 · 关注层级）
{elements_md}

## 检查方法（查制度 · 查证据 · 杀手锏提示）
{method_md}

## 三档判定要点
通过：{v_pass}
部分符合：{v_partial}
不符合：{v_fail}

# 证据库（待你取证）
目录：{dir}（共 {total_files} 个文件）

{files_md}

# 你的取证手段（自主选择使用）
1. **read 工具**：直接读取 txt/md/csv/json/xml/html/log 等文本文件，以及 **png/jpg 等图片**（你具备视觉能力，组织架构示意图等图片证据直接读图识别其内容）。
2. **exec 调用取证工具**（office/音频等二进制格式，逐字抽取、零加工）：
   `{kit_py} {kit_script} "<文件绝对路径>" [--max-chars N]`
   支持 docx/xlsx/pptx/pdf/rtf/eml/zip/odt/ods/vsdx 文本抽取，以及 mp3/wav/m4a/flac 等音频**本地语音转写**（逐字原文+时间戳）。结果走 stdout；失败返回 ERROR: 原因。
3. 可用 exec 配合 grep 等按关键词在目录内快速定位候选文件。

# 任务步骤
1. 通读文件清单，依据本检查项各要素口径**自主判断哪些文件可能相关**并逐一取证阅读（宁多勿漏；文件名可疑就读它，读后发现无关再放弃）。
2. 对每个要素判定：pass / partial / fail / missing（找不到应提供的文件）/ manual（有文件但穷尽手段仍无法读取内容）。
3. 每个要素的 reason 必须引用具体文件名并摘关键原文；fail/missing 要说明缺什么、差在哪。
4. 整体 result 取各要素最差（任一 fail→fail；否则任一 missing→missing；否则任一 partial/manual→partial；否则全 pass→pass），summary ≤60字。
5. gaps（差距，≤40字/条）与 remediation（整改建议，可执行，≤60字/条）。
6. 严格性：要素口径硬性要求某表述/文件而全部证据中均无，判 fail，不得降为 partial；partial 仅用于"实质具备、形式或覆盖不完整"。
7. 诚实性：判定只依据你实际读到的内容，不得臆造、不得凭文件名猜内容；转写/识别有明显错误（同音字等）时按原文引用，不得替证据"改写润色"。

只输出一个 JSON 对象（不要任何解释文字）。字符串值内**禁止英文双引号 "**，引用原文一律用中文引号「」：
{{"checkCode":"{code}","result":"pass|partial|fail|missing","confidence":0.0-1.0,"readFiles":["实际取证读过的文件名"],"elements":[{{"code":"1.1.1","verdict":"pass|partial|fail|missing|manual","evidenceFiles":["文件名"],"reason":"…"}}],"missingEvidence":["…"],"gaps":["…"],"remediation":["…"],"summary":"…"}}"""


def build_prompt(check: dict, root: str, doc_no: str, files: list[dict]) -> str:
    els = "\n".join(
        f"- {e.get('code')} {e.get('text')}｜口径：{e.get('criteria') or '—'}｜层级：{e.get('focusLevels') or '—'}"
        for e in check.get("elements") or []) or "（无要素）"
    steps = "\n".join(
        f"- [{s.get('stepKind') or '查制度'}{s.get('stepNo') or ''}] {s.get('action') or ''} {s.get('focus') or ''}"
        for s in check.get("methodSteps") or []) or "（无）"
    v = check.get("verdict") or {}

    def _j(x):
        if isinstance(x, str):
            try:
                x = json.loads(x)
            except Exception:  # noqa: BLE001
                x = [x]
        return "；".join(x or []) or "—"
    tip = check.get("tip") or ""
    files_md = "\n".join(
        f"- {f['rel']}（{f['ext'] or '无扩展名'}，{f['size']} 字节，{f['mtime']}）→ {f['abs']}"
        for f in files) or "（空目录）"
    kit_py, kit_script = _kit_paths()
    return PROMPT_TMPL.format(
        doc_no=doc_no, code=check.get("checkCode", ""), title=check.get("title", ""),
        priority=check.get("priority", ""), domain_label=check.get("domainLabel") or check.get("domain") or "",
        article_text=check.get("articleText") or "（见条文编号 " + str(check.get("regulation")) + "）",
        elements_md=els, method_md=steps + (f"\n- 杀手锏：{tip}" if tip else ""),
        v_pass=_j(v.get("verdictPass") or v.get("pass")),
        v_partial=_j(v.get("verdictPartial") or v.get("partial")),
        v_fail=_j(v.get("verdictFail") or v.get("fail")),
        dir=str(root).replace("\\", "/"), total_files=len(files), files_md=files_md,
        kit_py=kit_py, kit_script=kit_script)


# ---------------- 运行编排 ----------------
RUNS_LOCK = threading.Lock()


def recover_stale_runs() -> int:
    """平台启动时调用：把上个进程遗留的 running 运行标记为中断（执行线程已随旧进程消亡）。"""
    fixed = 0
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT id,dataJSON FROM entities WHERE type='SelfCheckRun'").fetchall()
        for r in rows:
            try:
                d = json.loads(r["dataJSON"])
            except Exception:  # noqa: BLE001
                continue
            if d.get("status") != "running":
                continue
            d["status"] = "error"
            d["error"] = "服务重启导致运行中断（自查执行线程随原平台进程退出），请重新发起自查"
            d["finishedAt"] = d.get("finishedAt") or _now()
            with db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (d["runId"], "SelfCheckRun", "published", d.get("_v", 0),
                     json.dumps(d, ensure_ascii=False), "[]", _now(), "system"))
            fixed += 1
    except Exception:  # noqa: BLE001
        return fixed
    return fixed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _save_run(run: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO entities(id,type,status,currentVersion,dataJSON,relationsJSON,updatedAt,updatedBy)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (run["runId"], "SelfCheckRun", "published", run.get("_v", 0),
             json.dumps(run, ensure_ascii=False), "[]", _now(), run.get("userKey", "ui-user")))
        run["_v"] = run.get("_v", 0) + 1


def get_run(run_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT dataJSON FROM entities WHERE id=? AND type='SelfCheckRun'",
                           (run_id,)).fetchone()
    return json.loads(row["dataJSON"]) if row else None


DOC_LABELS = {"jg24": "金规〔2024〕24号", "jg93": "金办发〔2025〕93号",
              "pboc3": "人行令〔2025〕第3号", "jf8": "金发〔2026〕8号"}


def start_run(doc: str, directory: str, priority: str = "", limit: int = 0,
              user_key: str = "") -> dict:
    """创建运行并后台执行。立即返回 runId；进度经 get_run 轮询。"""
    run_id = "scr-" + uuid.uuid4().hex[:8]
    agent = openclaw_svc.agent_id_for(user_key)
    run = {
        "runId": run_id, "doc": doc, "docNo": DOC_LABELS.get(doc, doc), "dir": directory,
        "priority": priority, "limit": int(limit or 0), "userKey": user_key or "default",
        "agentId": agent,
        "status": "running", "startedAt": _now(), "finishedAt": None,
        "total": 0, "done": 0, "items": [], "error": None, "fileCount": 0,
    }
    _save_run(run)
    t = threading.Thread(target=_execute, args=(run_id,), daemon=True, name=f"selfcheck-{run_id}")
    t.start()
    return run


def _execute(run_id: str) -> None:
    run = get_run(run_id) or {}
    try:
        agent = run.get("agentId") or openclaw_svc.GUEST_AGENT
        openclaw_svc.ensure_agent(run.get("userKey", "default"))
        h = openclaw_svc.ensure_running()
        if not h.get("ok"):
            run.update(status="error", error=f"智能体服务不可达：{h.get('error','')}",
                       finishedAt=_now())
            _save_run(run)
            return

        listing = list_files(run.get("dir", ""))
        if not listing["ok"]:
            run.update(status="error", error=listing["error"], finishedAt=_now())
            _save_run(run)
            return
        files = listing["files"]
        if not files:
            run.update(status="error", error="目录中没有可检查的文件", finishedAt=_now())
            _save_run(run)
            return

        checks = list_doc_checks(run["doc"], run.get("priority", ""))
        limit = int(run.get("limit") or 0)
        if limit > 0:
            checks = checks[:limit]
        run.update(total=len(checks), fileCount=len(files), status="running")
        _save_run(run)

        doc_no = run.get("docNo") or run["doc"]
        for c0 in checks:
            code = c0.get("checkCode", "")
            full = fetch_check_full(code)
            full.setdefault("checkCode", code)
            prompt = build_prompt(full, run["dir"], doc_no, files)
            reply = openclaw_svc.chat(agent, prompt,
                                      session_user=f"selfcheck:{run_id}",
                                      timeout=900.0, temperature=0.0, max_retries=1)
            item = {"checkCode": code, "title": full.get("title", ""),
                    "priority": full.get("priority", ""), "domainLabel": full.get("domainLabel", "")}
            if not reply.get("ok"):
                item.update(result="manual", summary="智能体调用失败，需人工检查",
                            error=reply.get("error", ""), elements=[], gaps=[], remediation=[])
            else:
                parsed = openclaw_svc.parse_json_reply(reply["content"])
                if isinstance(parsed, dict):
                    item.update(
                        result=parsed.get("result", "manual"),
                        confidence=parsed.get("confidence"),
                        summary=parsed.get("summary", ""),
                        elements=parsed.get("elements", []),
                        missingEvidence=parsed.get("missingEvidence", []),
                        gaps=parsed.get("gaps", []),
                        remediation=parsed.get("remediation", []),
                        readFiles=parsed.get("readFiles", []),
                        evidenceFiles=sorted({ef for e in parsed.get("elements", [])
                                              for ef in (e.get("evidenceFiles") or [])}))
                else:
                    item.update(result="manual", summary="智能体回复无法解析，需人工复核",
                                raw=(reply.get("content") or "")[:800], elements=[])
            run["items"].append(item)
            run["done"] += 1
            _save_run(run)

        run.update(status="done", finishedAt=_now())
        _save_run(run)
    except Exception as e:  # noqa: BLE001
        run.update(status="error", error=str(e)[:300], finishedAt=_now())
        try:
            _save_run(run)
        except Exception:  # noqa: BLE001
            pass


def summarize(run: dict) -> dict:
    items = run.get("items") or []
    n = {"pass": 0, "partial": 0, "fail": 0, "missing": 0, "manual": 0}
    for it in items:
        n[it.get("result", "manual")] = n.get(it.get("result", "manual"), 0) + 1
    total = len(items) or 1
    return {**n, "total": len(items),
            "complianceRate": round(100 * n["pass"] / total),
            "overall": ("fail" if n["fail"] else "missing" if n["missing"]
                        else "partial" if (n["partial"] or n["manual"]) else "pass")}
