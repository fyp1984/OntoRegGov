/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   留存资产（四类：台账 / 自查报告 / 方法与模板 / 已确认结果）
   · demo_assets.js
   视图 id：assets   容器：#assets_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/assets（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { assets: '/api/assets' };

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('assets_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="assets_refresh" title="重新拉取留存资产数据" aria-label="刷新留存资产">刷新</button>' +
        '<span class="muted">资产随轮次积累：上一轮留下的结论，是下一轮的起点与对照基准。</span>' +
      '</div>' +
      '<div id="assets_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>资产积累</h3><div id="assets_flow">' + DZ.skeleton(1) + '</div></div>' +
      '<div id="assets_cards">' + DZ.skeleton(4) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('assets_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(summary) {
    DZ.render('#assets_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('资产类别', DZ.number(summary && summary.total), '逐轮积累', '') +
      DZ.kpi('使用方式', '上一轮留给下一轮', '作为对照基准与切入点', '') +
    '</div>');
  }

  function renderFlow(items) {
    var box = document.getElementById('assets_flow');
    if (!box) return;
    if (!items.length) { box.innerHTML = DZ.empty('暂无资产'); return; }
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="留存资产">' +
      items.map(function (a, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="' + DZ.esc(a.name) + '">' +
            '<div class="dz-node-title">' + DZ.esc(a.name) + '</div>' +
            '<div class="dz-mini">' + DZ.esc(a.stage) + '</div>' +
          '</div>';
      }).join('') + '</div>' +
      '<div class="muted">四类资产逐轮沉淀，让新主题、新条线不必从零设计。</div>';
  }

  function renderCards(items) {
    var box = document.getElementById('assets_cards');
    if (!box) return;
    if (!items.length) { box.innerHTML = DZ.empty('暂无资产'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px">' +
      items.map(function (a) {
        return '<div class="card">' +
          '<h3>' + DZ.esc((a.no ? a.no + '、' : '') + a.name) + '</h3>' +
          '<div class="muted" style="margin:4px 0 8px">' + DZ.esc(a.intro || '') + '</div>' +
          '<div class="dz-metric">' +
            '<span class="dz-metric-k">由哪一轮留下</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(a.stage || '—') + '</span>' +
          '</div>' +
          '<div class="dz-metric">' +
            '<span class="dz-metric-k">下一轮怎么用</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(a.use || '—') + '</span>' +
          '</div>' +
        '</div>';
      }).join('') + '</div>';
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.summary);
      renderFlow(S.data.assets || []);
      renderCards(S.data.assets || []);
      return;
    }
    S.data = null;
    var box = document.getElementById('assets_cards');
    if (box) box.innerHTML = DZ.skeleton(4);
    var res = await DZ.get(API.assets);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '留存资产数据加载失败';
      DZ.render('#assets_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#assets_flow', DZ.empty('留存资产数据不可读'));
      DZ.render('#assets_cards', DZ.empty('留存资产数据不可读'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderFlow(Array.isArray(res.assets) ? res.assets : []);
    renderCards(Array.isArray(res.assets) ? res.assets : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['assets'] = mount;
})();
