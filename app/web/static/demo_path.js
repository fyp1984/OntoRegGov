/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   实施路径（四阶段 × 六列：起点主题 / 目标与交付物 / 转段判据 / 工具接入 / 机构资产）
   · demo_path.js
   视图 id：path   容器：#path_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/implementation/path（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { path: '/api/implementation/path' };

  // 阶段卡片的五列（标题「阶段 X」之外的其余列）
  var COLS = [
    { key: 'start', label: '起点主题' },
    { key: 'goal', label: '阶段目标与责任交付物' },
    { key: 'gate', label: '转段与验收判据' },
    { key: 'tools', label: '工具接入衔接' },
    { key: 'asset', label: '机构留下的资产' }
  ];

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('path_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="path_refresh" title="重新拉取实施路径数据" aria-label="刷新实施路径">刷新</button>' +
        '<span class="muted">首轮起点主题不预设：按机构当前关注点自选一个主题，之后按同一条链逐轮走。</span>' +
      '</div>' +
      '<div id="path_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>阶段推进</h3><div id="path_flow">' + DZ.skeleton(1) + '</div></div>' +
      '<div id="path_stages">' + DZ.skeleton(4) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('path_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(summary) {
    DZ.render('#path_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('阶段数', DZ.number(summary && summary.stages), '逐轮推进', '') +
      DZ.kpi('首轮起点', '自选主题', '由机构当前关注点决定', '') +
    '</div>');
  }

  function renderFlow(stages) {
    var box = document.getElementById('path_flow');
    if (!box) return;
    if (!stages.length) { box.innerHTML = DZ.empty('暂无阶段'); return; }
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="实施阶段">' +
      stages.map(function (s, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="阶段 ' + DZ.esc(s.stage) + '">' +
            '<div class="dz-node-title">阶段 ' + DZ.esc(s.stage) + '</div>' +
            '<div class="dz-mini">' + DZ.esc(s.start) + '</div>' +
          '</div>';
      }).join('') + '</div>' +
      '<div class="muted">每一轮从上一轮确认过的结论开始，轮次由已确认的结果驱动。</div>';
  }

  function renderStages(stages) {
    var box = document.getElementById('path_stages');
    if (!box) return;
    if (!stages.length) { box.innerHTML = DZ.empty('暂无阶段'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px">' +
      stages.map(function (s) {
        var rows = COLS.map(function (c) {
          return '<div class="dz-metric">' +
            '<span class="dz-metric-k">' + DZ.esc(c.label) + '</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(s[c.key] || '—') + '</span>' +
          '</div>';
        }).join('');
        return '<div class="card">' +
          '<h3>阶段 ' + DZ.esc(s.stage) + '</h3>' +
          '<div style="margin-top:6px">' + rows + '</div>' +
        '</div>';
      }).join('') + '</div>';
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.summary);
      renderFlow(S.data.stages || []);
      renderStages(S.data.stages || []);
      return;
    }
    S.data = null;
    var box = document.getElementById('path_stages');
    if (box) box.innerHTML = DZ.skeleton(4);
    var res = await DZ.get(API.path);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '实施路径数据加载失败';
      DZ.render('#path_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#path_flow', DZ.empty('实施路径数据不可读'));
      DZ.render('#path_stages', DZ.empty('实施路径数据不可读'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderFlow(Array.isArray(res.stages) ? res.stages : []);
    renderStages(Array.isArray(res.stages) ? res.stages : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['path'] = mount;
})();
