#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把知识库静态站点 app.js 内联改编为平台可用的 app/web/static/kb_site.js。

只做必要的机械改编（不改业务逻辑/文案/渲染）：

  1. IIFE -> window.KbSite = { init() }，改为延迟初始化（等首屏数据注入）
  2. DOM 锚点 app -> kb_app，nav -> kb_nav（避免与平台侧栏 #nav 冲突）
  3. 路由切换时的 window.scrollTo 改为滚动平台主容器（平台的滚动容器是 <main>）
  4. 按主题按需取数（v1.19）：首屏只加载轻量索引；知识图谱 / 条目详情 / 检索
     分别在需要时调用 /api/kb/knowledge/{graph,entity,search}，避免随知识库增长
     把全量载荷压到首屏。

用法：
    python3 scripts/kb_site/gen_kb_site_js.py
其中脚本源可用环境变量 KB_SITE_SRC 覆盖（默认取历史知识站点源码）。
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.environ.get(
    "KB_SITE_SRC",
    "/Users/FYP/Documents/@西北人的成长/20-Areas/信息安全/数据安全/"
    "10_知识库工程/site/assets/app.js",
)
DST = os.path.join(REPO, "app", "web", "static", "kb_site.js")

js = open(SRC, encoding="utf-8").read()


def sub(old: str, new: str, label: str) -> None:
    """精确替换一次；找不到锚点即报错（避免静默漏改）。"""
    global js
    assert old in js, "anchor not found: " + label
    js = js.replace(old, new, 1)


# ---------------- 1) IIFE -> window.KbSite.init() ----------------
OLD_HEAD = "(function () {\n  'use strict';\n"
NEW_HEAD = (
    "/* ============================================================\n"
    " * 数据安全知识库 · 站点应用（内联改编自 10_知识库工程/site/assets/app.js）\n"
    " * 改编点：1) IIFE -> window.KbSite.init() 延迟初始化；\n"
    " *         2) DOM 锚点 app/nav -> kb_app/kb_nav；\n"
    " *         3) 路由滚动改为滚动平台主容器；\n"
    " *         4) 按主题按需取数：首屏索引 + 图谱/详情/检索分接口（v1.19）。\n"
    " * 数据来源：window.KNOWLEDGE_BASE（首屏轻量索引，见 app.js:kbSiteShow）\n"
    " *           + /api/kb/knowledge/{graph,entity,search} 子接口。\n"
    " * ========================================================== */\n"
    "window.KbSite = (function () {\n  'use strict';\n\n  function init() {\n"
)
sub(OLD_HEAD, NEW_HEAD, "head")

OLD_TAIL = (
    "  /* ---------------- 启动 ---------------- */\n"
    "  window.addEventListener('hashchange', render);\n"
    "  if (!location.hash) location.hash = '#/';\n"
    "  render();\n"
    "})();\n"
)
NEW_TAIL = (
    "    /* ---------------- 启动 ---------------- */\n"
    "    window.addEventListener('hashchange', render);\n"
    "    if (!location.hash) location.hash = '#/';\n"
    "    render();\n"
    "  }\n\n"
    "  return { init: init };\n"
    "})();\n"
)
sub(OLD_TAIL, NEW_TAIL, "tail")

# ---------------- 2) DOM 锚点改名 ----------------
sub("document.getElementById('app')", "document.getElementById('kb_app')", "app anchor")
sub("document.getElementById('nav')", "document.getElementById('kb_nav')", "nav anchor")

# ---------------- 3) 滚动兜底 ----------------
ANCHOR = "  var appEl = document.getElementById('kb_app');\n"
HELPER = (
    ANCHOR
    + "  // 平台内嵌：真实滚动容器是平台的 <main>，切换路由时把两者都归零\n"
    + "  function scrollTopPlatform() {\n"
    + "    try {\n"
    + "      var m = appEl && appEl.closest ? appEl.closest('main') : null;\n"
    + "      if (m) m.scrollTop = 0;\n"
    + "    } catch (e) {}\n"
    + "    try { window.scrollTo(0, 0); } catch (e) {}\n"
    + "  }\n"
)
sub(ANCHOR, HELPER, "appEl anchor")
sub("    window.scrollTo(0, 0);\n", "    scrollTopPlatform();\n", "scrollTo")

# ================================================================
# 4) 按主题按需取数（v1.19 子接口）
# ================================================================

# 4.1 数据层：实体/图谱/检索的按需取数 + 入链缓存
sub(
    "  var ENT = new Map(KB.entities.map(function (e) { return [e.id, e]; }));\n",
    "  var ENT = new Map(KB.entities.map(function (e) { return [e.id, e]; }));\n"
    "\n"
    "  /* ---------------- 按主题按需取数（v1.19 子接口） ----------------\n"
    "   * 首屏仅加载轻量索引（/api/kb/knowledge/index）；图谱、条目详情、检索按\n"
    "   * 主题分接口在需要时取数，避免知识库增长后把全量载荷压到首屏。 */\n"
    "  var IN_CACHE = {};        // 入链缓存（随条目详情接口返回）\n"
    "  var GRAPH_LOADED = false, GRAPH_PENDING = null;\n"
    "\n"
    "  function apiGet(url) {\n"
    "    return fetch(url, { headers: { 'Accept': 'application/json' } })\n"
    "      .then(function (r) { return r.json(); });\n"
    "  }\n"
    "  function mergeEntity(rec) {\n"
    "    if (!rec || !rec.id) return;\n"
    "    ENT.set(rec.id, rec);\n"
    "    for (var i = 0; i < KB.entities.length; i++) {\n"
    "      if (KB.entities[i].id === rec.id) { KB.entities[i] = rec; return; }\n"
    "    }\n"
    "    KB.entities.push(rec);\n"
    "  }\n"
    "  function loadEntity(id) {\n"
    "    return apiGet('/api/kb/knowledge/entity/' + encodeURIComponent(id)).then(function (env) {\n"
    "      var c = env && env.content;\n"
    "      if (!c || !c.entity) return null;\n"
    "      mergeEntity(c.entity);\n"
    "      IN_CACHE[id] = c.relations_in || [];\n"
    "      return c.entity;\n"
    "    });\n"
    "  }\n"
    "  function loadGraph() {\n"
    "    if (GRAPH_LOADED) return Promise.resolve(true);\n"
    "    if (GRAPH_PENDING) return GRAPH_PENDING;\n"
    "    GRAPH_PENDING = apiGet('/api/kb/knowledge/graph').then(function (env) {\n"
    "      var c = env && env.content;\n"
    "      if (c && c.nodes) { KB.nodes = c.nodes; KB.edges = c.edges || []; GRAPH_LOADED = true; }\n"
    "      GRAPH_PENDING = null;\n"
    "      return GRAPH_LOADED;\n"
    "    }).catch(function () { GRAPH_PENDING = null; return false; });\n"
    "    return GRAPH_PENDING;\n"
    "  }\n"
    "  /* 入链：图谱已加载则用全量边反查，否则用条目详情接口带回的 relations_in */\n"
    "  function incomingRels(id) {\n"
    "    if (GRAPH_LOADED) {\n"
    "      return (KB.edges || []).filter(function (x) { return x.target === id; })\n"
    "        .map(function (x) { return { rel: x.rel, other: x.source, source: x.source, label: x.label }; });\n"
    "    }\n"
    "    return (IN_CACHE[id] || []).map(function (x) {\n"
    "      return { rel: x.rel, other: x.source, source: x.source, label: x.label };\n"
    "    });\n"
    "  }\n",
    "data-layer",
)

# 4.2 轻量索引携带边数：首页「知识关联边」不再依赖全量 edges
sub(
    "      counts: RAW.counts || {}\n",
    "      counts: RAW.counts || {}, edgeCount: RAW.edgeCount || 0\n",
    "meta edgeCount",
)
sub(
    "(KB.edges || []).length + '</div><div class=\"lbl\">知识关联边</div>",
    "((KB.meta && KB.meta.edgeCount) || (KB.edges || []).length) + "
    "'</div><div class=\"lbl\">知识关联边</div>",
    "home edge stat",
)

# 4.3 渲染序号：异步取数返回时若已切路由则丢弃结果
sub(
    "  var graphRaf = null, graphCleanup = null;\n",
    "  var graphRaf = null, graphCleanup = null;\n"
    "  var RENDER_SEQ = 0;   // 渲染序号：异步取数返回时若已切路由则丢弃\n",
    "render-seq decl",
)
sub(
    "  function render() {\n    stopGraph();\n",
    "  function render() {\n    stopGraph();\n    RENDER_SEQ++;\n",
    "render-seq bump",
)

# 4.4 检索改走服务端全字段接口（含正文），失败回落本地索引
sub(
    "    input.addEventListener('input', function () {\n"
    "      var q = input.value;\n"
    "      if (!q.trim()) { box.innerHTML = ''; return; }\n"
    "      var res = doSearch(q);\n"
    "      if (!res.length) { box.innerHTML = '<div class=\"sr-empty\">未找到与 “' + esc(q) + '” 相关的条目</div>'; return; }\n"
    "      box.innerHTML = res.map(function (r) {\n"
    "        var e = r.e;\n"
    "        var als = arr(e.aliases).filter(function (a) { return typeof a === 'string'; });\n"
    "        return '<a class=\"sr-item\" href=\"#/entity/' + encodeURIComponent(e.id) + '\">' +\n"
    "          '<div class=\"sr-title\">' + highlight(str(e.title), q) + '</div>' +\n"
    "          '<div class=\"sr-meta\">' + typeMeta(e.type).label + ' · ' + esc(e.level) +\n"
    "          (als.length ? ' · 别名：' + als.map(function (a) { return highlight(a, q); }).join('、') : '') +\n"
    "          '</div>' +\n"
    "          '<div class=\"sr-snip\">' + highlight(snippet(e, q), q) + '</div></a>';\n"
    "      }).join('');\n"
    "    });\n",
    "    var searchSeq = 0, searchTimer = null;\n"
    "    // 结果渲染：兼容服务端检索（{id,title,type,level,aliases,snippet}）与本地兜底（{e,...}）\n"
    "    function renderResults(q, res) {\n"
    "      if (!res.length) { box.innerHTML = '<div class=\"sr-empty\">未找到与 “' + esc(q) + '” 相关的条目</div>'; return; }\n"
    "      box.innerHTML = res.map(function (r) {\n"
    "        var e = r.e || r;\n"
    "        var als = arr(e.aliases).filter(function (a) { return typeof a === 'string'; });\n"
    "        var snip = r.snippet != null ? r.snippet : snippet(e, q);\n"
    "        return '<a class=\"sr-item\" href=\"#/entity/' + encodeURIComponent(e.id) + '\">' +\n"
    "          '<div class=\"sr-title\">' + highlight(str(e.title), q) + '</div>' +\n"
    "          '<div class=\"sr-meta\">' + typeMeta(e.type).label + ' · ' + esc(e.level) +\n"
    "          (als.length ? ' · 别名：' + als.map(function (a) { return highlight(a, q); }).join('、') : '') +\n"
    "          '</div>' +\n"
    "          '<div class=\"sr-snip\">' + highlight(str(snip), q) + '</div></a>';\n"
    "      }).join('');\n"
    "    }\n"
    "    input.addEventListener('input', function () {\n"
    "      var q = input.value;\n"
    "      if (!q.trim()) { box.innerHTML = ''; return; }\n"
    "      clearTimeout(searchTimer);\n"
    "      var seq = ++searchSeq;\n"
    "      // 检索走服务端全字段接口（含正文），避免首屏把全量正文带到浏览器\n"
    "      searchTimer = setTimeout(function () {\n"
    "        apiGet('/api/kb/knowledge/search?limit=12&q=' + encodeURIComponent(q)).then(function (env) {\n"
    "          if (seq !== searchSeq) return;\n"
    "          var c = env && env.content;\n"
    "          renderResults(q, (c && c.results) || []);\n"
    "        }).catch(function () {\n"
    "          if (seq === searchSeq) renderResults(q, doSearch(q));   // 兜底：本地索引\n"
    "        });\n"
    "      }, 120);\n"
    "    });\n",
    "search",
)

# 4.5 条目详情改走 /api/kb/knowledge/entity/{id}
sub(
    "  function renderEntity(id, crumbType) {\n"
    "    var e = ENT.get(id);\n"
    "    if (!e) return renderNotFound(id);\n"
    "    setCrumbs([crumbType || typeMeta(e.type).label, e.title]);\n",
    "  function renderEntity(id, crumbType) {\n"
    "    var hit = ENT.get(id);\n"
    "    if (hit && 'body_html' in hit) return renderEntityFull(hit, crumbType);\n"
    "    appEl.innerHTML = '<div class=\"empty\" style=\"margin-top:24px\"><h2>' +\n"
    "      esc(hit ? hit.title : '内容加载中…') + '</h2><p>正在获取条目详情…</p></div>';\n"
    "    var seq = RENDER_SEQ;\n"
    "    loadEntity(id).then(function (rec) {\n"
    "      if (seq !== RENDER_SEQ) return;\n"
    "      if (!rec) return renderNotFound(id);\n"
    "      renderEntityFull(rec, crumbType);\n"
    "    }).catch(function () {\n"
    "      if (seq !== RENDER_SEQ) return;\n"
    "      if (hit) renderEntityFull(hit, crumbType); else renderNotFound(id);\n"
    "    });\n"
    "  }\n"
    "\n"
    "  function renderEntityFull(e, crumbType) {\n"
    "    setCrumbs([crumbType || typeMeta(e.type).label, e.title]);\n",
    "entity-detail",
)
sub(
    "    var inRels = (KB.edges || []).filter(function (x) { return x.target === id; })\n"
    "      .map(function (x) { return { rel: x.rel, other: x.source, dir: 'in', label: x.label }; });\n",
    "    var inRels = incomingRels(e.id).map(function (r) { r.dir = 'in'; return r; });\n",
    "in-rels",
)
sub(
    "    (KB.edges || []).forEach(function (x) {\n"
    "      if (x.target === e.id && (x.rel === 'implements' || x.rel === 'deploys_control')) {\n"
    "        var src = ENT.get(x.source);\n"
    "        if (src && src.type === 'solution') prodIds[src.id] = 1;\n"
    "      }\n"
    "    });\n",
    "    incomingRels(e.id).forEach(function (x) {\n"
    "      if (x.rel === 'implements' || x.rel === 'deploys_control') {\n"
    "        var src = ENT.get(x.source);\n"
    "        if (src && src.type === 'solution') prodIds[src.id] = 1;\n"
    "      }\n"
    "    });\n",
    "control-products",
)

# 4.6 图谱视图改走 /api/kb/knowledge/graph
sub(
    "  function renderGraphView() {\n"
    "    var types = Object.keys(TYPE_META).filter(function (t) {\n",
    "  function renderGraphView() {\n"
    "    var seq = RENDER_SEQ;\n"
    "    appEl.innerHTML = '<div class=\"section\" style=\"margin-top:4px\"><div class=\"section-head\">' +\n"
    "      '<h2>知识图谱</h2><span class=\"sub\">图谱数据加载中…</span></div></div>';\n"
    "    loadGraph().then(function (ok) {\n"
    "      if (seq !== RENDER_SEQ) return;\n"
    "      if (!ok) {\n"
    "        appEl.innerHTML = '<div class=\"empty\" style=\"margin-top:24px\"><h2>图谱数据暂不可用</h2>' +\n"
    "          '<p>知识库平台暂不可达，请稍后重试。</p></div>';\n"
    "        return;\n"
    "      }\n"
    "      renderGraphViewNow();\n"
    "    });\n"
    "  }\n"
    "\n"
    "  function renderGraphViewNow() {\n"
    "    var types = Object.keys(TYPE_META).filter(function (t) {\n",
    "graph-view",
)

open(DST, "w", encoding="utf-8").write(js)
print("wrote", DST, len(js), "bytes")
