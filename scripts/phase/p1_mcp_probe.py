#!/usr/bin/env python3
"""P1 MCP 8422 真实客户端调用取证：list_tools + 逐 tool 调用，打印输入/输出。

用法：.venv/bin/python scripts/phase/p1_mcp_probe.py
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8422/mcp"
KEY = "dsec-demo-2026"


def _text(res) -> str:
    parts = []
    for c in res.content:
        if hasattr(c, "text"):
            parts.append(c.text)
    return "\n".join(parts)


async def main():
    async with streamablehttp_client(URL, headers={"Authorization": f"Bearer {KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"=== list_tools: {len(names)} 个 ===")
            for n in names:
                print("  -", n)

            async def call(name, args, compact=False):
                print(f"\n=== CALL {name} args={json.dumps(args, ensure_ascii=False)} ===")
                res = await session.call_tool(name, arguments=args)
                txt = _text(res)
                try:
                    data = json.loads(txt)
                    if compact and isinstance(data, dict):
                        data = {k: v for k, v in data.items()
                                if k in ("ok", "source", "total", "categoryCount",
                                         "problemTypeCount", "supervisionVersionTotal")}
                    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
                except Exception:
                    print(txt[:1500])

            await call("dsec_search", {"query": "数据出境", "limit": 5})
            await call("dsec_checks_by_doc", {"doc_key": "jg93", "limit": 3})
            await call("dsec_doc93_questionnaire", {}, compact=True)
            await call("dsec_law_qa", {"query": "数据出境需要满足什么条件", "limit": 3})
            await call("dsec_check_detail", {"check_code": "93-1.1"})


if __name__ == "__main__":
    asyncio.run(main())
