#!/usr/bin/env python3
"""批量上传知识库 Markdown 文件到 WeKnora。

用法: python3 scripts/upload_kb_to_weknora.py
"""
import os
import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

# 配置
WEKNORA_API = "http://127.0.0.1:18180"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InAycHJvYmVAZWtvcy5sb2NhbCIsImV4cCI6MTgyNTIzMTM2MywiaWF0IjoxNzkzNjk1MzYzLCJ0ZW5hbnRfaWQiOjEwMDAwLCJ0eXBlIjoiYWNjZXNzIiwidXNlcl9pZCI6IjZlZWZhMzA2LTE4NjUtNGUwZS05ZWZhLTRhYzFjYWIxMWRlYSJ9.z5SOWrfgm5AVILh89CpgRKUhg-w8CWVgXAceK9gyp7E"
KB_ID = "71fbeecd-fada-46b7-8643-a86793a73a9b"
CONTENT_DIR = Path("/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/10_知识库工程/content")

CATEGORY_PREFIX = {
    "terms": "术语",
    "controls": "控制",
    "laws": "法规",
    "cases": "案例",
    "solutions": "方案",
    "standards": "标准",
    "organizations": "机构",
    "scenarios": "场景",
    "topics": "专题",
    "paths": "路径",
    "roles": "角色",
}

def upload_file(md_path: Path) -> tuple[bool, str]:
    """上传单个 md 文件到 WeKnora。"""
    try:
        content = md_path.read_text(encoding="utf-8")
        # 从路径推导分类和标题
        rel = md_path.relative_to(CONTENT_DIR)
        category = rel.parts[0]
        prefix = CATEGORY_PREFIX.get(category, category)
        # 用文件名作为标题（去掉 .md）
        title = f"[{prefix}] {md_path.stem}"

        payload = json.dumps({
            "title": title,
            "content": content,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{WEKNORA_API}/api/v1/knowledge-bases/{KB_ID}/knowledge/manual",
            data=payload,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                return True, title
            else:
                return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:200]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)[:200]

def main():
    md_files = sorted(CONTENT_DIR.rglob("*.md"))
    total = len(md_files)
    print(f"开始批量上传 {total} 个 Markdown 文件到 WeKnora 知识库 {KB_ID}")
    print(f"目标: {WEKNORA_API}")
    print("-" * 60)

    success = 0
    failed = 0
    failed_list = []

    for i, md_path in enumerate(md_files, 1):
        ok, msg = upload_file(md_path)
        if ok:
            success += 1
            if i % 50 == 0 or i == total:
                print(f"[{i}/{total}] ✅ {msg}")
        else:
            failed += 1
            failed_list.append((str(md_path), msg))
            print(f"[{i}/{total}] ❌ {md_path.name}: {msg}")

        # 限速：每秒约 5 个
        time.sleep(0.2)

    print("-" * 60)
    print(f"上传完成: 成功 {success} / 失败 {failed} / 总计 {total}")
    if failed_list:
        print("\n失败文件列表:")
        for path, err in failed_list[:20]:
            print(f"  {path}: {err}")

if __name__ == "__main__":
    main()
