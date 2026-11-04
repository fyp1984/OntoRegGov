"""场景组件加载器（配置驱动核心）。

职责：
  1) 读 app/scenarios/registry.json（带缓存，reload() 清缓存便于开发）；
  2) 结构校验：组件必填字段、workflowSteps.type 命中词汇表、functions.module 可解析；
  3) 函数分发：按 registry 登记的 module 惰性 import，调用其 run(params)，参数 = 默认 params ∪ body。

不做：不在此处执行业务逻辑——业务一律下沉到 functions/ 适配器或平台既有 services。
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).parent / "registry.json"

_registry_cache: dict | None = None


class RegistryError(Exception):
    """注册表结构错误或分发失败。code 用于 REST 层映射 HTTP 状态。"""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def reload() -> None:
    global _registry_cache
    _registry_cache = None


def _load() -> dict:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    if not REGISTRY_PATH.exists():
        raise RegistryError("registry_missing", f"注册表不存在: {REGISTRY_PATH}")
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RegistryError("registry_invalid_json", f"注册表 JSON 解析失败: {e}")
    _validate(data)
    _registry_cache = data
    return data


# ---------------- 结构校验 ----------------
_REQUIRED_COMPONENT = {"id", "name", "kind", "workflowSteps", "functions"}
_REQUIRED_STEP = {"id", "title", "type"}
_REQUIRED_FUNC = {"id", "name", "module"}


def _validate(data: dict) -> None:
    comps = data.get("components")
    if not isinstance(comps, list) or not comps:
        raise RegistryError("registry_invalid", "components 必须为非空数组")
    vocab = {s["type"] for s in data.get("stepTypeVocabulary", [])}
    seen_ids = set()
    for c in comps:
        miss = _REQUIRED_COMPONENT - set(c)
        if miss:
            raise RegistryError("registry_invalid", f"组件缺字段 {miss}: {c.get('id')}")
        if c["id"] in seen_ids:
            raise RegistryError("registry_invalid", f"组件 id 重复: {c['id']}")
        seen_ids.add(c["id"])
        for st in c["workflowSteps"]:
            if _REQUIRED_STEP - set(st):
                raise RegistryError("registry_invalid", f"步骤缺字段: {st}")
            if vocab and st["type"] not in vocab:
                raise RegistryError(
                    "registry_invalid",
                    f"组件 {c['id']} 步骤 {st['id']} 的 type={st['type']} 不在词汇表 {sorted(vocab)}")
        fids = set()
        for f in c["functions"]:
            if _REQUIRED_FUNC - set(f):
                raise RegistryError("registry_invalid", f"函数缺字段: {f}")
            if f["id"] in fids:
                raise RegistryError("registry_invalid", f"组件 {c['id']} 函数 id 重复: {f['id']}")
            fids.add(f["id"])


# ---------------- 读 API ----------------
def list_components() -> list[dict]:
    """注册表清单：返回组件概要（不含完整步骤/函数明细）。"""
    data = _load()
    out = []
    for c in data["components"]:
        out.append({
            "id": c["id"], "name": c["name"], "kind": c["kind"],
            "kindLabel": c.get("kindLabel", ""), "priority": c.get("priority", ""),
            "summary": c.get("summary", ""), "roles": c.get("roles", []),
            "consumedOntologyTypes": c.get("consumedOntologyTypes", []),
            "stepCount": len(c.get("workflowSteps", [])),
            "functionIds": [f["id"] for f in c.get("functions", [])],
        })
    return out


def get_component(sid: str) -> dict:
    data = _load()
    for c in data["components"]:
        if c["id"] == sid:
            return c
    raise RegistryError("component_not_found", f"场景组件不存在: {sid}")


# ---------------- 函数分发 ----------------
def call_function(sid: str, fid: str, body: dict | None = None) -> dict:
    """惰性 import registry 登记的 module，调用其 run(params)。
    params = 组件函数默认 params ∪ body（body 透传覆盖/补充）。"""
    comp = get_component(sid)
    func = next((f for f in comp.get("functions", []) if f["id"] == fid), None)
    if not func:
        raise RegistryError("function_not_found", f"组件 {sid} 未注册函数 {fid}")
    defaults = dict(func.get("params") or {})
    params = {**defaults, **(body or {})}
    module_name = func["module"]
    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        raise RegistryError("function_import_failed",
                            f"函数模块导入失败: {module_name}: {e}")
    run = getattr(mod, "run", None)
    if not callable(run):
        raise RegistryError("function_invalid",
                            f"函数模块 {module_name} 未实现 run(params)")
    result = run(params)
    if not isinstance(result, dict):
        raise RegistryError("function_bad_return",
                            f"函数 {fid} 返回值必须为 dict，实得 {type(result).__name__}")
    result["_scenario"] = sid
    result["_function"] = fid
    return result
