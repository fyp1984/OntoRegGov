#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_publish.py — kb-publish 统一发布流水线（任务线2·工作包B）。

大白话：一次"改一条知识"触发：影子同步 → 双端 strict 校验 → 前端快照 build →
平台本体库 kb_compile（含 SHACL/断言/CSV对账）→ 双产物（canonical.ttl + 前端预览）
一起发布；任一步失败整批回滚到上一版，绝不留半成品。

边界纪律（硬约束）：
- 10_知识库工程 全程只读：content/ontology/sources/data/site/scripts 一律拷贝进
  本工程 .kb-publish/shadow/ 影子工作区；build.py / validate.py 跑的是影子里的副本
  （其 kbcommon.ROOT 由 __file__ 解析到影子），输出落影子，再提升到 app/data/site-preview/。
- 绝不写回 10 工程任何文件（含 site/）。

用法：
  python scripts/kb_publish.py                 # 同步影子 + 校验 + build + 编译 + 发布
  python scripts/kb_publish.py --no-sync        # 复用现有影子（不重新拷贝）
  python scripts/kb_publish.py --edit terms/cia-triad.md --append-summary "标记文本"
  python scripts/kb_publish.py --demo-edit      # 内置演示：给 cia-triad.summary 追加联调标记
  python scripts/kb_publish.py --rollback       # 手动回滚到上一版 canonical/preview
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from app.config import KB_ROOT as KB10_REAL, APP_DATA  # noqa: E402

WORK = PLATFORM_ROOT / ".kb-publish"
SHADOW = WORK / "shadow"
PREVIOUS = WORK / "previous"
PREV_TTL = PREVIOUS / "canonical.ttl"
PREV_PREVIEW = PREVIOUS / "site-preview"
PREVIEW = PLATFORM_ROOT / "app" / "data" / "site-preview"

CANONICAL_TTL = APP_DATA / "canonical.ttl"
PY = sys.executable


def log(msg: str) -> None:
    print(f"[kb-publish] {msg}", flush=True)


def run(cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, env=env, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True)


# ---------------------------------------------------------------------------
# 影子工作区同步（只读拷贝 10 工程骨架 + content）
# ---------------------------------------------------------------------------
def sync_shadow() -> None:
    """把 10 工程骨架与 content 只读拷贝进影子。10 工程绝不写回。

    ingest/ 也必须拷入：kb_compile 的 93号文编译器（app/kb_compiler/doc93.py）只读
    `ingest/v17/att1-selfcheck.txt` 产出 13 个自查检查项；影子缺该文件会导致编译结果
    静默丢弃 93 号文检查项（canonical 回退）。
    """
    log(f"同步影子工作区 <- {KB10_REAL}（只读拷贝）")
    if SHADOW.exists():
        shutil.rmtree(SHADOW)
    for sub in ("scripts", "ontology", "sources", "site", "content", "ingest"):
        src = KB10_REAL / sub
        if src.exists():
            shutil.copytree(src, SHADOW / sub)
    # data 目录只取权威登记表 control-codes.csv（build/编译器只读它），
    # 不拷 data/knowledge.json 等派生产物（那些由影子 build 重新生成）。
    (SHADOW / "data").mkdir(parents=True, exist_ok=True)
    cc = KB10_REAL / "data" / "control-codes.csv"
    if cc.exists():
        shutil.copy2(cc, SHADOW / "data" / "control-codes.csv")
    log(f"影子就绪: {SHADOW}")


def reconcile_controls() -> int:
    """影子只纳入 control-codes.csv 已登记的控制 MD（CSV 是 CT 码唯一权威）。

    剔除"MD 有但 CSV 未登记"的在途控制（里程碑3 续号未完成时，这些会让
    kb_compile 的 CSV↔MD 对账漂移、阻断发布）。返回被剔除的文件数。
    """
    import csv as _csv
    reg = set()
    with open(SHADOW / "data" / "control-codes.csv", encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            if row.get("id"):
                reg.add(row["id"].strip())
    cdir = SHADOW / "content" / "controls"
    removed = 0
    if cdir.exists():
        for p in cdir.glob("*.md"):
            if p.stem not in reg:
                p.unlink()
                removed += 1
    log(f"控制对账：影子保留 {len(reg)} 个 CSV 已登记控制，剔除 {removed} 个在途未登记控制")
    return removed


# ---------------------------------------------------------------------------
# 影子内演示编辑（只改影子副本，不碰 10 工程）
# ---------------------------------------------------------------------------
def apply_edit(relpath: str, append_summary: str | None, demo: bool, bad: bool = False) -> Path:
    target = SHADOW / "content" / relpath
    if not target.exists():
        raise SystemExit(f"[kb-publish] 影子内编辑目标不存在: {target}")
    if bad:
        # 反向演示：把 cia-triad.level 改成非法枚举 L9 → validate 必报 ERROR
        relpath = "terms/cia-triad.md"
        target = SHADOW / "content" / relpath
        lines = target.read_text(encoding="utf-8").splitlines()
        out = [f'level: L9' if ln.startswith("level:") else ln for ln in lines]
        target.write_text("\n".join(out) + "\n", encoding="utf-8")
        log(f"反向坏编辑（影子内）: {relpath}  level -> 'L9'（非法枚举，应被质量门拦截）")
        return target
    if demo:
        # 内置演示：给 cia-triad.summary 追加一个可 grep 的联调标记
        relpath = "terms/cia-triad.md"
        target = SHADOW / "content" / relpath
        append_summary = "【kb-publish 流水线联调标记】"
    if append_summary:
        lines = target.read_text(encoding="utf-8").splitlines()
        out = []
        done = False
        for ln in lines:
            if ln.startswith("summary:") and not done:
                cur = ln.split(":", 1)[1].strip()
                cur = cur.strip('"').strip("'")
                out.append(f'summary: "{cur}{append_summary}"')
                done = True
            else:
                out.append(ln)
        if not done:
            raise SystemExit(f"[kb-publish] 未找到 summary: 行，无法追加: {target}")
        target.write_text("\n".join(out) + "\n", encoding="utf-8")
        log(f"演示编辑完成（影子内）: {relpath}  summary += '{append_summary}'")
    return target


# ---------------------------------------------------------------------------
# 上一版快照 / 回滚
# ---------------------------------------------------------------------------
def snapshot_previous() -> None:
    """发布前把当前（即将被替换的）canonical/preview 存为 previous，供回滚。"""
    PREVIOUS.mkdir(parents=True, exist_ok=True)
    if CANONICAL_TTL.exists():
        shutil.copy2(CANONICAL_TTL, PREV_TTL)
    if PREVIEW.exists():
        if PREV_PREVIEW.exists():
            shutil.rmtree(PREV_PREVIEW)
        shutil.copytree(PREVIEW, PREV_PREVIEW)
    log(f"已存上一版快照 -> {PREVIOUS}")


def rollback(msg: str) -> None:
    log(f"!! 发布失败：{msg}")
    if PREV_TTL.exists():
        shutil.copy2(PREV_TTL, CANONICAL_TTL)
        log(f"!! 已回滚 canonical.ttl <- {PREV_TTL.name}")
    if PREV_PREVIEW.exists():
        if PREVIEW.exists():
            shutil.rmtree(PREVIEW)
        shutil.copytree(PREV_PREVIEW, PREVIEW)
        log(f"!! 已回滚前端预览 <- previous/site-preview")


# ---------------------------------------------------------------------------
# 流水线步骤
# ---------------------------------------------------------------------------
BASELINE_JSON = WORK / "baseline.json"


def run_validate() -> tuple[dict, list[str]]:
    """跑影子 validate.py --strict，返回 (summary, ERROR 签名列表)。"""
    proc = run([PY, str(SHADOW / "scripts" / "validate.py"), "--strict"])
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    summary, in_err, errs = None, False, []
    for ln in proc.stdout.splitlines():
        if ln.startswith("## ERROR"):
            in_err = True
            continue
        if ln.startswith("## WARN"):
            in_err = False
        if in_err and ln.startswith("  E "):
            errs.append(ln[4:].strip())
        if ln.startswith("SUMMARY_JSON "):
            summary = json.loads(ln[len("SUMMARY_JSON "):])
    return summary, errs


def capture_baseline() -> None:
    """同步后、本包编辑前，记录影子当前质量基线（ERROR 计数+签名）。"""
    summary, errs = run_validate()
    BASELINE_JSON.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_JSON.write_text(json.dumps({
        "errors": summary["errors"], "warnings": summary["warnings"],
        "error_signatures": sorted(errs),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"质量基线已记录：ERROR={summary['errors']} WARN={summary['warnings']} "
        f"（{len(errs)} 条 ERROR 签名）-> {BASELINE_JSON.name}")


def step_validate_gate(strict_zero: bool) -> dict:
    """质量门：本包编辑不得引入新 ERROR、不得抬高 ERROR 计数。
    strict_zero=True 时额外要求字面 ERROR=0/WARN=0（终态目标）。"""
    summary, errs = run_validate()
    if not summary:
        rollback("validate 无 SUMMARY_JSON 输出")
        raise SystemExit(1)
    if strict_zero:
        if summary["errors"] != 0 or summary["warnings"] != 0:
            rollback(f"--strict-zero 要求 ERROR=0/WARN=0，当前 "
                     f"ERROR={summary['errors']} WARN={summary['warnings']}")
            raise SystemExit(1)
    else:
        base = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
        new_sigs = sorted(set(errs) - set(base["error_signatures"]))
        if summary["errors"] > base["errors"] or new_sigs:
            rollback(f"质量门未过：本包编辑引入新 ERROR {new_sigs} "
                     f"(ERROR {base['errors']}->{summary['errors']})")
            raise SystemExit(1)
        warn_delta = summary["warnings"] - base["warnings"]
        log(f"质量门通过：ERROR {base['errors']}->{summary['errors']}（无新增）；"
            f"WARN {base['warnings']}->{summary['warnings']}"
            f"{'（+'+str(warn_delta)+'）' if warn_delta else '（持平）'}")
    return summary


def step_build_preview() -> None:
    """调影子 build.py：产物落影子 data/ 与 site/data/（不写 10 工程）。"""
    proc = run([PY, str(SHADOW / "scripts" / "build.py")])
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        rollback(f"build.py 失败（exit={proc.returncode}）")
        raise SystemExit(1)
    log("前端快照 build 完成（影子内）✅")


def step_compile_canonical() -> None:
    """调平台 kb_compile.py --check，KB10_ROOT 指向影子 → 编译器吃影子编辑源。"""
    env = dict(os.environ)
    env["KB10_ROOT"] = str(SHADOW)
    proc = run([PY, str(PLATFORM_ROOT / "scripts" / "kb_compile.py"), "--check"], env=env)
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        # kb_compile 已覆写 canonical.ttl → 必须还原
        rollback("kb_compile --check 失败（SHACL/断言/CSV对账未过），已还原 canonical.ttl")
        raise SystemExit(1)
    log("kb_compile --check 通过：SHACL conforms / 断言 0 / CSV对账 0 漂移 ✅")


def promote_preview() -> None:
    """把影子 build 产物提升为平台前端预览快照 app/data/site-preview/。"""
    PREVIEW.mkdir(parents=True, exist_ok=True)
    pairs = [
        (SHADOW / "data" / "knowledge.json", PREVIEW / "knowledge.json"),
        (SHADOW / "data" / "graph.json", PREVIEW / "graph.json"),
        (SHADOW / "site" / "data" / "knowledge-data.js", PREVIEW / "knowledge-data.js"),
    ]
    for src, dst in pairs:
        if src.exists():
            shutil.copy2(src, dst)
    log(f"前端预览快照已发布 -> {PREVIEW}")


def step_load_db() -> None:
    """收尾：投影入库闭环——表结构迁移（db_migrate up）+ 投影重建（db_seed_kb）。

    库（ekos_ds_kb）是 canonical.ttl 的派生只读复印件（坏了整批重建即可，知识不丢），
    故入库失败不回滚已发布的"知识正本 + 前端预览"，仅告警并提示重跑脚本，
    避免"库不可达"阻断发布（本地/离线场景）。
    """
    env = dict(os.environ)
    m = run([PY, str(PLATFORM_ROOT / "scripts" / "db_migrate.py"), "up"], env=env)
    sys.stdout.write(m.stdout)
    if m.stderr.strip():
        sys.stderr.write(m.stderr)
    if m.returncode != 0:
        log("!! 投影迁移未完成（PostgreSQL 不可达？）：知识正本与预览已发布；"
            "稍后可重跑 scripts/db_migrate.py up")
        return
    s = run([PY, str(PLATFORM_ROOT / "scripts" / "db_seed_kb.py")], env=env)
    sys.stdout.write(s.stdout)
    if s.stderr.strip():
        sys.stderr.write(s.stderr)
    if s.returncode != 0:
        log("!! 投影入库未完成：知识正本与预览已发布；稍后可重跑 scripts/db_seed_kb.py")
        return
    log("投影入库闭环完成：ekos_ds_kb 已按正本整批重建 ✅")


# ---------------------------------------------------------------------------
def cmd_rollback() -> None:
    rollback("手动 --rollback")
    log("完成：已还原到上一版。")


def main() -> int:
    ap = argparse.ArgumentParser(description="kb-publish 统一发布流水线")
    ap.add_argument("--no-sync", action="store_true", help="跳过影子同步（复用现有影子）")
    ap.add_argument("--edit", default="", help="影子内编辑目标 content 相对路径，如 terms/cia-triad.md")
    ap.add_argument("--append-summary", default="", help="给目标 summary 行追加文本")
    ap.add_argument("--demo-edit", action="store_true", help="内置演示编辑：cia-triad.summary 追加联调标记")
    ap.add_argument("--bad-edit", action="store_true",
                    help="反向演示：cia-triad.level 改为非法枚举 L9，验证质量门拦截+回滚")
    ap.add_argument("--strict-zero", action="store_true",
                    help="质量门要求字面 ERROR=0/WARN=0（终态目标；默认按基线无回归）")
    ap.add_argument("--no-reconcile", action="store_true",
                    help="不剔除在途未登记控制（影子原样保留全部 MD 控制）")
    ap.add_argument("--rollback", action="store_true", help="回滚到上一版后退出")
    ap.add_argument("--skip-db", action="store_true",
                    help="跳过投影入库（db_migrate up + db_seed_kb）；默认发布后自动闭环入库")
    args = ap.parse_args()

    if args.rollback:
        cmd_rollback()
        return 0

    if not args.no_sync:
        sync_shadow()
    if not SHADOW.exists():
        log("影子工作区不存在，先执行同步（去掉 --no-sync）")
        return 1

    # 影子只纳入 CSV 已登记控制（避免在途未登记控制阻断 CSV↔MD 对账）
    if not args.no_reconcile:
        reconcile_controls()

    # 同步后、本包编辑前：记录质量基线（供"无回归"门比对）
    capture_baseline()

    if args.demo_edit or args.bad_edit or args.edit:
        apply_edit(args.edit or "terms/cia-triad.md",
                   args.append_summary or None, args.demo_edit, args.bad_edit)

    # 发布前快照上一版
    snapshot_previous()

    # 门1：双端 strict 质量门（默认无回归；--strict-zero 要求 0/0）
    step_validate_gate(args.strict_zero)
    # 门2：前端快照 build（影子内，输出重定向）
    step_build_preview()
    # 门3：平台本体编译 + SHACL/断言/CSV对账
    step_compile_canonical()
    # 提升前端预览（此前一直落在影子，此刻才发布）
    promote_preview()
    # 门4：投影入库闭环（表结构迁移 + 投影重建；库不可达仅告警不阻断）
    if not args.skip_db:
        step_load_db()

    log("发布成功：canonical.ttl + 前端预览已整体更新，上一版留存于 .kb-publish/previous/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
