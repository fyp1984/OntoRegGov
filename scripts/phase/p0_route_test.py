import traceback
from app.services import db_kb as d

for q in ["个人信息保护", "数据出境", "风险评估"]:
    print(f"\n########## 查询: {q} ##########")
    print("=== VECTOR ===")
    try:
        for r in d.vector_search(q, 5):
            print("  ", r["score"], r["route"], r["id"], (r["label"] or "")[:42])
    except Exception:
        traceback.print_exc()
    print("=== GRAPH ===")
    try:
        for r in d.graph_search(q, 5):
            print("  ", r["route"], r["id"], (r["label"] or "")[:42])
    except Exception:
        traceback.print_exc()
    print("=== RAG ===")
    try:
        for r in d.rag_search(q, 3):
            print("  ", r["score"], r["route"], r.get("documentId"), r["label"])
    except Exception:
        traceback.print_exc()

print("\n=== FUSED: 个人信息保护 ===")
try:
    f = d.fused_search("个人信息保护", 12)
    print("total", f["total"], "routes", f["routes"])
    for r in f["results"]:
        print("  ", r.get("route"), r["id"], (r.get("label") or "")[:36])
except Exception:
    traceback.print_exc()
