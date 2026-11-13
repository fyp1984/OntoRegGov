#!/usr/bin/env python3
"""P1 自检：六维覆盖/审核落库/法规问答/接口不回归，全绿 exit 0。"""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8420"
fails = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    if not ok:
        fails.append(name)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


# 1) 六维覆盖（PG 直连）
import psycopg2
from app.config import KB_PG_DSN
conn = psycopg2.connect(KB_PG_DSN, connect_timeout=5)
cur = conn.cursor()
expect = {"jg93": 140, "pboc3": 56, "jf8": 32}
for dk, n in expect.items():
    cur.execute("""SELECT count(DISTINCT check_code) FROM check_six_dim WHERE doc_key=%s
                    AND check_code IN (SELECT check_code FROM check_six_dim WHERE doc_key=%s AND dimension='method')
                    AND check_code IN (SELECT check_code FROM check_six_dim WHERE doc_key=%s AND dimension='verdict')""",
                (dk, dk, dk))
    got = cur.fetchone()[0]
    check(f"六维覆盖 {dk} 方法+判定", got == n, f"covered={got}/{n}")

# 2) 审核台账：全部 approved 且 merged
cur.execute("SELECT status,count(*),bool_and(merged) FROM p1_sixdim_review GROUP BY status")
rows = cur.fetchall()
ok_merged = all(st == "approved" and cnt > 0 and m for st, cnt, m in rows) and len(rows) == 1
check("审核台账全部 approved 且已 merge", ok_merged, str(rows))

# 3) law_chunk 嵌入
cur.execute("SELECT count(*), count(embedding) FROM law_chunk")
lc, le = cur.fetchone()
check("law_chunk 已嵌入", lc == le and lc > 300, f"rows={lc} embedded={le}")
conn.close()

# 4) HTTP 接口
h = get("/api/health")
check("平台健康", h.get("status") == "ok", str(h.get("status")))

q = get("/api/p1/sixdim/stats")
landed = q["landed_check_six_dim"]
check("六维落库 jg93 method=140", landed["jg93"]["method"] == 140, str(landed["jg93"]))
check("六维落库 pboc3 method=56", landed["pboc3"]["method"] == 56, str(landed["pboc3"]))
check("六维落库 jf8 method=32", landed["jf8"]["method"] == 32, str(landed["jf8"]))

qa = get("/api/p1/law/qa?" + urllib.parse.urlencode({"q": "数据出境条件", "limit": 3}))
check("法规问答带引用命中", qa.get("total", 0) >= 1,
      f"total={qa.get('total')} first={qa['hits'][0]['citation'] if qa.get('hits') else '-'}")

sv = get("/api/scenarios/sc01-selfcheck-reception/functions/doc93_questionnaire") \
    if False else None
import urllib.request as _u
req = _u.Request(BASE + "/api/scenarios/sc01-selfcheck-reception/functions/doc93_questionnaire",
                  data=b"{}", method="POST", headers={"Content-Type": "application/json"})
with _u.urlopen(req, timeout=20) as r:
    q93 = json.loads(r.read().decode())
check("93问卷 ok total=139", q93.get("ok") and q93.get("total") == 139,
      f"ok={q93.get('ok')} total={q93.get('total')}")

# 5) P0 三路不回归
sr = get("/api/search?" + urllib.parse.urlencode({"q": "自动化决策"}))
routes = set()
for x in sr["results"]:
    for r in x.get("routes", [x.get("route", "")]):
        routes.add(str(r).split(":")[0].split("+")[0])
check("向量路仍命中", "vector" in routes, f"routes={sorted(routes)}")

print(f"\n合计 {len(expect)*3 + 6} 项候选，FAIL {len(fails)}")
if fails:
    print("FAILED:", fails)
    raise SystemExit(1)
print("P1 自检全绿")
