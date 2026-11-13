/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   应用与业务层台账（分类分级对账 · 从「管库表」走向「管使用场景」）
   · demo_ledger.js
   视图 id：ledger   容器：#ledger_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/ledger/rows（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { rows: '/api/ledger/rows' };

  // 对账结论 → 徽章
  function resultBadge(r) {
    if (r === 'aligned') return DZ.badge('ok', '已对上');
    if (r === 'partial') return DZ.badge('warn', '部分对上');
    if (r === 'missing') return DZ.badge('bad', '未对上');
    return DZ.badge('unk', '—');
  }
  // 分级 → 徽章（敏感 / 重要 / 内部）
  function levelBadge(l) {
    if (l === '敏感') return DZ.badge('bad', l);
    if (l === '重要') return DZ.badge('warn', l);
    return DZ.badge('unk', l || '—');
  }

  var FILTERS = [
    { key: 'all', label: '全部' },
    { key: 'aligned', label: '已对上' },
    { key: 'partial', label: '部分对上' },
    { key: 'missing', label: '未对上' }
  ];

  var S = { data: null, filter: 'all' };

  function rootEl() { return document.getElementById('ledger_root'); }

  function filtered() {
    var rows = (S.data && S.data.rows) || [];
    if (S.filter === 'all') return rows;
    return rows.filter(function (r) { return r.result === S.filter; });
  }

  function shell() {
    var opts = FILTERS.map(function (f) {
      return '<option value="' + f.key + '"' + (f.key === S.filter ? ' selected' : '') + '>' + DZ.esc(f.label) + '</option>';
    }).join('');
    return '' +
      '<div class="dz-toolbar">' +
        '<label class="muted" for="ledger_filter" style="margin:0">对账结论</label>' +
        '<select id="ledger_filter" title="按对账结论筛选" aria-label="按对账结论筛选">' + opts + '</select>' +
        '<button class="ghost" id="ledger_refresh" title="重新拉取台账数据" aria-label="刷新台账">刷新</button>' +
        '<span class="muted">沿用已有分类分级成果，补的是应用与业务这一层：把后台接口、导出、角色权限、报表与应用日志，同分级结果、权限、脱敏、导出审批逐项对账。</span>' +
      '</div>' +
      '<div id="ledger_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>应用与业务层台账对账</h3>' +
        '<div id="ledger_table" class="dz-table-wrap">' + DZ.skeleton(4) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var sel = document.getElementById('ledger_filter');
    if (sel) sel.onchange = function () { S.filter = this.value; renderTable(); };
    var btn = document.getElementById('ledger_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#ledger_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('对账场景', DZ.number(s.total), '应用与业务层', '') +
      DZ.kpi('已对上', DZ.number(s.aligned), '分级与控制一致', 'ok') +
      DZ.kpi('部分对上', DZ.number(s.partial), '有控制但未逐项登记', 'warn') +
      DZ.kpi('未对上', DZ.number(s.missing), '控制未落到该链路', 'bad') +
    '</div>');
  }

  function renderTable() {
    var box = document.getElementById('ledger_table');
    if (!box) return;
    var rows = filtered();
    if (!rows.length) { box.innerHTML = DZ.empty('当前筛选条件下暂无对账记录'); return; }
    box.innerHTML = '<table>' +
      '<thead><tr><th style="min-width:180px">使用场景</th><th>分级</th>' +
        '<th style="min-width:220px">应做到</th><th style="min-width:220px">实际（对账发现）</th>' +
        '<th style="width:110px">对账结论</th></tr></thead>' +
      '<tbody>' + rows.map(function (r) {
        return '<tr>' +
          '<td><b>' + DZ.esc(r.scene) + '</b></td>' +
          '<td>' + levelBadge(r.level) + '</td>' +
          '<td>' + DZ.esc(r.should) + '</td>' +
          '<td>' + DZ.esc(r.actual) + '</td>' +
          '<td>' + resultBadge(r.result) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table>' +
      '<div class="muted" style="margin-top:8px">对账结论：已对上＝分级结果与权限／脱敏／导出审批一致；部分对上＝已有控制但未逐项登记；未对上＝控制未落到该链路。</div>';
  }

  async function load(force) {
    if (S.data && !force) { renderKpis(S.data.summary); renderTable(); return; }
    S.data = null;
    var box = document.getElementById('ledger_table');
    if (box) box.innerHTML = DZ.skeleton(4);
    var res = await DZ.get(API.rows);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '台账数据加载失败';
      DZ.render('#ledger_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#ledger_table', DZ.empty('台账暂不可用'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderTable();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['ledger'] = mount;
})();
