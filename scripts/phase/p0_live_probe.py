import json, urllib.parse, urllib.request
from collections import Counter

for q in ["个人信息保护", "数据出境", "风险评估"]:
    url = "http://127.0.0.1:8420/api/search?" + urllib.parse.urlencode({"q": q})
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    print(f"\n===== {q}  total={d['total']} =====")
    print("route mix:", dict(Counter(x.get("route", "baseline") for x in d["results"])))
    for x in d["results"]:
        rt = x.get("route", "baseline")
        if rt in ("vector", "graph", "rag"):
            extra = x.get("documentId") or x.get("docKey") or ""
            print(f"  * [{rt}] {x['id']} {(x.get('label') or '')[:40]} {extra}")
