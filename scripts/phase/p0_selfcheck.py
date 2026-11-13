#!/usr/bin/env python3
"""P0 平台前端/接口自检（只读 GET/POST，不写业务数据）。
逐项 PASS/FAIL，全绿 exit 0。基线 http://127.0.0.1:8420。
"""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8420"
results = []


def call(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# 1 健康 + 首页
s, h = call("GET", "/api/health")
check("健康 /api/health=200 ok", s == 200 and h.get("status") == "ok", str(h)[:60])
try:
    with urllib.request.urlopen(BASE + "/", timeout=10) as r:
        html = r.read().decode("utf-8", "ignore")
    check("首页 index.html 可加载", "kb_q" in html or "知识库" in html, f"{len(html)} bytes")
except Exception as e:
    check("首页 index.html 可加载", False, str(e)[:60])

# 2 四文号下拉计数（/api/checks?doc=）
expected = {"jg24": 116, "jg93": 140, "pboc3": 56, "jf8": 32}
allok = True
detail = []
for d, n in expected.items():
    _, r = call("GET", "/api/checks?" + urllib.parse.urlencode({"doc": d}))
    got = r["byDoc"].get(d, 0)
    detail.append(f"{d}={got}")
    if got != n:
        allok = False
check("监管检查库四文号计数 116/140/56/32", allok, " ".join(detail))

# 3 jg24 六维详情（1.1：elements/verdict/findings 非空）
_, c = call("GET", "/api/checks/1.1")
six = bool(c.get("elements")) and bool(c.get("verdict")) and bool(c.get("findings"))
check("jg24 六维详情 /api/checks/1.1（elements/verdict/findings）", six,
      f"elements={len(c.get('elements',[]))} verdict={'有' if c.get('verdict') else '无'} "
      f"findings={len(c.get('findings',[]))}")

# 4 jg93 / pboc3 / jf8 详情可返回（新增同步项）
for code in ["93-1.1", "pb3-1", "jf8-1"]:
    try:
        _, cc = call("GET", f"/api/checks/{code}")
        ok = cc.get("checkCode") == code and bool(cc.get("title") or cc.get("articleText"))
        check(f"新增检查项详情 {code}", ok, (cc.get("title") or "")[:30])
    except Exception as e:
        check(f"新增检查项详情 {code}", False, str(e)[:60])

# 5 审核队列 + ingest 入闸候选
_, q = call("GET", "/api/review/queue")
check("审核队列 /api/review/queue 200", isinstance(q.get("queue"), list), f"open={len(q['queue'])}")
_, ir = call("GET", "/api/ingest/review")
check("审核队列 ingest /api/ingest/review 200", "items" in ir, f"items={len(ir.get('items',[]))}")

# 6 场景清单 + 93号文合规自查问卷 139 项
_, sc = call("GET", "/api/scenarios")
check("场景清单 /api/scenarios 200", len(sc.get("components", [])) > 0,
      f"components={len(sc.get('components',[]))}")
_, q93 = call("POST", "/api/scenarios/sc01-selfcheck-reception/functions/doc93_questionnaire", {})
check("93号文合规自查问卷 total=139", q93.get("ok") and q93.get("total") == 139,
      f"ok={q93.get('ok')} total={q93.get('total')} cats={q93.get('categoryCount')}")

# 7 知识检索：基线保留 + 向量/RAG 路命中
_, srch = call("GET", "/api/search?" + urllib.parse.urlencode({"q": "个人信息保护"}))
# 归一化收集每结果的路由来源（routes 列表 + route 主标签；基线/keyword/graph 标注都算基线保留）
provenance = set()
for x in srch["results"]:
    for r in x.get("routes", [x.get("route", "baseline")]):
        provenance.add(str(r).split(":")[0].split("+")[0])
check("/api/search 基线结果保留",
      provenance & {"baseline", "keyword"},
      f"total={srch['total']} routes={sorted(provenance)}")
check("/api/search 向量路命中", "vector" in provenance)
check("/api/search RAG 路命中", "rag" in provenance)
# 7b 图谱路：数据出境应命中 fuseki 实体（可与基线同 id，以 routes 标注为准）
_, srch2 = call("GET", "/api/search?" + urllib.parse.urlencode({"q": "数据出境"}))
gprof = set()
for x in srch2["results"]:
    for r in x.get("routes", [x.get("route", "")]):
        gprof.add(str(r).split(":")[0])
check("/api/search 图谱路命中(fuseki)", "graph" in gprof,
      f"total={srch2['total']} routes={sorted(gprof)}")

# 8 控制清单 + 图端点
_, ctrl = call("GET", "/api/controls")
check("/api/controls 200", ctrl.get("total", 0) > 0, f"controls={ctrl.get('total')}")
_, gb = call("GET", "/api/graph/backend")
check("/api/graph/backend 200", "backend" in gb or "status" in gb, str(gb)[:50])

print("\n" + "=" * 56)
nf = sum(1 for _, ok, _ in results if not ok)
print(f"合计 {len(results)} 项，PASS {len(results)-nf}，FAIL {nf}")
raise SystemExit(1 if nf else 0)
