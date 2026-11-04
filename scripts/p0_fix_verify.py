import json
import urllib.parse
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:8420"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def _has(x, name):
    if str(x.get("route", "")).startswith(name) or x.get("graph") and name == "graph":
        return True
    return any(str(r).startswith(name) for r in x.get("routes", []))

# 1) 自动化决策：ILIKE 不命中，应出现 vector 独有命中
q = "自动化决策"
d = get("/api/search?" + urllib.parse.urlencode({"q": q}))
mix = Counter()
for x in d["results"]:
    for r in x.get("routes", [x.get("route", "baseline")]):
        mix[str(r).split(":")[0].split("+")[0]] += 1
print(f"[1] /api/search?q={q}  total={d['total']}  route mix={dict(mix)}")
for x in d["results"]:
    if _has(x, "vector"):
        print("    VECTOR", x.get("route"), x["id"], (x.get("label") or "")[:48])

# 2) 数据出境：应出现 graph(fuseki) 命中
q = "数据出境"
d = get("/api/search?" + urllib.parse.urlencode({"q": q}))
mix = Counter()
for x in d["results"]:
    for r in x.get("routes", [x.get("route", "baseline")]):
        mix[str(r).split(":")[0].split("+")[0]] += 1
print(f"\n[2] /api/search?q={q}  total={d['total']}  route mix={dict(mix)}")
for x in d["results"]:
    if _has(x, "graph"):
        print("    GRAPH", x.get("route"), x.get("routes"), x["id"], (x.get("label") or "")[:48])

# 3) 93号文合规自查问卷
q93 = post("/api/scenarios/sc01-selfcheck-reception/functions/doc93_questionnaire", {})
print(f"\n[3] doc93_questionnaire  ok={q93.get('ok')} total={q93.get('total')} "
      f"categoryCount={q93.get('categoryCount')} source={q93.get('source')} err={q93.get('error')}")
