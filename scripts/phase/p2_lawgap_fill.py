#!/usr/bin/env python3
"""P2：补齐 law_chunk 中 jg24 两条"（同 X.Y）"交叉引用缺口（2.4←1.7、3.2←3.1）。

原条目无独立正文（仅"（同1.7）/（同3.1）"），P1 因过短跳过；P2 按引用解析到被引
条目的 article_text 生成继承 chunk，TEI 嵌入后幂等入库（ON CONFLICT DO NOTHING）。
只新增 law_chunk 行，不改既有行。
"""
import json
import urllib.request

import psycopg2

DSN = "postgresql://test:test@127.0.0.1:15432/ekos_ds_kb"
TEI = "http://127.0.0.1:18002/embed"
# 缺口条目 -> 被引条目
INHERIT = {"2.4": "1.7", "3.2": "3.1"}
DOC_LABEL = "金规24号 银行保险机构数据安全管理办法"


def embed(text):
    body = json.dumps({"inputs": [text], "normalize": True}).encode()
    req = urllib.request.Request(TEI, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())[0]


def main():
    conn = psycopg2.connect(DSN, connect_timeout=5)
    conn.autocommit = True
    inserted = 0
    try:
        with conn.cursor() as cur:
            for gap, src in INHERIT.items():
                cur.execute("""SELECT article_no,regulation,title,article_text
                               FROM inspection_check WHERE check_code=%s""", (src,))
                row = cur.fetchone()
                if not row:
                    print(f"SKIP {gap}: 被引 {src} 不存在")
                    continue
                art_no, reg, title, art_text = row
                content = f"（同{src}，本条交叉引用）{art_text}"
                vec = "[" + ",".join(f"{x:.8f}" for x in embed(content)) + "]"
                cur.execute(
                    """INSERT INTO law_chunk
                       (chunk_id,doc_key,article_no,check_code,chapter,regulation,
                        title,content,model,dim,embedding)
                       VALUES(%s,'jg24',%s,%s,NULL,%s,%s,%s,'bge-m3',1024,%s)
                       ON CONFLICT (chunk_id) DO NOTHING""",
                    (f"jg24-{gap}", art_no, gap, reg,
                     f"{title or ''}（同{src}）", content, vec))
                inserted += cur.rowcount or 0
                print(f"{'INS' if cur.rowcount else 'SKIP'} jg24-{gap} <- {src} ({art_no})")
    finally:
        conn.close()
    print(f"inserted={inserted}")


if __name__ == "__main__":
    main()
