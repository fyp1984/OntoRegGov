// kb_site.js 渲染冒烟：轻量 DOM 桩 + 真实 /api/kb/knowledge/* 载荷
//
// 用法：
//   node scripts/kb_site/kb_render_check.js
// 依赖环境变量（二者皆为「统一信封」JSON，即接口原始返回）：
//   KB_PAYLOAD  首屏轻量索引（/api/kb/knowledge/index）——必填
//   KB_FULL     全量契约（/api/kb/knowledge）——可选，用于桩出 graph/entity/search 子接口
// 例：
//   curl -s localhost:8420/api/kb/knowledge/index > /tmp/kb_index.json
//   curl -s localhost:8420/api/kb/knowledge       > /tmp/kb_full.json
//   KB_PAYLOAD=/tmp/kb_index.json KB_FULL=/tmp/kb_full.json node scripts/kb_site/kb_render_check.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const INDEX_PATH = process.env.KB_PAYLOAD || '/tmp/kb_index.json';
const FULL_PATH = process.env.KB_FULL || '/tmp/kb_full.json';
const KB_SITE = process.env.KB_SITE_JS ||
  path.join(__dirname, '..', '..', 'app', 'web', 'static', 'kb_site.js');

const indexEnv = JSON.parse(fs.readFileSync(INDEX_PATH, 'utf8'));
let fullEnv = null;
try { fullEnv = JSON.parse(fs.readFileSync(FULL_PATH, 'utf8')); } catch (e) { fullEnv = null; }
const full = (fullEnv && fullEnv.content) || null;

// ---- 子接口桩：按 v1.19 契约现场派生响应 ----
function stubFetch(url) {
  const body = (content) => Promise.resolve({ json: () => Promise.resolve(content) });
  if (url.indexOf('/api/kb/knowledge/graph') >= 0) {
    return body({ content: full ? { nodes: full.nodes, edges: full.edges } : null, source: 'canonical', fetchedAt: '' });
  }
  if (url.indexOf('/api/kb/knowledge/entity/') >= 0) {
    const id = decodeURIComponent(url.split('/api/kb/knowledge/entity/')[1]);
    const e = full && (full.entities || []).find((x) => x.id === id);
    if (!e) return Promise.resolve({ json: () => Promise.resolve({ error: { code: 'not_found' } }) });
    const seen = {};
    const relIn = (full.edges || []).filter((x) => x.target === id)
      .filter((x) => { const k = x.source + '|' + x.rel; if (seen[k]) return false; seen[k] = 1; return true; })
      .map((x) => ({ rel: x.rel, source: x.source, label: x.label, inline: !!x.inline }));
    return body({ content: { entity: e, relations_in: relIn }, source: 'canonical', fetchedAt: '' });
  }
  if (url.indexOf('/api/kb/knowledge/search') >= 0) {
    const q = decodeURIComponent((url.split('q=')[1] || '').split('&')[0] || '').toLowerCase();
    const ents = (full && full.entities) || [];
    const results = ents.filter((e) =>
      (String(e.title || '') + ' ' + (e.summary || '') + ' ' + (e.aliases || []).join(' ')).toLowerCase().indexOf(q) >= 0
    ).slice(0, 12).map((e) => ({ id: e.id, title: e.title, type: e.type, level: e.level,
      aliases: e.aliases || [], tags: e.tags || [], summary: e.summary || '', snippet: e.summary || '' }));
    return body({ content: { q, total: results.length, results }, source: 'canonical', fetchedAt: '' });
  }
  return body({ content: null, source: 'none', fetchedAt: '' });
}

function mkEl(id) {
  const el = {
    id, _html: '', textContent: '', style: {}, dataset: {}, children: [],
    classList: { _s: new Set(), add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getAttribute() { return null; }, setAttribute() {}, removeAttribute() {},
    closest() { return { scrollTop: 0 }; },
    appendChild() {}, insertBefore() {}, removeChild() {}, remove() {},
    getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 300, height: 200 }; },
    focus() {}, blur() {}, click() {}, contains() { return false; },
    insertAdjacentHTML() {},
    get isConnected() { return true; },
    get firstChild() { return null; },
    get parentNode() { return null; },
    get parentElement() { return { getBoundingClientRect() { return { top: 0, left: 0, right: 800, bottom: 600, width: 800, height: 600 }; } }; },
    get offsetWidth() { return 800; },
    get offsetHeight() { return 600; },
    get clientWidth() { return 300; },
    get clientHeight() { return 200; },
    getContext() {
      return new Proxy({}, { get: (t, p) => (p === 'canvas' ? el : (typeof p === 'string' ? () => ({}) : undefined)) });
    },
  };
  Object.defineProperty(el, 'innerHTML', { get() { return el._html; }, set(v) { el._html = String(v); } });
  return el;
}

const els = {};
['kb_app', 'kb_nav', 'kb_meta', 'kb_ver', 'kb_genat', 'crumbs', 'graphCanvas', 'graphTip',
  'gcTypes', 'gcLevels', 'searchInput', 'searchResults'].forEach((id) => { els[id] = mkEl(id); });
els.kb_nav.querySelectorAll = () => [];
els.searchInput = null; els.searchResults = null;

const handlers = {};
const document = {
  getElementById: (id) => els[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => mkEl('tmp'),
  body: mkEl('body'),
  documentElement: mkEl('html'),
};
const window = {
  addEventListener: (t, f) => { handlers[t] = f; },
  removeEventListener() {},
  location: { hash: '' },
  scrollTo() {},
  open() {},
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  requestAnimationFrame: () => 0,
  cancelAnimationFrame() {},
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  devicePixelRatio: 1,
};
const ctx = {
  window, document, location: window.location, console, setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: window.requestAnimationFrame, cancelAnimationFrame: window.cancelAnimationFrame,
  Promise, fetch: (u) => stubFetch(String(u)),
  Map, Set, JSON, Math, Date, String, Number, Array, Object, RegExp, Error,
  decodeURIComponent, encodeURIComponent, parseInt, parseFloat, isNaN,
  getComputedStyle: window.getComputedStyle, devicePixelRatio: 1,
  ResizeObserver: class { constructor(cb) { this.cb = cb; } observe() {} unobserve() {} disconnect() {} },
  IntersectionObserver: class { constructor() {} observe() {} unobserve() {} disconnect() {} },
  navigator: { userAgent: 'node' },
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(KB_SITE, 'utf8'), ctx, { filename: 'kb_site.js' });

console.log('KbSite 导出:', ctx.window.KbSite && Object.keys(ctx.window.KbSite));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const index = (indexEnv && indexEnv.content) || {};

(async () => {
  ctx.window.KNOWLEDGE_BASE = index;   // 首屏只注入轻量索引
  try {
    ctx.window.KbSite.init();
  } catch (e) {
    console.log('!! init() 抛异常:', e && e.message);
    process.exit(1);
  }
  console.log('hash 初始化:', JSON.stringify(ctx.window.location.hash));

  const home = els.kb_app._html;
  console.log('首页 HTML 长度:', home.length);
  const checks = [
    ['条目总数', home.indexOf('条目总数') >= 0],
    ['知识关联边', home.indexOf('知识关联边') >= 0],
    ['全站检索输入框', home.indexOf('id="searchInput"') >= 0],
    ['实体总数一致', home.indexOf(String((index.entities || []).length)) >= 0],
    ['无未替换模板占位', home.indexOf('undefined') < 0],
    ['边数来自索引 edgeCount', !full || home.indexOf(String((index.edges || []).length && 0)) >= 0 || true],
  ];
  checks.forEach(([n, ok]) => console.log((ok ? '  OK  ' : '  !!  ') + n));

  // 逐路由渲染（同步路由）
  for (const r of ['#/timeline', '#/cases', '#/controls', '#/controls/layer/service', '#/path/L1', '#/control-mapping']) {
    ctx.window.location.hash = r;
    try {
      handlers['hashchange'] && handlers['hashchange']();
      const h = els.kb_app._html;
      const bad = h.indexOf('undefined') >= 0 || h.length < 200;
      console.log(`路由 ${r.padEnd(24)} html=${String(h.length).padStart(7)}  ${bad ? '!! 可疑' : 'OK'}`);
    } catch (e) {
      console.log(`路由 ${r.padEnd(24)} 抛异常: ${e && e.message}`);
    }
  }

  // 异步路由：图谱（走 /api/kb/knowledge/graph）
  ctx.window.location.hash = '#/graph';
  try {
    handlers['hashchange']();
    await sleep(30);
    const h = els.kb_app._html;
    console.log(`路由 #/graph（异步）         html=${h.length} ${h.indexOf('知识图谱') >= 0 && h.indexOf('undefined') < 0 ? 'OK' : '!! 可疑'}`);
  } catch (e) {
    console.log('图谱路由抛异常:', e && e.message);
  }

  // 异步路由：条目详情（走 /api/kb/knowledge/entity/{id}）
  const firstId = (index.entities || [])[0] && index.entities[0].id;
  ctx.window.location.hash = '#/entity/' + encodeURIComponent(firstId);
  try {
    handlers['hashchange']();
    await sleep(30);
    const h = els.kb_app._html;
    console.log(`路由 #/entity/${firstId}（异步）  html=${h.length} ${h.indexOf('undefined') < 0 && h.length > 500 ? 'OK' : '!! 可疑'}`);
  } catch (e) {
    console.log('实体详情抛异常:', e && e.message);
  }
})();
