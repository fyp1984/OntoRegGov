"""场景组装框架（任务线3）：配置驱动、可插拔的业务场景组件层。

大白话：以前"金规24号自查"是写死在 index.html + app.js 里的一坨页面。
本包把"一个业务场景"抽象成一份 registry.json 配置 + 若干可复用的函数适配器：
  - 新增场景 = 往 registry.json 加一段配置（引用既有步骤渲染器 + 既有/新函数），
    不动前端壳、不动核心 API；sc02 即纯配置注册的实证（零新增 Python 文件）。
  - 函数能力 = app/scenarios/functions/ 下的适配器，按 registry 里登记的 module 惰性加载。
"""
