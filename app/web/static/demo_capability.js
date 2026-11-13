/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   能力域目录（十四能力域：按工作环节编排，逐项对应检查主题与交付物）
   · demo_capability.js
   视图 id：capability   容器：#capability_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/capabilities（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { capabilities: '/api/capabilities' };

  // 状态徽章（文字与颜色并存，不只靠颜色）
  function statusBadge(st) {
    if (st === 'ready') return DZ.badge('ok', '已有实例');
    return DZ.badge('unk', '待接入');
  }

  // 检查主题编号 / 说明 → 标签
  function checkTags(checks) {
    var list = Array.isArray(checks) ? checks : [];
    if (!list.length) return '<span class="muted">—</span>';
    return list.map(function (c) { return DZ.pill(c); }).join(' ');
  }

  // 已接入插件实例 → 软标签
  function instanceTags(instances) {
    var list = Array.isArray(instances) ? instances : [];
    if (!list.length) return '<span class="muted">暂无已接入插件，待接入。</span>';
    return list.map(function (n) { return '<span class="dz-tag-soft">' + DZ.esc(n) + '</span>'; }).join(' ');
  }

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('capability_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="capability_refresh" title="重新拉取能力域目录" aria-label="刷新能力域目录">刷新</button>' +
        '<span class="muted">按工作环节编排的能力域目录：逐项对应检查主题与接入后的交付物。</span>' +
      '</div>' +
      '<div id="capability_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="capability_cards">' + DZ.skeleton(6) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('capability_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(summary) {
    DZ.render('#capability_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('能力域总数', DZ.number(summary && summary.total), '按工作环节编排', '') +
      DZ.kpi('已有实例', DZ.number(summary && summary.ready), '已接入插件实例', 'ok') +
      DZ.kpi('待接入', DZ.number(summary && summary.planned), '尚无插件实例', 'warn') +
    '</div>');
  }

  function renderCards(items) {
    var box = document.getElementById('capability_cards');
    if (!box) return;
    if (!items.length) { box.innerHTML = DZ.empty('暂无能力域'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px">' +
      items.map(function (d) {
        return '<div class="card">' +
          '<h3>能力域 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + ' ' + statusBadge(d.status) + '</h3>' +
          '<div class="dz-cite"><div>' + DZ.esc(d.usage || '—') + '</div></div>' +
          '<div class="dz-metric"><span class="dz-metric-k">对应检查主题</span>' +
            '<span class="dz-metric-v" style="text-align:right">' + checkTags(d.checks) + '</span></div>' +
          '<div class="dz-metric"><span class="dz-metric-k">接入后交付物</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(d.deliverable || '—') + '</span></div>' +
          '<h4>已接入插件实例</h4>' +
          '<div style="display:flex;gap:8px;flex-wrap:wrap">' + instanceTags(d.instances) + '</div>' +
        '</div>';
      }).join('') + '</div>';
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.summary);
      renderCards(Array.isArray(S.data.capabilities) ? S.data.capabilities : []);
      return;
    }
    S.data = null;
    var box = document.getElementById('capability_cards');
    if (box) box.innerHTML = DZ.skeleton(6);
    var res = await DZ.get(API.capabilities);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '能力域目录加载失败';
      DZ.render('#capability_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#capability_cards', DZ.empty('能力域目录不可读'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderCards(Array.isArray(res.capabilities) ? res.capabilities : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['capability'] = mount;
})();
