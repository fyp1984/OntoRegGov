#!/usr/bin/env python3
"""P1 六维审核链路 HTTP 驱动：generate(入闸) → queue → approve_all → merge → stats。

全部经平台 HTTP API（http://127.0.0.1:8420）真实调用，仅 approved 落 check_six_dim。
用法：.venv/bin/python scripts/phase/p1_sixdim_pipeline.py
"""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8420"
DOCS = ["jg93", "pboc3", "jf8"]


def call(method, path, body=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    print("========== 1) generate 入闸（规则草案，LLM 无 key 降级） ==========")
    for dk in DOCS:
        res = call("POST", "/api/p1/sixdim/generate", params={"doc_key": dk})
        print(f"[generate {dk}] {json.dumps(res, ensure_ascii=False)}")

    print("\n========== 2) 审核队列 pending 计数 ==========")
    for dk in DOCS:
        q = call("GET", "/api/p1/sixdim/queue", params={"doc_key": dk, "status": "pending"})
        by_dim = {}
        for it in q["items"]:
            by_dim[it["dimension"]] = by_dim.get(it["dimension"], 0) + 1
        print(f"[queue {dk}] pending={q['total']}  按维={json.dumps(by_dim, ensure_ascii=False)}")

    print("\n========== 3) approve_all 审核通过 ==========")
    for dk in DOCS:
        res = call("POST", "/api/p1/sixdim/approve_all", params={"doc_key": dk, "reviewer": "admin"})
        print(f"[approve_all {dk}] {json.dumps(res, ensure_ascii=False)}")

    print("\n========== 4) merge 落库（仅 approved） ==========")
    m = call("POST", "/api/p1/sixdim/merge")
    print(f"[merge] {json.dumps(m, ensure_ascii=False)}")

    print("\n========== 5) 最终 stats ==========")
    s = call("GET", "/api/p1/sixdim/stats")
    print(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
