"""OpenAI 兼容 LLM 抽取；无 key 自动降级为规则抽取（degraded=true，不报错）。

v1.12.0 变更：配置改为运行时读取（UI 设置优先、env 兜底），
前端保存 LLM 配置后无需重启即生效。
"""
from __future__ import annotations
from .. import settings_store
from . import extractor_rule


def extract(text: str, document_id: str = "doc") -> dict:
    cfg = settings_store.get_runtime_llm()
    api_key, base_url, model = cfg["api_key"], cfg["base_url"], cfg["model"]
    if not api_key:
        cands = extractor_rule.extract(text, document_id)
        for c in cands:
            c["provenance"] = "llm-degraded"
        return {"candidates": cands, "degraded": True,
                "reason": "未配置 API key，自动降级为确定性规则抽取"}
    # 有 key 时尝试 OpenAI 兼容接口；任何异常均降级，不阻断端到端。
    try:
        import json as _json
        from urllib import request as _req
        sys_p = ("你是合规知识抽取器。只输出 JSON：[{kind,label,mappedClass,span,payload}]，"
                 "kind∈Clause/Obligation/Control，span 为原文片段。")
        body = _json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": sys_p},
                         {"role": "user", "content": text[:4000]}],
            "temperature": 0.0,
        }).encode()
        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        req = _req.Request(url, data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with _req.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        parsed = _json.loads(content[content.find("["):content.rfind("]") + 1])
        cands = []
        for i, item in enumerate(parsed):
            cands.append({
                "id": f"llm-{i:03d}", "kind": item.get("kind", "Obligation"),
                "label": item.get("label", "")[:40], "mappedClass": item.get("mappedClass", "Obligation"),
                "confidence": 0.55, "provenance": "llm", "span": item.get("span", ""),
                "payload": item.get("payload", {}),
            })
        return {"candidates": cands, "degraded": False}
    except Exception as e:  # 任何 LLM 故障都降级，不中断
        cands = extractor_rule.extract(text, document_id)
        for c in cands:
            c["provenance"] = "llm-degraded"
        return {"candidates": cands, "degraded": True, "reason": f"LLM调用失败，降级规则抽取: {e}"}


def test_connection(payload: dict | None = None) -> dict:
    """连通性测试：使用（可覆盖的）运行时配置打一次最小 chat/completions 请求。

    payload 可选：{base_url?, api_key?, model?} 用于"先测后存"。
    返回 {ok, detail, ...}；不落库、不改配置。
    """
    import json as _json
    from urllib import request as _req
    cfg = settings_store.get_runtime_llm()
    base_url = (payload or {}).get("base_url") or cfg["base_url"]
    api_key = (payload or {}).get("api_key") or cfg["api_key"]
    model = (payload or {}).get("model") or cfg["model"]
    if not api_key:
        return {"ok": False, "detail": "未配置 API key（env 与 UI 均为空）"}
    try:
        body = _json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }).encode()
        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        req = _req.Request(url, data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with _req.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode())
        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")[:50]
        return {"ok": True, "detail": f"连通成功（{model}）: {reply or 'ok'}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"连通失败: {e}"}
