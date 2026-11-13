/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   逐类问题处置（九类检查发现典型问题 × 失效层 × 管理策略 × 技术防护策略）
   · demo_issues.js
   视图 id：issues   容器：#issues_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/issues/classes（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { classes: '/api/issues/classes' };
  var MGMT_KEYS = ['制度', '培训', '流程规范', '审计检查'];

  var S = { data: null, sel: null, layer: 'all' };

  function rootEl() { return document.getElementById('issues_root'); }

  function layerFilter() {
    var layers = (S.data && S.data.summary && S.data.summary.layers) || {};
    return Object.keys(layers);
  }
  function classes() {
    var all = (S.data && S.data.classes) || [];
    if (S.layer === 'all') return all;
    return all.filter(function (c) { return c.layer === S.layer; });
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<label class="muted" for="issues_layer" style="margin:0">失效层</label>' +
        '<select id="issues_layer" title="按失效层筛选" aria-label="按失效层筛选"></select>' +
        '<button class="ghost" id="issues_refresh" title="重新拉取问题清单" aria-label="刷新问题清单">刷新</button>' +
        '<span class="muted">每一类已识别的问题同时落到管理策略与技术防护策略，两组统一收口到「证据与验收」。</span>' +
      '</div>' +
      '<div id="issues_split">' + DZ.skeleton(5) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var sel = document.getElementById('issues_layer');
    if (sel) sel.onchange = function () { S.layer = this.value; renderSplit(); };
    var btn = document.getElementById('issues_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderLayerOptions() {
    var sel = document.getElementById('issues_layer');
    if (!sel) return;
    var layers = layerFilter();
    sel.innerHTML = '<option value="all">全部</option>' +
      layers.map(function (l) {
        return '<option value="' + DZ.esc(l) + '"' + (l === S.layer ? ' selected' : '') + '>' + DZ.esc(l) + '</option>';
      }).join('');
  }

  function renderSplit() {
    var box = document.getElementById('issues_split');
    if (!box) return;
    var list = classes();
    if (!list.length) { box.innerHTML = DZ.empty('当前筛选条件下暂无问题类别'); return; }
    if (!S.sel || !list.some(function (c) { return c.no === S.sel; })) {
      S.sel = list[0].no;
    }
    box.innerHTML = '<div class="dz-split">' +
      '<div class="dz-side"><div class="card"><h3>问题类别（' + list.length + '）</h3>' +
        '<div id="issues_list"></div></div></div>' +
      '<div class="dz-main" id="issues_detail"></div>' +
    '</div>';
    renderList(list);
    renderDetail();
  }

  function renderList(list) {
    var box = document.getElementById('issues_list');
    if (!box) return;
    box.innerHTML = '<div class="pick-list" style="grid-template-columns:1fr">' +
      list.map(function (c) {
        var on = c.no === S.sel;
        var style = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
        return '<div class="pick" data-no="' + DZ.esc(c.no) + '" role="button" tabindex="0"' + style +
          ' aria-label="查看问题类别 ' + DZ.esc(c.name) + '" title="查看该类处置策略">' +
          '<div style="min-width:0;flex:1">' +
            '<div class="pick-name" style="font-weight:600">' + DZ.esc(c.no) + ' ' + DZ.esc(c.name) + '</div>' +
            '<div class="row" style="gap:6px;margin-top:6px">' + DZ.pill(c.layer) + '</div>' +
          '</div>' +
        '</div>';
      }).join('') + '</div>';
    box.querySelectorAll('.pick').forEach(function (el) {
      var open = function () { S.sel = el.dataset.no; renderList(list); renderDetail(); };
      el.onclick = open;
      el.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
    });
  }

  function renderDetail() {
    var main = document.getElementById('issues_detail');
    if (!main) return;
    var c = ((S.data && S.data.classes) || []).filter(function (x) { return x.no === S.sel; })[0];
    if (!c) { main.innerHTML = DZ.empty('请选择左侧问题类别查看处置策略'); return; }

    var mgmtRows = MGMT_KEYS.map(function (k) {
      var v = (c.mgmt || {})[k] || '—';
      return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
        '<span class="dz-metric-v" style="font-weight:400;text-align:right;max-width:70%">' + DZ.esc(v) + '</span></div>';
    }).join('');

    var techPills = (c.tech || []).length
      ? c.tech.map(function (t) { return DZ.pill(t); }).join(' ')
      : '<span class="muted">—</span>';

    var evList = (c.evidence || []).length
      ? '<ul style="margin:4px 0 0 18px">' + c.evidence.map(function (e) { return '<li>' + DZ.esc(e) + '</li>'; }).join('') + '</ul>'
      : '<div class="muted">—</div>';

    main.innerHTML = '<div class="card">' +
      '<h3>' + DZ.esc(c.no) + ' ' + DZ.esc(c.name) + ' ' + DZ.pill('失效层 · ' + c.layer) + '</h3>' +
      '<h4>管理策略（制度 / 培训 / 流程规范 / 审计检查）</h4>' + mgmtRows +
      '<h4>技术防护策略</h4><div class="row" style="gap:6px">' + techPills + '</div>' +
      '<h4>证据与验收</h4>' +
        '<div class="why">' +
          '<div><b>验收判据：</b>' + DZ.esc(c.accept || '—') + '</div>' +
          '<div style="margin-top:6px"><b>应留证据：</b></div>' + evList +
        '</div>' +
    '</div>';
  }

  async function load(force) {
    if (S.data && !force) { renderLayerOptions(); renderSplit(); return; }
    S.data = null;
    var box = document.getElementById('issues_split');
    if (box) box.innerHTML = DZ.skeleton(5);
    var res = await DZ.get(API.classes);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '问题清单加载失败';
      box = document.getElementById('issues_split');
      if (box) box.innerHTML = DZ.banner('bad', msg, function () { load(true); });
      return;
    }
    S.data = res;
    renderLayerOptions();
    renderSplit();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['issues'] = mount;
})();
