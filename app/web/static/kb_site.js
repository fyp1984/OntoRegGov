/* ============================================================================
 * 数据安全知识库 · 站点应用（原生 JS，hash 路由，完全数据驱动）
 * 数据来源：window.KNOWLEDGE_BASE（data/knowledge-data.js，由构建脚本生成/覆盖）
 * ========================================================================== */
/* ============================================================
 * 数据安全知识库 · 站点应用（内联改编自 10_知识库工程/site/assets/app.js）
 * 改编点：1) IIFE -> window.KbSite.init() 延迟初始化；
 *         2) DOM 锚点 app/nav -> kb_app/kb_nav；
 *         3) 路由滚动改为滚动平台主容器；
 *         4) 按主题按需取数：首屏索引 + 图谱/详情/检索分接口（v1.19）。
 * 数据来源：window.KNOWLEDGE_BASE（首屏轻量索引，见 app.js:kbSiteShow）
 *           + /api/kb/knowledge/{graph,entity,search} 子接口。
 * ========================================================== */
window.KbSite = (function () {
  'use strict';
  /* 一次性事件绑定标记：init() 支持重复调用（设置页「刷新数据」重取后重建站点），
   * 避免每次重建都叠加一份 hashchange 监听。 */
  var _wired = false;

  function init() {

  // 兼容两种数据形状：{meta:{...}} 包裹 或 顶层扁平（generated_at/version/counts）
  var RAW = window.KNOWLEDGE_BASE || {};
  var KB = {
    meta: RAW.meta || {
      generated_at: RAW.generated_at, version: RAW.version,
      counts: RAW.counts || {}, edgeCount: RAW.edgeCount || 0
    },
    entities: RAW.entities || [],
    nodes: RAW.nodes || [],
    edges: RAW.edges || []
  };
  var ENT = new Map(KB.entities.map(function (e) { return [e.id, e]; }));

  /* ---------------- 按主题按需取数（v1.19 子接口） ----------------
   * 首屏仅加载轻量索引（/api/kb/knowledge/index）；图谱、条目详情、检索按
   * 主题分接口在需要时取数，避免知识库增长后把全量载荷压到首屏。 */
  var IN_CACHE = {};        // 入链缓存（随条目详情接口返回）
  /* 图谱多源（v1.20.0）：每个来源首次访问时各取一次并缓存；切换来源不重取。
   *   site     —— 本站知识库装配图（Markdown -> nodes/edges）
   *   native   —— 底层实体抽取图（经后端只读代理）
   *   ontology —— 平台本体镜像图
   * 后端在底层实体库不可达时自动回落 site，信封 source 字段标注实际来源。 */
  var GRAPH_SOURCES = [
    { key: 'site',     label: '知识库图谱',   hint: '本站知识库装配图 · 11 类实体' },
    { key: 'native',   label: '底层抽取图',   hint: '底层实体抽取图' },
    { key: 'ontology', label: '平台本体图',   hint: '平台本体镜像图' }
  ];
  var GRAPH_CACHE = {}, GRAPH_PENDING = {}, GRAPH_SRC = 'site', GRAPH_LOADED = false;
  // 取数来源英文键 → 中文可读名（避免英文键直接上屏）
  var SOURCE_TEXT = { weknora: '知识库实时', canonical: '正本图', db: '结构化投影', sqlite: '运行台账', site: '本站装配', none: '来源不可用' };

  function apiGet(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); });
  }
  function mergeEntity(rec) {
    if (!rec || !rec.id) return;
    ENT.set(rec.id, rec);
    for (var i = 0; i < KB.entities.length; i++) {
      if (KB.entities[i].id === rec.id) { KB.entities[i] = rec; return; }
    }
    KB.entities.push(rec);
  }
  function loadEntity(id) {
    return apiGet('/api/kb/knowledge/entity/' + encodeURIComponent(id)).then(function (env) {
      var c = env && env.content;
      if (!c || !c.entity) return null;
      mergeEntity(c.entity);
      IN_CACHE[id] = c.relations_in || [];
      return c.entity;
    });
  }
  function loadGraph(source) {
    source = source || GRAPH_SRC;
    if (GRAPH_CACHE[source]) return Promise.resolve(true);
    if (GRAPH_PENDING[source]) return GRAPH_PENDING[source];
    GRAPH_PENDING[source] = apiGet('/api/kb/knowledge/graph?source=' + encodeURIComponent(source))
      .then(function (env) {
        var c = env && env.content;
        if (c && c.nodes && c.nodes.length) {
          GRAPH_CACHE[source] = {
            nodes: c.nodes, edges: c.edges || [],
            meta: { graphSource: c.graphSource || source, source: env.source || '',
                    counts: c.counts || {}, generated_at: c.generated_at, version: c.version }
          };
          if (source === 'site') { KB.nodes = c.nodes; KB.edges = c.edges || []; GRAPH_LOADED = true; }
        }
        GRAPH_PENDING[source] = null;
        return !!GRAPH_CACHE[source];
      }).catch(function () { GRAPH_PENDING[source] = null; return false; });
    return GRAPH_PENDING[source];
  }
  /* 入链：图谱已加载则用全量边反查，否则用条目详情接口带回的 relations_in */
  function incomingRels(id) {
    if (GRAPH_LOADED) {
      return (KB.edges || []).filter(function (x) { return x.target === id; })
        .map(function (x) { return { rel: x.rel, other: x.source, source: x.source, label: x.label }; });
    }
    return (IN_CACHE[id] || []).map(function (x) {
      return { rel: x.rel, other: x.source, source: x.source, label: x.label };
    });
  }

  /* ---------------- 领域展示元数据（UI 层，非条目文案） ---------------- */
  /* 实体类型分类色：向品牌蓝/中性协调，降低饱和，保留可区分度（少量语义色相，无艳色/紫） */
  var TYPE_META = {
    term:         { label: '术语 / 概念', color: '#2B62F0' },  /* brand-500 */
    law:          { label: '法律法规',   color: '#0A2C9E' },  /* brand-800 */
    standard:     { label: '标准',       color: '#667085' },  /* neutral-500 */
    control:      { label: '控制措施',    color: '#4A7CFF' },  /* brand-400 */
    role:         { label: '角色岗位',    color: '#475467' },  /* neutral-600 */
    organization: { label: '权威机构',    color: '#98A2B3' },  /* neutral-400 */
    case:         { label: '案例事件',    color: '#DC2626' },  /* danger-600 */
    solution:     { label: '方案产品',    color: '#1240D2' },  /* brand-700 */
    scenario:     { label: '行业场景',    color: '#7EA6FF' },  /* brand-300 */
    guide:        { label: '学习路径',    color: '#1B4FE4' },  /* brand-600 */
    topic:        { label: '专题',        color: '#D97706' },  /* warning-600 */
    doc:          { label: '原始文档',    color: '#0E7490' }   /* teal-700：文件型（Word/PDF） */
  };
  var LEVEL_RADIUS = { L1: 9, L2: 12, L3: 15 };
  var STATUS_LABEL = { reviewed: '已核对', draft: '草稿', stale: '待更新' };
  var VALIDITY_LABEL = { effective: '现行有效', amended: '已修正', repealed: '已废止', draft: '征求意见' };
  var CASE_TYPE_LABEL = {
    leak: '数据泄露', penalty: '行政处罚', misuse: '滥用', theft: '窃取',
    ransomware: '勒索', 'compliance-rectification': '合规整改', insider: '内鬼',
    'ai-violation': 'AI违规'
  };
  /* ---------------- 控制体系（v1.5）四组中文映射，兜底英文键 ---------------- */
  var LAYER_LABEL = {
    endpoint: '端侧', network: '链路网络', service: '服务应用',
    protocol: '协议', management: '管理'
  };
  var LAYER_COLOR = {
    endpoint: '#1B4FE4', network: '#4A7CFF', service: '#1240D2',
    protocol: '#2B62F0', management: '#0A2C9E'
  };
  var LAYER_ORDER = ['endpoint', 'network', 'service', 'protocol', 'management'];
  var LIFECYCLE_LABEL = {
    collection: '采集', transmission: '传输', storage: '存储',
    processing: '使用加工', sharing: '共享提供', destruction: '删除销毁'
  };
  var LIFECYCLE_ORDER = ['collection', 'transmission', 'storage', 'processing', 'sharing', 'destruction'];
  var CONTROL_TYPE_LABEL = {
    govern: '治理', identify: '识别', protect: '保护',
    detect: '检测', respond: '响应', recover: '恢复'
  };
  var CONTROL_TYPE_ORDER = ['govern', 'identify', 'protect', 'detect', 'respond', 'recover'];
  var FRAMEWORK_LABEL = {
    'MLPS2.0': '等保2.0', 'DSMM': '数据安全能力', 'GBT43697': '数据分类分级',
    'GBT35273': '个人信息安全规范', 'MLPS-CRYPTO': '密评', 'JRT0197': '金融数据分级',
    'JRT0223': '金融数据生命周期', 'JINGUI-24-2024': '金规24号', 'NIST-CSF20': 'NIST CSF 2.0',
    'CIS-V8': 'CIS Controls v8', 'ISO27002-2022': 'ISO 27002'
  };
  var REL_LABELS = {
    defined_by: '定义/依据于', defines: '定义', broader: '上位概念', narrower: '下位概念',
    synonym: '同义/近义', antonym: '反义对照', contrasts_with: '对比辨析',
    member_of: '属于/归类于', has_member: '包含成员', prerequisite: '前置知识', enables: '支撑',
    related_term: '相关概念', governed_by: '受管于/合规依据', governs: '管辖',
    mitigates: '缓解风险', mitigated_by: '被缓解', implements: '落地实现', implemented_by: '实现于',
    cites_law: '引用法条', cites_standard: '引用标准', instance_of: '属于案例', has_instance: '案例',
    involves_role: '涉及角色', involved_in: '参与', occurs_in: '发生于场景', has_case: '案例',
    published_by: '发布/制定机构', publishes: '发布',
    part_of_path: '属于学习路径', includes: '包含步骤', see_also: '参见/延伸',
    deployed_with: '由产品落地', deploys_control: '落地该控制',
    related: '正文引用'
  };

  /* ---------------- 工具 ---------------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function stripHtml(html) {
    var d = document.createElement('div');
    d.innerHTML = html || '';
    return d.textContent || d.innerText || '';
  }
  /* 来源图谱可能含站点未登记的类型（如平台本体图 InspectionMethodStep / CheckElement）。
   * 对未知类型按名称稳定散列到调色板取色，保证同一类型跨会话同色、可区分。 */
  var ONTO_TYPE_LABEL = {
    Entity: '本体实体', InspectionMethodStep: '检查方法步骤', CheckElement: '检查要素',
    InspectionCheck: '检查项', Metric: '度量指标', FindingPattern: '问题模式',
    InterviewQuestion: '访谈问题', VerdictRule: '判定规则', entity: '抽取实体'
  };
  var EXTRA_PALETTE = ['#2B62F0', '#0A2C9E', '#4A7CFF', '#1240D2', '#1B4FE4', '#7EA6FF',
    '#667085', '#475467', '#98A2B3', '#344054', '#DC2626', '#D97706', '#0E7490', '#047857'];
  var TYPE_DYN = {};
  function dynColor(t) {
    if (!TYPE_DYN[t]) {
      var h = 0;
      for (var i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
      TYPE_DYN[t] = EXTRA_PALETTE[h % EXTRA_PALETTE.length];
    }
    return TYPE_DYN[t];
  }
  function typeMeta(t) { return TYPE_META[t] || { label: ONTO_TYPE_LABEL[t] || t, color: dynColor(t) }; }
  function relLabel(rel) { return REL_LABELS[rel] || rel; }

  function typeBadge(t) {
    var m = typeMeta(t);
    return '<span class="badge b-type" style="background:' + m.color + '14;color:' + m.color +
      ';border-color:' + m.color + '38">' + m.label + '</span>';
  }
  function levelBadge(lv) { return '<span class="badge b-level">' + esc(lv) + '</span>'; }
  function statusBadge(s) {
    return '<span class="badge b-status-' + esc(s) + '">' + (STATUS_LABEL[s] || esc(s)) + '</span>';
  }

  /* ---------------- 搜索索引（防御性归一：容忍字段缺失/类型异常） ---------------- */
  function arr(x) { return Array.isArray(x) ? x : []; }
  function str(x) { return String(x == null ? '' : x); }

  var index = (KB.entities || []).map(function (e) {
    var parts = [str(e.title), arr(e.aliases).filter(function (a) { return typeof a === 'string'; }).join(' '),
      arr(e.tags).filter(function (t) { return typeof t === 'string'; }).join(' '),
      str(e.summary), stripHtml(e.body_html)];
    return { e: e, text: parts.join(' ').toLowerCase() };
  });

  function doSearch(q) {
    q = (q || '').trim().toLowerCase();
    if (!q) return [];
    var tokens = q.split(/\s+/).filter(Boolean);
    var out = [];
    index.forEach(function (it) {
      var t = it.text, score = 0;
      var title = str(it.e.title).toLowerCase();
      if (title.indexOf(q) >= 0) score += 100;
      arr(it.e.aliases).forEach(function (a) { if (typeof a === 'string' && a.toLowerCase().indexOf(q) >= 0) score += 60; });
      arr(it.e.tags).forEach(function (t2) { if (typeof t2 === 'string' && t2.toLowerCase().indexOf(q) >= 0) score += 40; });
      if (str(it.e.summary).toLowerCase().indexOf(q) >= 0) score += 25;
      var allHit = tokens.every(function (tk) { return t.indexOf(tk) >= 0; });
      if (!allHit) return;
      if (score === 0) score = 5;
      out.push({ e: it.e, score: score, text: t });
    });
    return out.sort(function (a, b) { return b.score - a.score; }).slice(0, 12);
  }

  function highlight(text, q) {
    var safe = esc(text);
    q = (q || '').trim();
    if (!q) return safe;
    var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
    return safe.replace(re, '<mark>$1</mark>');
  }
  function snippet(e, q) {
    var full = stripHtml(e.body_html);
    var idx = full.toLowerCase().indexOf(str(q).trim().toLowerCase());
    if (idx < 0) return str(e.summary);
    var s = Math.max(0, idx - 30);
    return (s > 0 ? '…' : '') + full.slice(s, s + 110) + '…';
  }

  /* ---------------- 路由 ---------------- */
  var appEl = document.getElementById('kb_app');
  // 平台内嵌：真实滚动容器是平台的 <main>，切换路由时把两者都归零
  function scrollTopPlatform() {
    try {
      var m = appEl && appEl.closest ? appEl.closest('main') : null;
      if (m) m.scrollTop = 0;
    } catch (e) {}
    try { window.scrollTo(0, 0); } catch (e) {}
  }
  var crumbEl = document.getElementById('crumbs');
  var navEl = document.getElementById('kb_nav');
  var graphRaf = null, graphCleanup = null;
  var RENDER_SEQ = 0;   // 渲染序号：异步取数返回时若已切路由则丢弃

  function stopGraph() {
    if (graphRaf) { cancelAnimationFrame(graphRaf); graphRaf = null; }
    if (graphCleanup) { graphCleanup(); graphCleanup = null; }
  }

  function parseHash() {
    var h = location.hash.replace(/^#\/?/, '');
    var parts = h.split('/').filter(Boolean);
    if (parts.length === 0) return { name: 'home' };
    switch (parts[0]) {
      case 'entity':  return { name: 'entity', id: decodeURIComponent(parts[1] || '') };
      case 'law':     return { name: 'law', id: decodeURIComponent(parts[1] || '') };
      case 'topic':   return { name: 'topic', id: decodeURIComponent(parts[1] || '') };
      case 'graph':   return { name: 'graph' };
      case 'path':    return { name: 'path', level: (parts[1] || '').toUpperCase() };
      case 'timeline':return { name: 'timeline' };
      case 'cases':   return { name: 'cases' };
      case 'type':    return { name: 'type', type: parts[1] || '' };
      case 'controls':
        // #/controls 或 #/controls/layer/:layer
        if (parts[1] === 'layer' && parts[2]) return { name: 'controls', layer: decodeURIComponent(parts[2]) };
        return { name: 'controls' };
      case 'control-mapping': return { name: 'control-mapping' };
      case 'checks':  return { name: 'checks' };
      default:        return { name: 'notfound', path: h };
    }
  }

  function setNavActive(route) {
    var key = route.name === 'entity' ? '' : route.name;
    if (route.name === 'control-mapping') key = 'controls';
    Array.prototype.forEach.call(navEl.querySelectorAll('a'), function (a) {
      a.classList.toggle('active', a.getAttribute('data-nav') === key);
    });
  }
  function setCrumbs(arr) {
    if (!crumbEl) return;  // 面包屑元素已移除时安全跳过
    var html = '<a href="#/">首页</a>';
    arr.forEach(function (c, i) {
      html += '<span class="sep">/</span>';
      if (i === arr.length - 1) html += '<span class="here">' + esc(c) + '</span>';
      else html += '<span>' + esc(c) + '</span>';
    });
    crumbEl.innerHTML = html;
  }

  function render() {
    stopGraph();
    RENDER_SEQ++;
    scrollTopPlatform();
    var route = parseHash();
    setNavActive(route);
    switch (route.name) {
      case 'home':      setCrumbs([]); renderHome(); break;
      case 'entity':    renderEntity(route.id); break;
      case 'law':       renderEntity(route.id, '法规'); break;
      case 'topic':     renderEntity(route.id, '专题'); break;
      case 'graph':     setCrumbs(['知识图谱']); renderGraphView(); break;
      case 'path':      setCrumbs(['学习路径', route.level]); renderPath(route.level); break;
      case 'timeline':  setCrumbs(['法规时间线']); renderTimeline(); break;
      case 'cases':     setCrumbs(['案例库']); renderCases(); break;
      case 'type':      renderTypeList(route.type); break;
      case 'controls':  renderControls(route.layer); break;
      case 'checks':    setCrumbs(['监管检查库']); renderChecks(); break;
      case 'control-mapping': setCrumbs(['控制体系', '控制↔法规/标准映射']); renderControlMapping(); break;
      default:          setCrumbs(['未找到']); renderNotFound(route.path);
    }
  }

  /* ================= 视图：首页 ================= */
  function renderHome() {
    var counts = KB.meta.counts || {};
    var lvl = { L1: 0, L2: 0, L3: 0 };
    KB.entities.forEach(function (e) { lvl[e.level] = (lvl[e.level] || 0) + 1; });
    var total = KB.entities.length;

    var typeTiles = Object.keys(TYPE_META).map(function (t) {
      var n = counts[t] || 0;
      var m = typeMeta(t);
      return '<a class="type-tile" style="--tc:' + m.color + '" href="#/type/' + encodeURIComponent(t) + '">' +
        '<div class="t-name">' + m.label + '</div>' +
        '<div class="t-count">' + n + '</div>' +
        (n > 0 ? '' : '<div class="t-desc">建设中，敬请期待</div>') + '</a>';
    }).join('');

    // 精选卡片：案例 + 指南 + L1 入门条目
    var featured = KB.entities.filter(function (e) {
      return e.type === 'case' || e.type === 'guide' || e.level === 'L1';
    }).slice(0, 6).map(cardHtml).join('');

    // 重点法规 / 专题（数据驱动：所有专题 + 若干核心法规，链接走 #/law、#/topic 可分享路由）
    var topicList = KB.entities.filter(function (e) { return e.type === 'topic'; });
    var keyLawIds = ['pipl', 'csl', 'dsl', 'data-security-law', 'bank-insurance-data-security-measures'];
    var lawList = keyLawIds.map(function (id) { return ENT.get(id); }).filter(function (e) { return e && e.type === 'law'; });
    var highlights = topicList.concat(lawList).map(hlCardHtml).join('');

    appEl.innerHTML =
      '<section class="hero">' +
      '  <span class="hero-deco" aria-hidden="true"></span>' +
      '  <h1>数据安全知识库</h1>' +
      '  <div class="searchbox">' +
      '    <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>' +
      '    <input id="searchInput" type="search" placeholder="搜索标题、别名、标签、摘要或正文…" aria-label="全站检索" autocomplete="off">' +
      '    <div class="search-results" id="searchResults"></div>' +
      '  </div>' +
      '</section>' +

      '<div class="stat-row">' +
      '  <div class="stat-card"><div class="num">' + total + '</div><div class="lbl">条目总数</div></div>' +
      '  <div class="stat-card"><div class="num">' + ((KB.meta && KB.meta.edgeCount) || (KB.edges || []).length) + '</div><div class="lbl">知识关联边</div></div>' +
      '  <div class="stat-card"><div class="num">' + (lvl.L1 || 0) + ' / ' + (lvl.L2 || 0) + ' / ' + (lvl.L3 || 0) + '</div><div class="lbl">入门 / 进阶 / 专家 段位分布</div></div>' +
      '  <div class="stat-card"><div class="num">' + Object.keys(counts).filter(function (k) { return counts[k] > 0; }).length + '</div><div class="lbl">覆盖实体类型</div></div>' +
      '</div>' +

      '<div class="section">' +
      '  <div class="section-head"><h2>按类型浏览</h2><span class="sub">术语、法规、标准、控制、案例、学习路径等</span></div>' +
      '  <div class="type-grid">' + typeTiles + '</div>' +
      '</div>' +

      '<div class="section">' +
      '  <div class="section-head"><h2>重点法规 / 专题</h2></div>' +
      '  <div class="card-grid">' + highlights + '</div>' +
      '</div>' +

      '<div class="section">' +
      '  <div class="section-head"><h2>精选内容</h2><span class="sub">入门概念、标志性案例与分层学习路径</span>' +
      '  <a class="more" href="#/cases">全部案例 →</a></div>' +
      '  <div class="card-grid">' + featured + '</div>' +
      '</div>';

    bindSearch();
  }

  function renderTypeList(t) {
    if (!TYPE_META[t]) return renderNotFound('type/' + t);
    var list = KB.entities.filter(function (e) { return e.type === t; });
    var m = typeMeta(t);
    setCrumbs([m.label]);
    appEl.innerHTML =
      '<div class="section" style="margin-top:8px">' +
      '<div class="section-head"><h2>' + m.label + '</h2><span class="sub">共 ' + list.length + ' 条 · <a href="#/">返回首页</a></span></div>' +
      (list.length ? '<div class="card-grid">' + list.map(cardHtml).join('') + '</div>'
        : '<div class="empty"><h2>暂无此类条目</h2><p>该类型内容正在建设中。</p></div>') +
      '</div>';
  }

  function cardHtml(e) {
    return '<a class="entity-card" href="#/entity/' + encodeURIComponent(e.id) + '">' +
      '<div class="ec-title">' + esc(e.title) + '</div>' +
      '<div class="ec-summary">' + esc(e.summary) + '</div>' +
      '<div class="ec-foot">' + typeBadge(e.type) + levelBadge(e.level) +
      (e.tags || []).slice(0, 2).map(function (tg) { return '<span class="tag">' + esc(tg) + '</span>'; }).join('') +
      '</div></a>';
  }

  // 法规/专题可分享路由链接（law→#/law、topic→#/topic）
  function lawTopicHref(e) {
    if (e.type === 'law') return '#/law/' + encodeURIComponent(e.id);
    if (e.type === 'topic') return '#/topic/' + encodeURIComponent(e.id);
    return '#/entity/' + encodeURIComponent(e.id);
  }
  function hlCardHtml(e) {
    return '<a class="entity-card" href="' + lawTopicHref(e) + '">' +
      '<div class="ec-title">' + esc(e.title) + '</div>' +
      '<div class="ec-summary">' + esc(e.summary) + '</div>' +
      '<div class="ec-foot">' + typeBadge(e.type) +
      (e.tags || []).slice(0, 2).map(function (tg) { return '<span class="tag">' + esc(tg) + '</span>'; }).join('') +
      '</div></a>';
  }

  var docClickBound = false;
  function bindSearch() {
    var input = document.getElementById('searchInput');
    var box = document.getElementById('searchResults');
    if (!input) return;
    function results() { return box ? box.querySelectorAll('.sr-item') : []; }
    var searchSeq = 0, searchTimer = null;
    // 结果渲染：兼容服务端检索（{id,title,type,level,aliases,snippet}）与本地兜底（{e,...}）
    function renderResults(q, res) {
      if (!res.length) { box.innerHTML = '<div class="sr-empty">未找到与 “' + esc(q) + '” 相关的条目</div>'; return; }
      box.innerHTML = res.map(function (r) {
        var e = r.e || r;
        var als = arr(e.aliases).filter(function (a) { return typeof a === 'string'; });
        var snip = r.snippet != null ? r.snippet : snippet(e, q);
        return '<a class="sr-item" href="#/entity/' + encodeURIComponent(e.id) + '">' +
          '<div class="sr-title">' + highlight(str(e.title), q) + '</div>' +
          '<div class="sr-meta">' + typeMeta(e.type).label + ' · ' + esc(e.level) +
          (als.length ? ' · 别名：' + als.map(function (a) { return highlight(a, q); }).join('、') : '') +
          '</div>' +
          '<div class="sr-snip">' + highlight(str(snip), q) + '</div></a>';
      }).join('');
    }
    input.addEventListener('input', function () {
      var q = input.value;
      if (!q.trim()) { box.innerHTML = ''; return; }
      clearTimeout(searchTimer);
      var seq = ++searchSeq;
      // 检索走服务端全字段接口（含正文），避免首屏把全量正文带到浏览器
      searchTimer = setTimeout(function () {
        apiGet('/api/kb/knowledge/search?limit=12&q=' + encodeURIComponent(q)).then(function (env) {
          if (seq !== searchSeq) return;
          var c = env && env.content;
          renderResults(q, (c && c.results) || []);
        }).catch(function () {
          if (seq === searchSeq) renderResults(q, doSearch(q));   // 兜底：本地索引
        });
      }, 120);
    });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { input.value = ''; box.innerHTML = ''; input.blur(); return; }
      if (ev.key === 'Enter') {
        var items = results();
        if (items.length) {
          location.hash = items[0].getAttribute('href');
          box.innerHTML = ''; input.blur();
        }
      }
    });
    // 文档级点击收起：只绑定一次，处理时判断输入框是否仍在文档中
    if (!docClickBound) {
      docClickBound = true;
      document.addEventListener('click', function (ev) {
        var inp = document.getElementById('searchInput');
        var bx = document.getElementById('searchResults');
        if (!inp || !bx || !inp.isConnected) return;
        if (!bx.contains(ev.target) && ev.target !== inp) bx.innerHTML = '';
      });
    }
  }

  /* ================= 视图：实体详情 ================= */
  function renderEntity(id, crumbType) {
    var hit = ENT.get(id);
    if (hit && 'body_html' in hit) return renderEntityFull(hit, crumbType);
    appEl.innerHTML = '<div class="empty" style="margin-top:24px"><h2>' +
      esc(hit ? hit.title : '内容加载中…') + '</h2><p>正在获取条目详情…</p></div>';
    var seq = RENDER_SEQ;
    loadEntity(id).then(function (rec) {
      if (seq !== RENDER_SEQ) return;
      if (!rec) return renderNotFound(id);
      renderEntityFull(rec, crumbType);
    }).catch(function () {
      if (seq !== RENDER_SEQ) return;
      if (hit) renderEntityFull(hit, crumbType); else renderNotFound(id);
    });
  }

  function renderEntityFull(e, crumbType) {
    setCrumbs([crumbType || typeMeta(e.type).label, e.title]);

    // 出链 / 入链
    var outRels = (e.relations_out || []).map(function (r) {
      return { rel: r.rel, other: r.to, dir: 'out' };
    });
    var inRels = incomingRels(e.id).map(function (r) { r.dir = 'in'; return r; });

    function relBlock(title, list) {
      if (!list.length) return '';
      var groups = {};
      list.forEach(function (r) {
        var key = r.rel;
        (groups[key] = groups[key] || []).push(r);
      });
      var html = '<div class="rel-group"><div class="rg-label">' + esc(title) + '</div><div class="rel-list">';
      Object.keys(groups).forEach(function (k) {
        groups[k].forEach(function (r) {
          var t = ENT.get(r.other);
          if (!t) return;
          html += '<a class="rel-item" href="#/entity/' + encodeURIComponent(t.id) + '">' +
            '<span class="dir">' + (r.dir === 'out' ? '→' : '←') + '</span>' +
            esc(t.title) + '<span class="rt">' + esc(relLabel(k) !== k ? relLabel(k) : (r.label || k)) + '</span></a>';
        });
      });
      html += '</div></div>';
      return html;
    }

    // 来源表
    var srcRows = (e.sources || []).map(function (s) {
      var kindLabel = { local: '本地原料', official: '官方', standard: '标准', media: '媒体', book: '书籍', course: '课程' }[s.kind] || s.kind;
      var name = s.url ? '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.name) + '</a>' : '<span title="' + esc(s.path || '') + '">' + esc(s.name) + '</span>';
      return '<tr><td style="width:18%"><span class="src-kind">' + kindLabel + '</span></td>' +
        '<td style="width:42%">' + name + '</td>' +
        '<td style="width:20%">' + esc(s.issuer || '—') + '</td>' +
        '<td style="width:20%">' + esc(s.issued || s.effective || '—') + '</td></tr>';
    }).join('');

    // 类型特有结构化信息
    var factsHtml = '';
    if (e.type === 'law') {
      var a = e.attrs || {};
      factsHtml = '<div class="case-facts">' +
        fact('发布机关', esc(a.authority || '—')) +
        fact('文号', esc(a.doc_no || '—')) +
        fact('发布日期', esc(a.issued || '—')) +
        fact('生效日期', esc(a.effective || '—')) +
        '</div>' +
        '<p style="font-size:13.5px;color:var(--text-secondary)"><b>效力状态：</b>' +
        '<span class="badge b-validity-' + esc(a.validity) + '">' + (VALIDITY_LABEL[a.validity] || a.validity) + '</span></p>' +
        (a.penalties ? '<blockquote><p><b>法律责任：</b>' + esc(a.penalties) + '</p></blockquote>' : '');
    } else if (e.type === 'standard') {
      var sa = e.attrs || {};
      factsHtml = '<div class="case-facts">' +
        fact('标准号', esc(sa.std_no || '—')) +
        fact('发布机构', esc(sa.issuer || '—')) +
        fact('发布日期', esc(sa.issued || '—')) +
        fact('实施日期', esc(sa.effective || '—')) +
        '</div>';
    } else if (e.type === 'role') {
      var ra = e.attrs || {};
      factsHtml = '<ul>' + (ra.duties || []).map(function (d) { return '<li>' + esc(d) + '</li>'; }).join('') + '</ul>' +
        (ra.legal_basis ? '<p style="font-size:13.5px;color:var(--text-secondary)"><b>法定依据：</b>' + esc(ra.legal_basis) + '</p>' : '');
    } else if (e.type === 'organization') {
      var oa = e.attrs || {};
      factsHtml = '<div class="case-facts">' + fact('地区', esc(oa.region || '—')) +
        fact('机构类型', esc(oa.org_kind || '—')) + '</div>' +
        '<p style="font-size:14px">' + esc(oa.mandate || '') + '</p>';
    } else if (e.type === 'case') {
      factsHtml = caseFactsHtml(e);
    } else if (e.type === 'control') {
      factsHtml = controlFactsHtml(e);
    }

    appEl.innerHTML =
      '<div class="entity-head">' +
      '  <div class="badges">' + typeBadge(e.type) + levelBadge(e.level) + statusBadge(e.status) + '</div>' +
      '  <h1>' + esc(e.title) + (e.title_en ? '<span class="title-en">' + esc(e.title_en) + '</span>' : '') + '</h1>' +
      (e.aliases && e.aliases.length ? '<div class="aliases"><b>别名：</b>' + e.aliases.map(esc).join(' · ') + '</div>' : '') +
      '  <div class="summary">' + esc(e.summary) + '</div>' +
      (e.official_url
        ? '  <div class="head-actions"><a class="btn-outline" href="' + esc(e.official_url) + '" target="_blank" rel="noopener noreferrer">查看官方原文 ↗</a></div>'
        : '') +
      '  <div class="meta-row"><span>更新于 ' + esc(e.updated) + '</span><span>id: ' + esc(e.id) + '</span>' +
      (e.tags || []).map(function (t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('') + '</div>' +
      '</div>' +

      '<div class="detail-wrap">' +
      '  <div class="prose-card"><div class="prose">' +
      factsHtml +
      (e.body_html || '<p>（正文建设中）</p>') +
      mediaHtml(e) +
      '  </div></div>' +
      '  <aside class="side-card">' +
      relBlock('出链 →', outRels) +
      relBlock('入链 ←', inRels) +
      '  <h3 style="margin-top:18px">来源</h3>' +
      (srcRows ? '<table class="src-table"><colgroup><col style="width:18%"><col style="width:42%"><col style="width:20%"><col style="width:20%"></colgroup>' +
        '<thead><tr><th>类型</th><th>名称</th><th>机构</th><th>日期</th></tr></thead><tbody>' + srcRows + '</tbody></table>'
        : '<p style="font-size:13px;color:var(--text-secondary)">暂无来源记录</p>') +
      '  </aside>' +
      '</div>';
    bindMediaFails(appEl);
    if (e.type === 'topic') enhanceTopic(e);
  }

  /* 时限高亮：把日期/关键时限包成徽标 */
  function badgeDates(html) {
    return String(html)
      .replace(/(20\d{2}-\d{1,2}-\d{1,2}(?:\s*前)?)/g, '<span class="dl-badge">$1</span>')
      .replace(/(6月底前启动|6月底前)/g, '<span class="dl-badge">$1</span>');
  }

  /* ================= 专题专属增强（#/topic） ================= */
  function enhanceTopic(e) {
    var prose = appEl.querySelector('.prose');
    if (!prose) return;
    var hs = Array.prototype.slice.call(prose.querySelectorAll('h2'));
    if (!hs.length) return;
    // 分节锚点导航
    hs.forEach(function (h, i) { h.id = 'sec-' + i; });
    var nav = '<div class="toc-nav"><span class="toc-label">本专题</span>' +
      hs.map(function (h, i) {
        return '<a class="toc-link" data-tgt="sec-' + i + '">' + esc(h.textContent.trim()) + '</a>';
      }).join('') + '</div>';
    prose.insertAdjacentHTML('afterbegin', nav);
    prose.querySelectorAll('.toc-link').forEach(function (a) {
      a.addEventListener('click', function () {
        var t = document.getElementById(a.getAttribute('data-tgt'));
        if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });

    hs.forEach(function (h) {
      var title = h.textContent.trim();
      var nodes = [];
      var n = h.nextElementSibling;
      while (n && n.tagName !== 'H2') { nodes.push(n); n = n.nextElementSibling; }
      if (title.indexOf('四阶段时间线') >= 0) {
        var tbl = nodes.find ? nodes.find(function (x) { return x.tagName === 'TABLE'; }) : null;
        if (tbl) {
          var rows = tbl.querySelectorAll('tbody tr');
          var cards = Array.prototype.map.call(rows, function (tr, idx) {
            var c = tr.children;
            return '<div class="tl-stage">' +
              '<div class="ts-step">阶段 ' + (idx + 1) + '</div>' +
              '<div class="ts-name">' + c[0].textContent.trim() + '</div>' +
              '<div class="ts-time">' + c[1].textContent.trim() + '</div>' +
              '<div class="ts-owner">牵头：' + c[2].textContent.trim() + '</div>' +
              '<div class="ts-action">' + badgeDates(c[3].innerHTML) + '</div>' +
              '<div class="ts-deliver">' + badgeDates(c[4].innerHTML) + '</div>' +
              '</div>';
          }).join('');
          tbl.insertAdjacentHTML('beforebegin', '<div class="stage-timeline">' + cards + '</div>');
          tbl.remove();
        }
      } else if (title.indexOf('报送时限') >= 0) {
        nodes.forEach(function (nd) {
          if (nd.tagName === 'TD' || nd.tagName === 'TABLE') {
            nd.innerHTML = badgeDates(nd.innerHTML);
          } else if (nd.querySelectorAll) {
            Array.prototype.forEach.call(nd.querySelectorAll('td, th'), function (td) { td.innerHTML = badgeDates(td.innerHTML); });
          }
        });
      } else if (title.indexOf('检查项索引') >= 0) {
        if (nodes.length) {
          var det = document.createElement('details');
          det.className = 'idx-details';
          var sum = document.createElement('summary');
          sum.textContent = '展开查看检查项索引';
          det.appendChild(sum);
          nodes.forEach(function (x) { det.appendChild(x); });
          h.insertAdjacentElement('afterend', det);
        }
      }
    });
  }

  function fact(k, v) {
    return '<div class="case-fact"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>';
  }

  // 多媒体渲染：images 栅格（带 onerror 兜底）+ videos 卡片；media 全空则返回空串
  function mediaHtml(e) {
    var md = e.media || {};
    var imgs = md.images || [], vids = md.videos || [];
    if (!imgs.length && !vids.length) return '';
    var h = '';
    if (imgs.length) {
      h += '<div class="media-section"><h2 class="media-h">配图 / 图解</h2><div class="media-grid">';
      imgs.forEach(function (im) {
        var host = '';
        try { host = new URL(im.url).hostname; } catch (_) {}
        var failHref = im.source_url || im.url || '#';
        h += '<figure class="media-img">' +
          '<div class="media-img-wrap">' +
            '<img src="' + esc(im.url) + '" alt="' + esc(im.caption || e.title) + '" loading="lazy" referrerpolicy="no-referrer">' +
            '<div class="media-img-failed">' +
              '<div class="media-fail-icon">🖼</div>' +
              '<div class="media-fail-t">图片暂不可用</div>' +
              '<div class="media-fail-s">' + esc(im.source || host) + '</div>' +
              '<a class="media-fail-link" href="' + esc(failHref) + '" target="_blank" rel="noopener noreferrer">前往原站查看 ↗</a>' +
            '</div>' +
          '</div>' +
          (im.caption ? '<figcaption class="media-cap">' + esc(im.caption) + '</figcaption>' : '') +
          '<div class="media-credit">' +
            (im.source ? '<span>' + esc(im.source) + '</span>' : '') +
            (im.license ? '<span class="media-lic">' + esc(im.license) + '</span>' : '') +
            (im.source_url ? '<a href="' + esc(im.source_url) + '" target="_blank" rel="noopener noreferrer">来源 ↗</a>' : '') +
          '</div>' +
        '</figure>';
      });
      h += '</div></div>';
    }
    if (vids.length) {
      h += '<div class="media-section"><h2 class="media-h">推荐视频</h2><div class="media-vids">';
      vids.forEach(function (v) {
        var plat = (v.platform || '').toLowerCase();
        var badgeCls = plat === 'bilibili' ? 'mv-bili' : plat === 'youtube' ? 'mv-yt' : 'mv-official';
        var badgeTxt = plat === 'bilibili' ? 'B站' : '▶';
        h += '<a class="media-vid" href="' + esc(v.url) + '" target="_blank" rel="noopener noreferrer">' +
          '<span class="mv-badge ' + badgeCls + '">' + badgeTxt + '</span>' +
          '<span class="mv-body">' +
            '<span class="mv-title">' + esc(v.title) + '</span>' +
            '<span class="mv-meta">' + esc(v.platform || '') + (v.duration ? ' · ' + esc(v.duration) : '') + '</span>' +
            (v.desc ? '<span class="mv-desc">' + esc(v.desc) + '</span>' : '') +
          '</span>' +
          '<span class="mv-go">↗</span>' +
        '</a>';
      });
      h += '</div></div>';
    }
    return h;
  }

  // 为已渲染的媒体图绑定 error：失败时切换 .is-failed，显示兜底卡而非破图
  function bindMediaFails(root) {
    (root || appEl).querySelectorAll('.media-img img').forEach(function (img) {
      // 已缓存失败的图也会触发 error；绑定后立即检测 complete&&naturalWidth===0
      img.addEventListener('error', function () {
        var f = img.closest('.media-img');
        if (f) f.classList.add('is-failed');
      });
      if (img.complete && img.naturalWidth === 0) {
        var f0 = img.closest('.media-img');
        if (f0) f0.classList.add('is-failed');
      }
    });
  }

  function caseFactsHtml(e) {
    var a = e.attrs || {};
    var h = '<div class="case-facts">' +
      fact('事件日期', esc(a.event_date || '—')) +
      fact('事件类型', CASE_TYPE_LABEL[a.case_type] || esc(a.case_type || '—')) +
      fact('处罚金额', esc(a.penalty_amount || '—')) +
      fact('影响规模', esc(a.affected_scale || '—')) +
      '</div>';
    if (a.root_causes && a.root_causes.length) {
      h += '<h3 style="font-size:13px;color:var(--text-secondary);margin:6px 0 8px;letter-spacing:1px">根因标签</h3>' +
        '<div class="root-chips">' + a.root_causes.map(function (r) { return '<span class="chip">' + esc(r) + '</span>'; }).join('') + '</div>';
    }
    if (a.timeline && a.timeline.length) {
      h += '<h3 style="font-size:13px;color:var(--text-secondary);margin:18px 0 8px;letter-spacing:1px">处置时间线</h3><div class="timeline">';
      h += a.timeline.map(function (t) {
        return '<div class="tl-item"><div class="tl-date">' + esc(t.date) + '</div>' +
          '<div class="tl-axis"><div class="tl-dot"></div></div>' +
          '<div class="tl-body" style="box-shadow:none"><div class="tl-desc" style="margin:0">' + esc(t.event) + '</div></div></div>';
      }).join('');
      h += '</div>';
    }
    if (a.images && a.images.length) {
      h += '<div class="case-images">' + a.images.map(function (im) {
        return '<figure><img src="' + esc(im.src) + '" alt="' + esc(im.caption || e.title) + '" loading="lazy">' +
          (im.caption ? '<figcaption>' + esc(im.caption) + '</figcaption>' : '') + '</figure>';
      }).join('') + '</div>';
    }
    return h;
  }

  /* ================= 控制体系：详情专属区块 ================= */
  function controlFactsHtml(e) {
    var layer = e.layer, lc = arr(e.lifecycle), ct = e.control_type;
    var h = '<div class="case-facts">' +
      fact('控制编号', '<span class="ctrl-code">' + esc(e.code || '—') + '</span>') +
      fact('控制域', '<span class="layer-chip" style="--lc:' + (LAYER_COLOR[layer] || '#667085') + '">' +
        (LAYER_LABEL[layer] || esc(layer || '—')) + '</span>') +
      fact('控制类型', CONTROL_TYPE_LABEL[ct] || esc(ct || '—')) +
      fact('控制族', esc(e.family || '—')) +
      '</div>';
    // 生命周期阶段
    if (lc.length) {
      h += '<h3 class="ctrl-h">生命周期阶段</h3><div class="root-chips">' + lc.map(function (l) {
        return '<span class="chip">' + (LIFECYCLE_LABEL[l] || esc(l)) + '</span>';
      }).join('') + '</div>';
    }
    // 法规与标准映射表
    var sm = arr(e.standard_mappings);
    if (sm.length) {
      h += '<h3 class="ctrl-h">法规与标准映射</h3>' +
        '<div class="tbl-scroll"><table class="map-table"><thead><tr>' +
        '<th style="width:30%">框架/标准</th><th style="width:32%">条款 / 编号</th><th>说明</th>' +
        '</tr></thead><tbody>' +
        sm.map(function (m) {
          return '<tr><td>' + (FRAMEWORK_LABEL[m.framework] || esc(m.framework || '—')) + '</td>' +
            '<td>' + esc(m.ref || '—') + '</td>' +
            '<td>' + esc(m.note || '') + '</td></tr>';
        }).join('') +
        '</tbody></table></div>';
    }
    // 验证证据
    var evd = arr(e.evidence_examples);
    if (evd.length) {
      h += '<h3 class="ctrl-h">验证证据（长什么样算做到位）</h3><ul class="ctrl-evidence">' +
        evd.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ul>';
    }
    // 由哪些产品落地（outgoing deployed_with + incoming solution implements/deploys_control）
    var prodIds = {};
    arr(e.relations_out).forEach(function (r) {
      if (r.rel === 'deployed_with' || r.rel === 'deploys_control') prodIds[r.to] = 1;
    });
    incomingRels(e.id).forEach(function (x) {
      if (x.rel === 'implements' || x.rel === 'deploys_control') {
        var src = ENT.get(x.source);
        if (src && src.type === 'solution') prodIds[src.id] = 1;
      }
    });
    var prods = Object.keys(prodIds).map(function (id) { return ENT.get(id); }).filter(Boolean);
    if (prods.length) {
      h += '<h3 class="ctrl-h">由哪些产品落地</h3><div class="card-grid">' +
        prods.map(cardHtml).join('') + '</div>';
    }
    return h;
  }

  /* ================= 视图：控制体系地图 ================= */
  function allControls() { return KB.entities.filter(function (e) { return e.type === 'control'; }); }

  function controlCardHtml(e) {
    return '<a class="entity-card ctrl-card" href="#/entity/' + encodeURIComponent(e.id) + '">' +
      '<div class="cc-top"><span class="ctrl-code">' + esc(e.code || '') + '</span>' +
      '<span class="layer-chip" style="--lc:' + (LAYER_COLOR[e.layer] || '#667085') + '">' +
      (LAYER_LABEL[e.layer] || esc(e.layer || '')) + '</span></div>' +
      '<div class="ec-title">' + esc(e.title) + '</div>' +
      '<div class="ec-summary">' + esc(e.summary) + '</div>' +
      '<div class="ec-foot">' +
      (e.family ? '<span class="tag">' + esc(e.family) + '</span>' : '') +
      (e.control_type ? '<span class="tag">' + (CONTROL_TYPE_LABEL[e.control_type] || esc(e.control_type)) + '</span>' : '') +
      arr(e.lifecycle).slice(0, 2).map(function (l) { return '<span class="tag">' + (LIFECYCLE_LABEL[l] || esc(l)) + '</span>'; }).join('') +
      '</div></a>';
  }

  function renderControls(routeLayer) {
    var all = allControls();
    // 统计
    var layerCount = {}, ctCount = {};
    all.forEach(function (e) {
      layerCount[e.layer] = (layerCount[e.layer] || 0) + 1;
      ctCount[e.control_type] = (ctCount[e.control_type] || 0) + 1;
    });
    // 实际出现过的 lifecycle / framework（用于筛选 chips）
    var lcSet = {}, fwSet = {};
    all.forEach(function (e) {
      arr(e.lifecycle).forEach(function (l) { lcSet[l] = 1; });
      arr(e.standard_mappings).forEach(function (m) { fwSet[m.framework] = 1; });
    });

    function draw(f) {
      f = f || {};
      var list = all.filter(function (e) {
        if (f.layer && e.layer !== f.layer) return false;
        if (f.lc && arr(e.lifecycle).indexOf(f.lc) < 0) return false;
        if (f.ct && e.control_type !== f.ct) return false;
        if (f.fw && !arr(e.standard_mappings).some(function (m) { return m.framework === f.fw; })) return false;
        return true;
      });

      // 五域概览卡片
      var layerCards = LAYER_ORDER.map(function (ly) {
        var n = layerCount[ly] || 0;
        var active = f.layer === ly;
        return '<a class="layer-card' + (active ? ' on' : '') + '" href="#/controls/layer/' + ly + '" ' +
          'style="--lc:' + (LAYER_COLOR[ly] || '#667085') + '">' +
          '<div class="lc-dot"></div><div class="lc-name">' + (LAYER_LABEL[ly] || ly) + '</div>' +
          '<div class="lc-count">' + n + '</div></a>';
      }).join('');

      function chips(items, key, cur) {
        return ['<button type="button" class="chip' + (!cur ? ' on' : '') + '" data-f="' + key + '" data-v="">全部</button>']
          .concat(items.map(function (it) {
            var v = it.v, label = it.label;
            return '<button type="button" class="chip' + (cur === v ? ' on' : '') + '" data-f="' + key + '" data-v="' + v + '">' + label + '</button>';
          })).join('');
      }
      var lcItems = LIFECYCLE_ORDER.filter(function (l) { return lcSet[l]; }).map(function (l) { return { v: l, label: LIFECYCLE_LABEL[l] }; });
      var ctItems = CONTROL_TYPE_ORDER.filter(function (c) { return ctCount[c]; }).map(function (c) { return { v: c, label: CONTROL_TYPE_LABEL[c] }; });
      var fwItems = Object.keys(fwSet).map(function (fw) { return { v: fw, label: FRAMEWORK_LABEL[fw] || fw }; });

      var sub = f.layer ? (LAYER_LABEL[f.layer] + ' · ') : '';
      var body = list.length
        ? '<div class="card-grid">' + list.map(controlCardHtml).join('') + '</div>'
        : '<div class="empty"><h2>暂无符合条件的控制</h2><p>调整筛选试试。</p></div>';

      appEl.innerHTML =
        '<div class="section" style="margin-top:4px">' +

        '<div class="layer-grid">' + layerCards + '</div>' +
        '<div class="ctrl-map-link">' + (f.layer ? esc(sub) : '') + list.length + ' 条控制 · ' +
        '<a href="#/control-mapping">控制↔法规/标准映射 →</a></div>' +

        '<div class="ctrl-filter"><div class="cf-label">生命周期</div><div class="chip-row">' + chips(lcItems, 'lc', f.lc) + '</div></div>' +
        '<div class="ctrl-filter"><div class="cf-label">控制类型</div><div class="chip-row">' + chips(ctItems, 'ct', f.ct) + '</div></div>' +
        '<div class="ctrl-filter"><div class="cf-label">依据标准</div><div class="chip-row">' + chips(fwItems, 'fw', f.fw) + '</div></div>' +

        body + '</div>';

      // 筛选 chips：页内状态；layer 下钻走真路由
      appEl.querySelectorAll('.ctrl-filter [data-f]').forEach(function (b) {
        b.addEventListener('click', function () {
          var nf = { layer: f.layer, lc: f.lc, ct: f.ct, fw: f.fw };
          var key = b.getAttribute('data-f'), v = b.getAttribute('data-v');
          nf[key] = v || null;
          draw(nf);
        });
      });
    }
    draw(routeLayer ? { layer: routeLayer } : {});
    setCrumbs(routeLayer ? ['控制体系', LAYER_LABEL[routeLayer] || routeLayer] : ['控制体系']);
  }

  /* ================= 视图：监管检查库（PRD K3 · 多文号 · 关联检索） =================
   * 由知识库上方标签承载（见 index.html #kb_nav data-nav="checks"）。
   * 渲染宿主 DOM 后复用 app.js 的全局 loadChecks()/showCheck()：
   *   - 元素 id 与内联 onchange/oninput 调用保持与既往实现一致（#ck_doc/#ck_domain/
   *     #ck_pri/#ck_kw → #ck_list、点击行 → #ck_detail）；
   *   - 取数统一走 /api/checks（统一信封 + 降级链），页面不做分支渲染。 */
  function renderChecks() {
    var opts = function (vals) {
      return '<option value="">' + vals[0] + '</option>' + vals.slice(1).map(function (v) {
        return '<option value="' + v[0] + '">' + v[1] + '</option>';
      }).join('');
    };
    appEl.innerHTML =
      '<div class="section" style="margin-top:4px">' +
        '<div class="card">' +
          '<h3>监管检查库（多文号 · 关联检索）</h3>' +
          '<div class="dz-toolbar">' +
            '<select id="ck_doc" onchange="loadChecks()" title="按文号筛选" aria-label="按文号筛选" style="max-width:300px">' +
              opts(['全部文号',
                    ['jg24', '金规〔2024〕24号（银行保险数据安全办法）'],
                    ['jg93', '金办发〔2025〕93号（专项行动自查表）'],
                    ['pboc3', '人行令〔2025〕第3号（业务领域数据安全办法）'],
                    ['jf8', '金发〔2026〕8号（AI 安全开发应用指导意见）']]) +
            '</select>' +
            '<select id="ck_domain" onchange="loadChecks()" title="按领域筛选" aria-label="按领域筛选" style="max-width:160px">' +
              opts(['全部领域', ['gov', '治理域'], ['tech', '科技域'], ['cross', '跨域']]) +
            '</select>' +
            '<select id="ck_pri" onchange="loadChecks()" title="按优先级筛选" aria-label="按优先级筛选" style="max-width:170px">' +
              opts(['全部优先级', ['P0', 'P0'], ['P1', 'P1'], ['P2', 'P2']]) +
            '</select>' +
            '<input id="ck_kw" placeholder="搜索关键词" oninput="loadChecks()" title="搜索关键词" aria-label="搜索关键词" style="max-width:220px">' +
            '<button onclick="loadChecks()" title="应用筛选">筛选</button>' +
          '</div>' +
          '<div id="ck_list" style="max-height:56vh;overflow:auto"></div>' +
        '</div>' +
        '<div class="card"><h3>检查项六维详情</h3>' +
          '<div id="ck_detail" class="muted">点击上方检查项查看六维详情。</div>' +
        '</div>' +
      '</div>';
    if (typeof window.loadChecks === 'function') window.loadChecks();
  }

  /* ================= 视图：控制↔法规/标准映射 ================= */
  function renderControlMapping() {
    var all = allControls();
    // framework → [{control, ref, note}]
    var byFw = {};
    all.forEach(function (c) {
      arr(c.standard_mappings).forEach(function (m) {
        (byFw[m.framework] = byFw[m.framework] || []).push({ c: c, ref: m.ref, note: m.note });
      });
    });
    // 总览矩阵行
    var fwRows = Object.keys(byFw).sort(function (a, b) { return byFw[b].length - byFw[a].length; });

    function draw(fw) {
      var matrix = fwRows.map(function (f) {
        var n = byFw[f].length;
        return '<button type="button" class="fw-cell' + (fw === f ? ' on' : '') + '" data-fw="' + f + '">' +
          '<div class="fw-name">' + (FRAMEWORK_LABEL[f] || esc(f)) + '</div>' +
          '<div class="fw-count">' + n + ' 控制</div></button>';
      }).join('');

      var body;
      if (!fw || !byFw[fw]) {
        body = '<div class="empty"><h2>选择一个框架/标准查看</h2><p>上方矩阵按承接控制数排序，点选后列出"该要求 → 由哪些控制承接"。</p></div>';
      } else {
        body = '<h3 class="case-year">' + (FRAMEWORK_LABEL[fw] || esc(fw)) + ' · ' + byFw[fw].length + ' 条承接</h3>' +
          '<div class="tbl-scroll"><table class="map-table"><thead><tr>' +
          '<th style="width:16%">控制编号</th><th>控制</th><th style="width:30%">条款 / 编号</th></tr></thead><tbody>' +
          byFw[fw].map(function (it) {
            return '<tr><td><a href="#/entity/' + encodeURIComponent(it.c.id) + '" class="ctrl-code">' + esc(it.c.code || '') + '</a></td>' +
              '<td><a href="#/entity/' + encodeURIComponent(it.c.id) + '">' + esc(it.c.title) + '</a>' +
              (it.c.family ? '<div class="muted">' + esc(it.c.family) + '</div>' : '') + '</td>' +
              '<td>' + esc(it.ref || '—') + '</td></tr>';
          }).join('') +
          '</tbody></table></div>';
      }
      appEl.innerHTML =
        '<div class="section" style="margin-top:4px"><div class="section-head">' +
        '<h2>控制 ↔ 法规/标准映射</h2><span class="sub">按框架总览，点选查看承接该要求的控制</span></div>' +
        '<div class="fw-grid">' + matrix + '</div>' + body + '</div>';
      appEl.querySelectorAll('[data-fw]').forEach(function (b) {
        b.addEventListener('click', function () { draw(b.getAttribute('data-fw')); });
      });
    }
    draw(null);
  }

  /* ================= 视图：学习路径 ================= */
  function renderPath(level) {
    if (['L1', 'L2', 'L3'].indexOf(level) < 0) return renderNotFound(level);
    var tabs = ['L1', 'L2', 'L3'].map(function (l) {
      var label = { L1: '入门', L2: '进阶', L3: '专家' }[l];
      return '<a class="badge ' + (l === level ? 'b-status-reviewed' : '') +
        '" style="padding:6px 14px;font-size:13px" href="#/path/' + l + '">' + l + ' · ' + label + '</a>';
    }).join('<span style="width:8px;display:inline-block"></span>');
    var guide = KB.entities.find(function (e) {
      return e.type === 'guide' && (e.attrs && e.attrs.audience === level.toLowerCase());
    }) || KB.entities.find(function (e) { return e.type === 'guide' && e.level === level; });

    if (!guide) {
      appEl.innerHTML = '<div class="empty"><h2>暂无 ' + level + ' 学习路径</h2>' +
        '<p>该段位的指南条目尚未编写。</p></div>';
      return;
    }
    var cur = (guide.attrs && guide.attrs.curriculum) || [];
    var steps = cur.map(function (s) {
      var refs = (s.refs || []).map(function (rid) {
        var t = ENT.get(rid);
        if (!t) return '';
        return '<a class="step-ref" href="#/entity/' + encodeURIComponent(rid) + '">' +
          '<div class="sr-t">' + esc(t.title) + ' · ' + typeMeta(t.type).label + '</div>' +
          '<div class="sr-s">' + esc(t.summary) + '</div></a>';
      }).join('');
      return '<div class="tl-item"><div class="tl-date">第 ' + s.step + ' 步</div>' +
        '<div class="tl-axis"><div class="tl-dot"></div></div>' +
        '<div class="tl-body"><a class="tl-title">' + esc(s.title) + '</a>' +
        (s.goal ? '<div class="tl-desc">' + esc(s.goal) + '</div>' : '') +
        (refs ? '<div class="step-refs">' + refs + '</div>' : '') +
        '</div></div>';
    }).join('');

    appEl.innerHTML =
      '<div style="display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap">' + tabs + '</div>' +
      '<div class="path-head"><h1>学习路径 · ' + level + '</h1>' +
      '<p>' + esc(guide.summary) + '</p>' +
      '<span class="dur">建议时长：' + esc(guide.attrs.duration || '—') + '</span></div>' +
      '<div class="timeline">' + steps + '</div>';
  }

  /* ================= 视图：法规时间线 ================= */
  function renderTimeline() {
    var items = KB.entities.filter(function (e) { return e.type === 'law' || e.type === 'standard'; });
    items.sort(function (a, b) {
      return String(b.attrs.issued || b.attrs.effective || '').localeCompare(String(a.attrs.issued || a.attrs.effective || ''));
    });
    var html = items.map(function (e) {
      var a = e.attrs || {};
      var date = a.issued || a.effective || e.updated;
      var meta = [];
      if (a.doc_no) meta.push('文号：' + a.doc_no);
      if (a.std_no) meta.push(a.std_no);
      if (a.validity) meta.push('<span class="badge b-validity-' + esc(a.validity) + '">' + (VALIDITY_LABEL[a.validity] || a.validity) + '</span>');
      if (e.type === 'standard' && a.status_std) meta.push('标准状态：' + a.status_std);
      var extLink = e.official_url
        ? '<a class="ext-link" data-ext-official href="' + esc(e.official_url) + '" target="_blank" rel="noopener noreferrer" title="查看官方原文" aria-label="查看官方原文">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>'
        : '';
      return '<div class="tl-item' + (e.type === 'law' ? ' highlight' : '') + '">' +
        '<div class="tl-date">' + esc(date) + '</div>' +
        '<div class="tl-axis"><div class="tl-dot"></div></div>' +
        '<div class="tl-body">' +
        '<a class="tl-title" href="#/entity/' + encodeURIComponent(e.id) + '">' + esc(e.title) + '</a>' + extLink +
        '<div class="tl-meta">' + typeBadge(e.type) + levelBadge(e.level) + meta.join('<span style="color:var(--text-faint)">|</span>') + '</div>' +
        '<div class="tl-desc">' + esc(e.summary) + '</div>' +
        '</div></div>';
    }).join('');

    appEl.innerHTML =
      '<div class="section" style="margin-top:4px">' +
      (html ? '<div class="timeline">' + html + '</div>'
        : '<div class="empty"><h2>暂无法规/标准</h2></div>') + '</div>';

    // 小外链按钮：新窗口打开官方原文，阻止冒泡（虽父级非链接，仍兜底）
    Array.prototype.forEach.call(appEl.querySelectorAll('[data-ext-official]'), function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        window.open(a.getAttribute('href'), '_blank', 'noopener,noreferrer');
      });
    });
  }

  /* ================= 视图：案例库 ================= */
  function renderCases() {
    var all = KB.entities.filter(function (e) { return e.type === 'case'; });
    // 库内实际出现过的 case_type（空类型/未识别不显示 chip）
    var typeCount = {};
    all.forEach(function (e) {
      var ct = (e.attrs || {}).case_type;
      if (ct && CASE_TYPE_LABEL[ct]) typeCount[ct] = (typeCount[ct] || 0) + 1;
    });
    var types = Object.keys(typeCount).sort(function (a, b) { return typeCount[b] - typeCount[a]; });

    function yearOf(e) {
      return ((e.attrs || {}).event_date || '').slice(0, 4) || '未知年份';
    }
    function yearNum(y) { return y === '未知年份' ? -1 : parseInt(y, 10); }

    function draw(filter) {
      filter = filter || 'all';
      var list = all.filter(function (e) {
        return filter === 'all' || (e.attrs || {}).case_type === filter;
      });
      // 按年份倒序分组（未知年份垫底）
      var groups = {};
      list.forEach(function (e) { var y = yearOf(e); (groups[y] = groups[y] || []).push(e); });
      var years = Object.keys(groups).sort(function (a, b) { return yearNum(b) - yearNum(a); });

      var chips = ['<button type="button" class="chip' + (filter === 'all' ? ' on' : '') + '" data-cf="all">全部</button>']
        .concat(types.map(function (t) {
          return '<button type="button" class="chip' + (filter === t ? ' on' : '') + '" data-cf="' + t + '">' +
            CASE_TYPE_LABEL[t] + ' · ' + typeCount[t] + '</button>';
        })).join('');

      var body = list.length
        ? years.map(function (y) {
          return '<h3 class="case-year">' + esc(y) + '</h3>' +
            '<div class="card-grid">' + groups[y].map(cardHtml).join('') + '</div>';
        }).join('')
        : '<div class="empty"><h2>暂无此类案例</h2><p>该筛选下还没有案例。</p></div>';

      appEl.innerHTML =
        '<div class="section" style="margin-top:4px">' +
        '<div class="chip-row">' + chips + '</div>' + body + '</div>';

      appEl.querySelectorAll('[data-cf]').forEach(function (b) {
        b.addEventListener('click', function () { draw(b.getAttribute('data-cf')); });
      });
    }
    draw('all');
  }

  /* ================= 视图：未找到 ================= */
  function renderNotFound(what) {
    appEl.innerHTML = '<div class="empty" style="margin-top:24px">' +
      '<h2>未找到该内容</h2><p>“' + esc(what || '') + '” 不存在或已被移动。</p>' +
      '<p><a class="badge b-type" style="background:var(--brand-50);color:var(--brand-700);padding:8px 16px" href="#/">返回首页</a></p></div>';
  }

  /* ================= 视图：知识图谱（手写 Canvas 力导向 · 多源 · 总览+下钻） ================= */
  function graphSourceLabel(key) {
    var s = GRAPH_SOURCES.filter(function (x) { return x.key === key; })[0];
    return s ? s.label : key;
  }

  /* 切换图谱数据源：停旧引擎 -> 序号自增丢弃在途请求 -> 重渲染（命中缓存即瞬时） */
  function switchGraphSource(key) {
    if (key === GRAPH_SRC || !GRAPH_SOURCES.some(function (s) { return s.key === key; })) return;
    GRAPH_SRC = key;
    stopGraph();
    RENDER_SEQ++;
    renderGraphView();
  }

  function renderGraphView() {
    var seq = RENDER_SEQ;
    appEl.innerHTML = '<div class="graph-loading">正在从「' + esc(graphSourceLabel(GRAPH_SRC)) + '」取数…</div>';
    loadGraph(GRAPH_SRC).then(function (ok) {
      if (seq !== RENDER_SEQ) return;
      if (!ok) {
        appEl.innerHTML = '<div class="empty" style="margin-top:24px"><h2>图谱数据暂不可用</h2>' +
          '<p>数据源「' + esc(graphSourceLabel(GRAPH_SRC)) + '」取数失败，请稍后重试或切换其他来源。</p>' +
          '<p><a class="badge b-type" style="background:var(--brand-50);color:var(--brand-700);padding:8px 16px" href="#/">返回首页</a></p></div>';
        return;
      }
      renderGraphViewNow();
    });
  }

  function renderGraphViewNow() {
    var g = GRAPH_CACHE[GRAPH_SRC];
    if (!g) return;
    var typeCounts = {};
    g.nodes.forEach(function (n) {
      typeCounts[n.type] = (typeCounts[n.type] || 0) + 1;
    });
    // 类型按出现频次降序（用于统计条「类型 N」）
    var types = Object.keys(typeCounts).sort(function (a, b) { return typeCounts[b] - typeCounts[a]; });

    appEl.innerHTML =
      '<div class="graph-toolbar">' +
      '  <div class="gt-group"><span class="gt-lbl">数据源</span><div class="graph-seg" id="graphSeg">' +
      GRAPH_SOURCES.map(function (s) {
        return '<button data-src="' + s.key + '" title="' + esc(s.hint) + '"' +
          (s.key === GRAPH_SRC ? ' class="on"' : '') + '>' + esc(s.label) + '</button>';
      }).join('') + '</div></div>' +
      '  <div class="graph-stats">' +
      '    <span>节点 <b id="gsNodes">' + g.nodes.length + '</b></span>' +
      '    <span>关系 <b id="gsEdges">' + g.edges.length + '</b></span>' +
      '    <span>类型 <b id="gsTypes">' + types.length + '</b></span>' +
      (g.meta.source ? '    <span class="gs-src">' + esc(SOURCE_TEXT[g.meta.source] || '本站装配') + '</span>' : '') +
      '  </div>' +
      '</div>' +
      '<div class="graph-layout" id="graphLayout">' +
      '  <div class="graph-canvas-wrap">' +
      '    <canvas id="graphCanvas"></canvas>' +
      '    <div class="graph-tooltip" id="graphTip"></div>' +
      '    <div class="graph-hint" id="graphHint">总览 · 点击节点下钻查看邻接关系</div>' +
      '  </div>' +
      '  <aside class="graph-panel" id="graphPanel"></aside>' +
      '</div>';

    initGraphEngine(document.getElementById('graphCanvas'), types);
  }

  function initGraphEngine(canvas, types) {
    var ctx = canvas.getContext('2d');
    var wrap = canvas.parentElement;
    var tip = document.getElementById('graphTip');
    var hintEl = document.getElementById('graphHint');
    var layoutEl = document.getElementById('graphLayout');
    var panelEl = document.getElementById('graphPanel');

    // 图谱渲染调参集中处（便于后续微调）
    var CFG = {
      edgeBaseAlpha: 0.09,     // 默认边不透明度（让节点成为主体）
      edgeWidth: 0.8,          // 默认边宽
      edgeHotAlpha: 0.9,       // 悬停高亮边不透明度
      edgeHotWidth: 1.8,
      edgeDimAlpha: 0.03,      // 悬停时非邻边进一步压暗
      focusDimNode: 0.14,      // 下钻时非邻接节点的保留透明度（保持空间语境）
      repulsion: 2600,         // 节点间斥力
      springLength: 118,       // 理想边长
      springK: 0.05,
      gravity: 0.014,          // 整体向心（收敛，防漂移）
      clusterK: 0.03,          // 同类型聚类力（视觉分区）
      hubLabelCount: 16,       // 总览只显示度数 top-N 枢纽标签
      zoomLabelScale: 1.7,     // 放大到该倍率后显示视口内全部标签
      edgeZoomInScale: 1.3,    // 总览(scale<此值)边极淡，超过后随缩放渐显
      // —— 数值稳定性钳制（v1.20.0 修复「图谱不可见」核心 bug）——
      soften: 500,             // 斥力柔性：用 d²+soften 替代 d²，避免近距力趋于无穷
      maxForce: 30,            // 单对节点斥力上限（防止密集区累积爆炸）
      maxSpeed: 16,            // 单步速度上限（px/step）
      maxStep: 8,              // 单步位移上限（px/step）
      maxCoord: 1e5            // 坐标硬边界（NaN/爆炸的最后防线）
    };

    // 随节点/边数自适应的动态参数（build 时按实际规模重算，避免大库变毛球）
    var dyn = { edgeBaseAlpha: CFG.edgeBaseAlpha, repulsion: CFG.repulsion,
                springLength: CFG.springLength, hubLabelCount: CFG.hubLabelCount };

    var state = {
      scale: 1, tx: 0, ty: 0,
      alpha: 1,
      nodes: [], edges: [],
      activeTypes: {}, activeLevels: {},
      dragging: null, panning: null, hover: null, focus: null,
      downX: 0, downY: 0, moved: false,
      w: 0, h: 0
    };
    types.forEach(function (t) { state.activeTypes[t] = true; });
    ['L1', 'L2', 'L3'].forEach(function (l) { state.activeLevels[l] = true; });

    function resize() {
      var r = wrap.getBoundingClientRect();
      var dpr = window.devicePixelRatio || 1;
      state.w = r.width; state.h = r.height;
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // 改 canvas.width 会清空画布；立即重绘，避免尺寸变化瞬间出现空白帧
      if (state.nodes.length) draw();
    }
    resize();
    function worldCenter() {
      return { x: (state.w / 2 - state.tx) / state.scale, y: (state.h / 2 - state.ty) / state.scale };
    }

    function build() {
      // 关闭下钻面板并同步画布尺寸（栅格列数变化会改变画布宽度，先量后算）
      state.focus = null; state.hover = null;
      updatePanel();
      resize();
      var g = GRAPH_CACHE[GRAPH_SRC];
      var srcNodes = (g && g.nodes) || [], srcEdges = (g && g.edges) || [];
      var keep = {};
      srcNodes.forEach(function (n) {
        if (!state.activeTypes[n.type] || !state.activeLevels[n.level]) return;
        keep[n.id] = true;
      });
      var prevById = {};
      state.nodes.forEach(function (p) { prevById[p.id] = p; });
      var list = srcNodes.filter(function (n) { return keep[n.id]; });
      var cx = state.w / 2, cy = state.h / 2;
      // 初始位置：黄金角螺旋铺开（半径 ∝ √i），避免初值近重合导致斥力爆冲；过滤重建时沿用旧坐标
      var spacing = Math.max(14, Math.min(state.w, state.h) * 0.42 / Math.sqrt(Math.max(1, list.length)));
      state.nodes = list.map(function (n, i) {
        var prev = prevById[n.id];
        var r = spacing * Math.sqrt(i + 0.5), ang = i * 2.399963;
        return {
          id: n.id, title: n.title, type: n.type, level: n.level,
          x: prev ? prev.x : cx + Math.cos(ang) * r,
          y: prev ? prev.y : cy + Math.sin(ang) * r,
          vx: 0, vy: 0
        };
      });
      var idx = {}; state.nodes.forEach(function (n, i) { idx[n.id] = i; });
      state.edges = srcEdges.filter(function (e) {
        return idx[e.source] != null && idx[e.target] != null;
      }).map(function (e) { return { s: idx[e.source], t: idx[e.target], label: e.label || e.rel }; });
      // 计算每个节点的度数（用于枢纽标签 LOD）
      state.nodes.forEach(function (p) { p.degree = 0; });
      state.edges.forEach(function (e) { state.nodes[e.s].degree++; state.nodes[e.t].degree++; });
      // 度数 top-N 索引集合（默认总览只给这些节点画标签）
      var sorted = state.nodes.map(function (p, i) { return { i: i, d: p.degree }; })
        .sort(function (a, b) { return b.d - a.d; });

      // —— 按实际规模自适应：大库降边透明度、斥力/边长温和加大、枢纽标签略增但仍疏朗 ——
      var nn = state.nodes.length, ne = state.edges.length;
      // 边透明度：保持"视觉墨水量"大致恒定 → alpha ∝ 1/sqrt(边数)，夹在安全区间
      dyn.edgeBaseAlpha = Math.min(0.09, Math.max(0.022, 2.2 / Math.sqrt(Math.max(1, ne))));
      dyn.repulsion = CFG.repulsion * Math.min(1.2, 0.7 + 0.3 * Math.sqrt(nn / 150));
      dyn.springLength = CFG.springLength * (1 + 0.12 * Math.sqrt(nn / 150));
      dyn.hubLabelCount = Math.min(28, Math.max(12, Math.round(CFG.hubLabelCount * Math.sqrt(nn / 150))));

      state.hubs = {};
      sorted.slice(0, dyn.hubLabelCount).forEach(function (o) { state.hubs[o.i] = true; });
      // 按类型分配环形锚点：同类节点被轻微拉向同一扇区，形成视觉分区
      var usedTypes = {};
      state.nodes.forEach(function (p) { usedTypes[p.type] = true; });
      var tList = Object.keys(usedTypes), wc = worldCenter();
      var R = Math.min(state.w, state.h) * 0.4;
      tList.forEach(function (t, k) {
        var ang = (k / Math.max(1, tList.length)) * Math.PI * 2 - Math.PI / 2;
        var ax = wc.x + Math.cos(ang) * R, ay = wc.y + Math.sin(ang) * R;
        state.nodes.forEach(function (p) { if (p.type === t) { p.ax = ax; p.ay = ay; } });
      });
      state.alpha = 1;
      // 同步预收敛：迭代次数随规模递减（大图步成本高，控制在可感知范围内）
      var iters = nn > 1500 ? 140 : (nn > 600 ? 220 : (nn > 300 ? 300 : 420));
      for (var kk = 0; kk < iters && state.alpha > 0.006; kk++) stepPhysics();
      fitToView();
      syncStats();
    }

    /* 统计条联动：过滤后显示「当前 / 总量」，未过滤时仅显示总量 */
    function syncStats() {
      var g = GRAPH_CACHE[GRAPH_SRC] || { nodes: [], edges: [] };
      var tn = (g.nodes || []).length, te = (g.edges || []).length;
      var cn = state.nodes.length, ce = state.edges.length;
      var tset = {};
      state.nodes.forEach(function (p) { tset[p.type] = true; });
      var nEl = document.getElementById('gsNodes'), eEl = document.getElementById('gsEdges'),
          tEl = document.getElementById('gsTypes');
      if (nEl) nEl.textContent = cn === tn ? String(tn) : cn + ' / ' + tn;
      if (eEl) eEl.textContent = ce === te ? String(te) : ce + ' / ' + te;
      if (tEl) tEl.textContent = String(Object.keys(tset).length);
    }
    build();

    function neighborsOf(i) {
      var set = {}; set[i] = true;
      state.edges.forEach(function (e) {
        if (e.s === i) set[e.t] = true;
        if (e.t === i) set[e.s] = true;
      });
      return set;
    }

    /* 斥力用均匀网格做近邻裁剪（替代全量 O(n²)）：每步只与相邻 3×3 单元格内节点算斥力。
     * 对 3000+ 节点的大图，把每步从 ~5e6 次配对降到 ~1e5 次，避免首屏长时间卡死。
     * 注意：返回网格对象而非写入外层变量——`build()` 在函数声明处即时调用，
     *       外层 var 此时尚未赋值（TDZ/undefined），会造成「图谱不可见」。 */
    function buildGrid() {
      var cs = Math.max(48, dyn.springLength * 1.4);
      var map = new Map();
      for (var i = 0; i < state.nodes.length; i++) {
        var p = state.nodes[i];
        var key = Math.floor(p.x / cs) * 100003 + Math.floor(p.y / cs);
        var arr = map.get(key);
        if (arr) arr.push(i); else map.set(key, [i]);
      }
      return { cs: cs, map: map };
    }
    function stepPhysics() {
      var n = state.nodes, N = n.length;
      if (state.alpha <= 0.006 || !N) return;
      var a = state.alpha;
      // —— 斥力：柔性化 + 单对上限 + 近邻裁剪，杜绝数值爆炸 ——
      var soften = CFG.soften, maxF = CFG.maxForce, kRep = dyn.repulsion * 0.5; // ×0.5：每对在双向各算一次
      var grid = buildGrid();
      var cs = grid.cs, map = grid.map;
      for (var i = 0; i < N; i++) {
        var ni = n[i];
        var gx0 = Math.floor(ni.x / cs), gy0 = Math.floor(ni.y / cs);
        for (var ox = -1; ox <= 1; ox++) {
          for (var oy = -1; oy <= 1; oy++) {
            var cell = map.get((gx0 + ox) * 100003 + (gy0 + oy));
            if (!cell) continue;
            for (var ci = 0; ci < cell.length; ci++) {
              var j = cell[ci];
              if (j === i) continue;
              var nj = n[j];
              var dx = ni.x - nj.x, dy = ni.y - nj.y;
              var d2 = dx * dx + dy * dy;
              var d = Math.sqrt(d2) + 0.01;
              var f = kRep / (d2 + soften);
              if (f > maxF) f = maxF;
              f *= a;
              var ux = dx / d, uy = dy / d;
              ni.vx += ux * f; ni.vy += uy * f;
            }
          }
        }
      }
      // 弹簧（理想边长）
      state.edges.forEach(function (e) {
        var p = n[e.s], q = n[e.t];
        var dx = q.x - p.x, dy = q.y - p.y;
        var d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        var f = (d - dyn.springLength) * CFG.springK * a;
        var ux = dx / d, uy = dy / d;
        p.vx += ux * f; p.vy += uy * f;
        q.vx -= ux * f; q.vy -= uy * f;
      });
      // 同类型聚类：把同类节点轻微拉向其类型环形锚点，形成扇区分区
      for (var c2 = 0; c2 < N; c2++) {
        var pc = n[c2];
        if (pc.ax != null) {
          pc.vx += (pc.ax - pc.x) * CFG.clusterK * a;
          pc.vy += (pc.ay - pc.y) * CFG.clusterK * a;
        }
      }
      // 整体向心 + 阻尼 + 速度/位移钳制 + 越界兜底（v1.20.0 稳定性关键）
      var gx = (state.w / 2 - state.tx) / state.scale;
      var gy = (state.h / 2 - state.ty) / state.scale;
      var damp = 0.82, vmax2 = CFG.maxSpeed * CFG.maxSpeed, mstep = CFG.maxStep, mc = CFG.maxCoord;
      for (var m = 0; m < N; m++) {
        var p2 = n[m];
        p2.vx += (gx - p2.x) * CFG.gravity * a;
        p2.vy += (gy - p2.y) * CFG.gravity * a;
        p2.vx *= damp; p2.vy *= damp;
        var sp2 = p2.vx * p2.vx + p2.vy * p2.vy;
        if (sp2 > vmax2) { var sc = CFG.maxSpeed / Math.sqrt(sp2); p2.vx *= sc; p2.vy *= sc; }
        var sx = p2.vx, sy = p2.vy;
        if (sx > mstep) sx = mstep; else if (sx < -mstep) sx = -mstep;
        if (sy > mstep) sy = mstep; else if (sy < -mstep) sy = -mstep;
        p2.x += sx; p2.y += sy;
        if (!isFinite(p2.x) || !isFinite(p2.y)) { p2.x = gx; p2.y = gy; p2.vx = 0; p2.vy = 0; }
        if (p2.x > mc) p2.x = mc; else if (p2.x < -mc) p2.x = -mc;
        if (p2.y > mc) p2.y = mc; else if (p2.y < -mc) p2.y = -mc;
      }
      state.alpha *= 0.95;
    }

    /* 相机取景：按给定节点集合的包围盒 + 画布尺寸算 scale/translate（含留白与上下限）。
     * 用百分位裁剪包围盒，避免少数游离/孤立节点把取景缩得过小；并做有限性兜底。 */
    function fitToNodes(idxList, pad, maxScale) {
      if (!idxList.length || !state.w || !state.h) return;
      var xs = [], ys = [];
      idxList.forEach(function (i) {
        var p = state.nodes[i];
        if (p && isFinite(p.x) && isFinite(p.y)) { xs.push(p.x); ys.push(p.y); }
      });
      if (!xs.length) return;
      xs.sort(function (a, b) { return a - b; });
      ys.sort(function (a, b) { return a - b; });
      var n = xs.length, lo = Math.floor(n * 0.02), hi = Math.max(lo, Math.ceil(n * 0.98) - 1);
      var minX = xs[lo], maxX = xs[hi], minY = ys[lo], maxY = ys[hi];
      var bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY);
      var availW = Math.max(40, state.w - pad * 2), availH = Math.max(40, state.h - pad * 2);
      var s = Math.min(availW / bw, availH / bh);
      if (!isFinite(s) || s <= 0) s = 1;
      state.scale = Math.min(maxScale, Math.max(0.05, s));
      state.tx = state.w / 2 - ((minX + maxX) / 2) * state.scale;
      state.ty = state.h / 2 - ((minY + maxY) / 2) * state.scale;
    }
    function allIndices() {
      var a = [], i;
      for (i = 0; i < state.nodes.length; i++) a.push(i);
      return a;
    }
    function fitToView() { fitToNodes(allIndices(), 46, 1.2); }
    /* 下钻：聚焦节点 + 其一跳邻居取景（允许适度放大） */
    function fitToFocus(i) {
      fitToNodes(Object.keys(neighborsOf(i)).map(Number), 92, 1.5);
    }

    function tick() {
      stepPhysics();
      draw();
    }

    function screenX(p) { return p.x * state.scale + state.tx; }
    function screenY(p) { return p.y * state.scale + state.ty; }
    function radiusOf(p) { return (LEVEL_RADIUS[p.level] || 10) * Math.min(1.15, Math.max(0.7, state.scale)); }

    function draw() {
      ctx.clearRect(0, 0, state.w, state.h);
      var hoverSet = state.hover != null ? neighborsOf(state.hover) : null;
      var focusSet = state.focus != null ? neighborsOf(state.focus) : null;
      var hiSet = focusSet || hoverSet;    // 当前高亮集合（下钻优先于悬停）
      var hasHi = !!hiSet;
      var zoomed = state.scale >= CFG.zoomLabelScale;

      // 边：默认极淡细线；下钻时聚焦节点的边高亮、其余压暗；悬停时邻边高亮
      // 总览(scale<edgeZoomInScale)下边进一步压到 ~25%，放大后渐显，避免大库灰网压过节点
      var zoomFade = Math.min(1, Math.max(0,
        (state.scale - CFG.edgeZoomInScale) / (CFG.zoomLabelScale - CFG.edgeZoomInScale)));
      var baseA = dyn.edgeBaseAlpha * (0.25 + 0.75 * zoomFade);
      state.edges.forEach(function (e) {
        var a = state.nodes[e.s], b = state.nodes[e.t];
        var onFocus = focusSet && (e.s === state.focus || e.t === state.focus);
        var near = hasHi && hiSet[e.s] && hiSet[e.t];
        ctx.strokeStyle = onFocus
          ? 'rgba(27,79,228,' + CFG.edgeHotAlpha + ')'
          : (near ? 'rgba(27,79,228,0.30)'
                  : (hasHi ? 'rgba(102,112,133,' + CFG.edgeDimAlpha + ')'
                           : 'rgba(102,112,133,' + baseA + ')'));
        ctx.lineWidth = onFocus ? CFG.edgeHotWidth : CFG.edgeWidth;
        ctx.beginPath();
        ctx.moveTo(screenX(a), screenY(a));
        ctx.lineTo(screenX(b), screenY(b));
        ctx.stroke();
      });

      // 标签是否该画：
      //  - 下钻：聚焦节点 + 一跳邻居；悬停：hovered + 一度邻居
      //  - 未放大总览：只画度数 top-N 枢纽
      //  - 放大到 zoomLabelScale：画视口内全部节点
      function shouldLabel(i, p, sx, sy) {
        if (focusSet) return !!focusSet[i];
        if (hoverSet) return !!hoverSet[i];
        if (zoomed) return sx > -60 && sx < state.w + 60 && sy > -30 && sy < state.h + 30;
        return !!state.hubs[i];
      }

      // 节点圆
      state.nodes.forEach(function (p, i) {
        var sx = screenX(p), sy = screenY(p), r = radiusOf(p);
        var dim = hasHi && !hiSet[i];
        ctx.globalAlpha = dim ? (focusSet ? CFG.focusDimNode : 0.22) : 1;
        ctx.beginPath();
        ctx.arc(sx, sy, i === state.focus ? r + 2 : r, 0, Math.PI * 2);
        ctx.fillStyle = typeMeta(p.type).color;
        ctx.fill();
        ctx.lineWidth = i === state.focus ? 3 : 2;
        ctx.strokeStyle = i === state.focus ? '#1B4FE4' : '#fff';
        ctx.stroke();
        ctx.globalAlpha = 1;
      });

      // 标签（独立一遍绘制；总览时按度数排序后做屏幕距离去重，避免叠字）
      var drawn = [];
      var order = state.nodes.map(function (p, i) { return { i: i, p: p, deg: p.degree || 0 }; })
        .sort(function (a, b) { return b.deg - a.deg; });
      order.forEach(function (o) {
        var i = o.i, p = o.p;
        var sx = screenX(p), sy = screenY(p), r = radiusOf(p);
        if (!shouldLabel(i, p, sx, sy)) return;
        var ly = sy + r + 14;
        // 总览非放大时：跳过与已画标签屏幕距离过近者
        if (!zoomed && !hoverSet && !focusSet) {
          var tooClose = drawn.some(function (d) {
            var dx = d.x - sx, dy = d.y - ly; return dx * dx + dy * dy < 56 * 56;
          });
          if (tooClose) return;
        }
        var strong = i === state.focus || (state.hubs[i] && !zoomed);
        ctx.font = (strong ? '600 ' : '') + '12px -apple-system, "PingFang SC", sans-serif';
        ctx.fillStyle = hasHi && !hiSet[i] ? '#98A2B3' : '#1D2939';
        ctx.textAlign = 'center';
        ctx.fillText(p.title, sx, ly);
        drawn.push({ x: sx, y: ly });
      });
    }

    function toWorld(px, py) {
      return { x: (px - state.tx) / state.scale, y: (py - state.ty) / state.scale };
    }
    function hitNode(px, py) {
      var w = toWorld(px, py);
      for (var i = state.nodes.length - 1; i >= 0; i--) {
        var p = state.nodes[i];
        var dx = p.x - w.x, dy = p.y - w.y;
        if (dx * dx + dy * dy < (radiusOf(p) / state.scale + 4) * (radiusOf(p) / state.scale + 4)) return i;
      }
      return -1;
    }

    /* ---------------- 总览 / 下钻 交互 ---------------- */
    function setFocus(i) {
      if (i != null && (i < 0 || i >= state.nodes.length)) i = null;
      state.focus = i;
      if (hintEl) {
        hintEl.textContent = i == null
          ? '总览 · 点击节点下钻查看邻接关系'
          : '聚焦「' + state.nodes[i].title + '」 · 点击空白或 Esc 返回总览';
      }
      updatePanel();
      if (i != null) fitToFocus(i); else fitToView();
    }
    function openEntity(i) {
      var p = state.nodes[i];
      if (p && ENT.get(p.id)) location.hash = '#/entity/' + encodeURIComponent(p.id);
    }
    /* 右侧详情面板：节点信息 + 关联关系清单（点击某条关系即聚焦到该邻居） */
    function updatePanel() {
      if (!layoutEl || !panelEl) return;
      if (state.focus == null) {
        layoutEl.classList.remove('has-panel');
        panelEl.innerHTML = '';
        return;
      }
      var i = state.focus, p = state.nodes[i];
      var rels = [];
      state.edges.forEach(function (e) {
        if (e.s === i) rels.push({ other: e.t, rel: e.label || '关联', out: true });
        else if (e.t === i) rels.push({ other: e.s, rel: e.label || '关联', out: false });
      });
      rels.sort(function (a, b) {
        return (state.nodes[b.other].degree || 0) - (state.nodes[a.other].degree || 0);
      });
      var MAX = 60;
      var hasEntity = !!ENT.get(p.id);
      panelEl.innerHTML =
        '<div class="gp-head"><h3 class="gp-title">' + esc(p.title) + '</h3>' +
        '<button class="gp-close" id="gpClose" title="返回总览">×</button></div>' +
        '<div class="gp-meta">' + typeBadge(p.type) + levelBadge(p.level) + '</div>' +
        '<div class="gp-metrics">' +
        '  <div class="gp-metric"><div class="m-v">' + (p.degree || 0) + '</div><div class="m-k">连接关系</div></div>' +
        '  <div class="gp-metric"><div class="m-v">' + rels.length + '</div><div class="m-k">关联实体</div></div>' +
        '</div>' +
        '<div class="gp-rel-h">关联关系（' + rels.length + '）</div>' +
        (rels.length
          ? rels.slice(0, MAX).map(function (r) {
              var q = state.nodes[r.other];
              return '<button class="gp-rel" data-goto="' + r.other + '">' +
                '<span class="r-rel">' + esc(relLabel(r.rel)) + (r.out ? ' →' : ' ←') + '</span>' +
                '<span class="r-t">' + esc(q ? q.title : '') + '</span></button>';
            }).join('') + (rels.length > MAX ? '<div class="gc-empty">仅显示前 ' + MAX + ' 条</div>' : '')
          : '<div class="gc-empty">该实体暂无关联关系</div>') +
        '<div class="gp-actions">' +
        '  <button class="gp-btn" id="gpCenter">居中显示</button>' +
        (hasEntity ? '<a class="gp-btn primary" href="#/entity/' + encodeURIComponent(p.id) + '">查看详情</a>' : '') +
        '</div>';
      layoutEl.classList.add('has-panel');
    }

    canvas.addEventListener('mousedown', function (ev) {
      var r = canvas.getBoundingClientRect();
      var px = ev.clientX - r.left, py = ev.clientY - r.top;
      var i = hitNode(px, py);
      state.moved = false;
      state.downX = px; state.downY = py;
      if (i >= 0) { state.dragging = i; }
      else { state.panning = { x: px - state.tx, y: py - state.ty }; canvas.classList.add('dragging'); }
    });
    canvas.addEventListener('dblclick', function (ev) {
      var r = canvas.getBoundingClientRect();
      var i = hitNode(ev.clientX - r.left, ev.clientY - r.top);
      if (i >= 0) openEntity(i);
    });
    function onMove(ev) {
      if (!document.body.contains(canvas)) return;
      var r = canvas.getBoundingClientRect();
      var px = ev.clientX - r.left, py = ev.clientY - r.top;
      if (Math.abs(px - state.downX) + Math.abs(py - state.downY) > 4) state.moved = true;
      if (state.dragging != null) {
        var w = toWorld(px, py);
        state.nodes[state.dragging].x = w.x;
        state.nodes[state.dragging].y = w.y;
        state.nodes[state.dragging].vx = 0; state.nodes[state.dragging].vy = 0;
        tip.classList.remove('show');
      } else if (state.panning) {
        state.tx = px - state.panning.x;
        state.ty = py - state.panning.y;
        tip.classList.remove('show');
      } else {
        var i = hitNode(px, py);
        state.hover = i >= 0 ? i : null;
        if (i >= 0) {
          var p = state.nodes[i];
          tip.innerHTML = '<div class="gt-t">' + esc(p.title) + '</div>' +
            '<div class="gt-s">' + typeMeta(p.type).label + ' · ' + p.level + ' · 点击下钻</div>';
          tip.style.left = (px + 14) + 'px';
          tip.style.top = (py + 10) + 'px';
          tip.classList.add('show');
          canvas.style.cursor = 'pointer';
        } else {
          tip.classList.remove('show');
          canvas.style.cursor = 'grab';
        }
      }
    }
    function onUp() {
      if (!document.body.contains(canvas)) return;
      if (state.dragging != null && !state.moved) {
        setFocus(state.dragging);               // 点击节点 -> 下钻
      } else if (state.panning && !state.moved && state.focus != null) {
        setFocus(null);                          // 点击空白 -> 返回总览
      }
      state.dragging = null; state.panning = null;
      canvas.classList.remove('dragging');
    }
    function onKey(ev) { if (ev.key === 'Escape' && state.focus != null) setFocus(null); }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('keydown', onKey);

    canvas.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var r = canvas.getBoundingClientRect();
      var px = ev.clientX - r.left, py = ev.clientY - r.top;
      var factor = ev.deltaY < 0 ? 1.12 : 0.89;
      var ns = Math.min(2.5, Math.max(0.35, state.scale * factor));
      var w = toWorld(px, py);
      state.scale = ns;
      state.tx = px - w.x * ns;
      state.ty = py - w.y * ns;
    }, { passive: false });

    // 数据源切换
    var segEl = document.getElementById('graphSeg');
    if (segEl) segEl.addEventListener('click', function (ev) {
      var b = ev.target.closest && ev.target.closest('button[data-src]');
      if (b) switchGraphSource(b.getAttribute('data-src'));
    });
    // 详情面板：关闭 / 居中 / 跳转邻居
    if (panelEl) panelEl.addEventListener('click', function (ev) {
      var t = ev.target;
      if (!t.closest) return;
      if (t.closest('#gpClose')) { setFocus(null); return; }
      if (t.closest('#gpCenter')) { if (state.focus != null) fitToFocus(state.focus); return; }
      var rel = t.closest('[data-goto]');
      if (rel) setFocus(parseInt(rel.getAttribute('data-goto'), 10));
    });

    function loop() {
      tick();
      graphRaf = requestAnimationFrame(loop);
    }
    loop();

    var rs = new ResizeObserver(function () { resize(); });
    rs.observe(wrap);
    graphCleanup = function () {
      rs.disconnect();
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('keydown', onKey);
      tip && tip.classList.remove('show');
      if (layoutEl) layoutEl.classList.remove('has-panel');
    };
  }

    /* ---------------- 启动 ---------------- */
    if (!_wired) { window.addEventListener('hashchange', render); _wired = true; }
    if (!location.hash) location.hash = '#/';
    render();
  }

  return { init: init };
})();
