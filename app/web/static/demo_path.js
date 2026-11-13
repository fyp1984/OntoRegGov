/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   实施路径（四阶段 × 六列 × 转段判据：判定通过方可转段）
   · demo_path.js
   视图 id：path   容器：#path_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/implementation/path（六列读自方法论口径，阶段状态与判据读自运行台账）
   写操作：POST /api/implementation/path/gates/{id}/check、POST /api/implementation/path/stages/{stage}/advance
          （前后端双重校验，失败 VALIDATION_FAILED）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { path: '/api/implementation/path' };

  var COLS = [
    { key: 'start', label: '起点主题' },
    { key: 'goal', label: '阶段目标与责任交付物' },
    { key: 'gate', label: '转段与验收判据' },
    { key: 'tools', label: '工具接入衔接' },
    { key: 'asset', label: '机构留下的资产' }
  ];

  var S = { data: null, busy: false };

  function rootEl() { return document.getElementById('path_root'); }

  function stageStatusBadge(st) {
    if (st === 'done') return DZ.badge('ok', '已完成');
    if (st === 'in_progress') return DZ.badge('warn', '进行中');
    return DZ.badge('unk', '未开始');
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="path_refresh" title="重新拉取实施路径数据" aria-label="刷新实施路径">刷新</button>' +
        '<span class="muted">首轮起点主题不预设：按机构当前关注点自选一个主题；逐项判定转段判据，全过方可转段。</span>' +
      '</div>' +
      '<div id="path_msg"></div>' +
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

  function setMsg(html) { DZ.render('#path_msg', html || ''); }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#path_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('阶段数', DZ.number(s.stages), '逐轮推进', '') +
      DZ.kpi('已完成', DZ.number(s.done), '已转段阶段', 'ok') +
      DZ.kpi('进行中', DZ.number(s.inProgress), '当前阶段', 'warn') +
      DZ.kpi('转段判据', DZ.number(s.gates), '已判定 ' + DZ.number(s.gatesChecked), '') +
    '</div>');
  }

  function renderFlow(stages) {
    var box = document.getElementById('path_flow');
    if (!box) return;
    if (!stages.length) { box.innerHTML = DZ.empty('暂无阶段'); return; }
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="实施阶段">' +
      stages.map(function (s, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node ' + (s.status === 'done' ? 'on' : (s.status === 'in_progress' ? 'on' : '')) + '" ' +
            'role="listitem" title="阶段 ' + DZ.esc(s.stage) + '：' + DZ.esc(s.statusLabel) + '">' +
            '<div class="dz-node-title">阶段 ' + DZ.esc(s.stage) + ' ' + stageStatusBadge(s.status) + '</div>' +
            '<div class="dz-mini">判据 ' + DZ.number(s.gateDone) + ' / ' + DZ.number(s.gateTotal) + '</div>' +
          '</div>';
      }).join('') + '</div>' +
      '<div class="muted">每一轮从上一轮确认过的结论开始，轮次由已确认的结果驱动。</div>';
  }

  function gateList(s) {
    var items = s.gateItems || [];
    if (!items.length) return '<div class="muted">该阶段暂无转段判据。</div>';
    var editable = s.status === 'in_progress';
    return items.map(function (g) {
      var checked = g.checked ? ' checked' : '';
      var dis = editable ? '' : ' disabled';
      var meta = g.checked && g.checkedBy
        ? '<span class="muted">由 ' + DZ.esc(g.checkedBy) + ' 于 ' + DZ.esc(DZ.date(g.checkedAt)) + ' 判定</span>'
        : '<span class="muted">未判定</span>';
      return '<div class="dz-metric">' +
        '<span class="dz-metric-k" style="flex:1">' +
          '<label style="display:flex;gap:8px;align-items:flex-start;cursor:pointer">' +
            '<input type="checkbox" data-gate="' + DZ.esc(g.itemId) + '"' + checked + dis +
              ' aria-label="转段判据：' + DZ.esc(g.text) + '">' +
            '<span>' + DZ.esc(g.seq) + '．' + DZ.esc(g.text) + '</span>' +
          '</label>' +
        '</span>' +
        '<span class="dz-metric-v" style="text-align:right;font-weight:400">' + meta + '</span>' +
      '</div>';
    }).join('');
  }

  function renderStages(stages) {
    var box = document.getElementById('path_stages');
    if (!box) return;
    if (!stages.length) { box.innerHTML = DZ.empty('暂无阶段'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px">' +
      stages.map(function (s) {
        var rows = COLS.map(function (c) {
          return '<div class="dz-metric">' +
            '<span class="dz-metric-k">' + DZ.esc(c.label) + '</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(s[c.key] || '—') + '</span>' +
          '</div>';
        }).join('');
        var advBtn = '<button id="path_adv_' + DZ.esc(s.stage) + '" ' +
          (s.canAdvance ? '' : 'disabled ') +
          'title="' + (s.canAdvance ? '判据已全部通过，可转段' : '判据未全部通过，暂不可转段') + '">' +
          (s.status === 'done' ? '已转段' : (s.status === 'pending' ? '未开始' : '确认转段')) + '</button>';
        return '<div class="card">' +
          '<h3>阶段 ' + DZ.esc(s.stage) + ' ' + stageStatusBadge(s.status) + '</h3>' +
          '<div style="margin-top:6px">' + rows + '</div>' +
          '<h4>转段判据（' + DZ.number(s.gateDone) + ' / ' + DZ.number(s.gateTotal) + '）</h4>' +
          gateList(s) +
          '<div class="dz-actions">' + advBtn + '</div>' +
        '</div>';
      }).join('') + '</div>';
    bindStages(stages);
  }

  function bindStages(stages) {
    var box = document.getElementById('path_stages');
    if (!box) return;
    box.querySelectorAll('[data-gate]').forEach(function (cb) {
      cb.onchange = function () { checkGate(cb.getAttribute('data-gate'), cb.checked); };
    });
    stages.forEach(function (s) {
      var btn = document.getElementById('path_adv_' + s.stage);
      if (btn && s.canAdvance) btn.onclick = function () { advance(s.stage); };
    });
  }

  async function checkGate(itemId, checked) {
    if (S.busy) return;
    S.busy = true;
    var res = await DZ.post(API.path + '/gates/' + encodeURIComponent(itemId) + '/check', { checked: checked });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '判据判定失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad');
      await load(true);
      return;
    }
    setMsg('');
    DZ.toast(checked ? '转段判据已判定通过' : '转段判据已取消判定', 'ok');
    await load(true);
  }

  async function advance(stage) {
    if (S.busy) return;
    S.busy = true;
    setMsg(DZ.banner('', '转段中…'));
    var res = await DZ.post(API.path + '/stages/' + encodeURIComponent(stage) + '/advance');
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '转段失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad');
      await load(true);
      return;
    }
    setMsg('');
    DZ.toast(res.allDone ? '阶段已推进，本轮四阶段全部完成' : ('阶段 ' + stage + ' 已转段，进入阶段 ' + res.nextStage), 'ok');
    await load(true);
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.summary);
      renderFlow(S.data.stages || []);
      renderStages(S.data.stages || []);
      return;
    }
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
