"""全量功能 Demo 包（金融行业数据安全知识库和智能体平台演示）。

本包为**独立增量模块**：自带 SQLite 演示库（app/data/demo.db），
不影响现有 app.db 与任何既有接口行为。导入失败时现有应用仍可正常启动
（见 app/main.py 末尾的可选挂载块）。
"""
from __future__ import annotations

__all__ = ["store", "seed", "router"]
