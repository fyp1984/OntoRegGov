/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   平台架构（知识底座五层：知识层 / 编排层 / 接入层 / 能力层 / 证据层）
   · demo_arch.js
   视图 id：arch   容器：#arch_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/architecture/layers（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { layers: '/api/architecture/layers' };

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('arch_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="arch_refresh" title="重新拉取平台架构数据" aria-label="刷新平台架构">刷新</button>' +
        '<span class="muted">自上而下：知识层供依据，编排层管作业，接入层给入口，能力层出结果，证据层留痕迹。</span>' +
      '</div>' +
      '<div id="arch_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="arch_layers">' + DZ.skeleton(5) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('arch_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(layers) {
    var mods = layers.reduce(function (n, L) { return n + ((L.modules || []).length); }, 0);
    DZ.render('#arch_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('架构层', DZ.number(layers.length), '自上而下分层', '') +
      DZ.kpi('能力模块', DZ.number(mods), '各层可复用模块', '') +
    '</div>');
  }

  function renderLayers(layers) {
    var box = document.getElementById('arch_layers');
    if (!box) return;
    if (!layers.length) { box.innerHTML = DZ.empty('暂无架构层'); return; }
    box.innerHTML = layers.map(function (L) {
      var mods = (L.modules || []).map(function (m) {
        return '<span class="dz-tag-soft">' + DZ.esc(m) + '</span>';
      }).join(' ');
      return '<div class="card">' +
        '<h3>第 ' + DZ.esc(L.no) + ' 层 · ' + DZ.esc(L.name) + '</h3>' +
        '<div class="dz-cite"><div>' + DZ.esc(L.desc || '—') + '</div></div>' +
        '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">' + mods + '</div>' +
      '</div>';
    }).join('');
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.layers || []);
      renderLayers(S.data.layers || []);
      return;
    }
    S.data = null;
    var box = document.getElementById('arch_layers');
    if (box) box.innerHTML = DZ.skeleton(5);
    var res = await DZ.get(API.layers);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '平台架构数据加载失败';
      DZ.render('#arch_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#arch_layers', DZ.empty('平台架构数据不可读'));
      return;
    }
    S.data = res;
    var layers = Array.isArray(res.layers) ? res.layers : [];
    renderKpis(layers);
    renderLayers(layers);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['arch'] = mount;
})();
