/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   现状诊断（五个维度 × 三问「有没有 / 有没有执行 / 有没有证据」）
   · demo_diag.js
   视图 id：diag   容器：#diag_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/diagnosis/dimensions（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { dimensions: '/api/diagnosis/dimensions' };

  // 三问判定 → 徽章（文字与颜色并存，不只靠颜色）
  function stateBadge(s) {
    if (s === 'yes') return DZ.badge('ok', '有');
    if (s === 'partial') return DZ.badge('warn', '部分');
    if (s === 'no') return DZ.badge('bad', '缺');
    return DZ.badge('unk', '—');
  }

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('diag_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="diag_refresh" title="重新拉取现状诊断数据" aria-label="刷新现状诊断">刷新</button>' +
        '<span class="muted">同一组三问逐层收紧：先问有没有，再问有没有执行，最后问有没有证据。</span>' +
      '</div>' +
      '<div id="diag_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>三问链条</h3><div id="diag_chain">' + DZ.skeleton(1) + '</div></div>' +
      '<div id="diag_dims">' + DZ.skeleton(4) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('diag_refresh');
    if (btn) btn.onclick = function () { load(true); };
    renderChain();
    load(false);
  }

  // 三问链条：有没有 → 有没有执行 → 有没有证据
  function renderChain() {
    var box = document.getElementById('diag_chain');
    if (!box) return;
    var steps = ['有没有', '有没有执行', '有没有证据'];
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="三问链条">' +
      steps.map(function (t, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="三问第 ' + (i + 1) + ' 层：' + DZ.esc(t) + '">' +
            '<div class="dz-node-title">' + DZ.esc(t) + '</div>' +
          '</div>';
      }).join('') + '</div>' +
      '<div class="muted">只答「有没有」，得到的是一张制度清单；三问都过，才拿到可核对的结论。</div>';
  }

  function renderKpis(summary) {
    var a = (summary && summary.answers) || { yes: 0, partial: 0, no: 0 };
    var total = (Number(a.yes) || 0) + (Number(a.partial) || 0) + (Number(a.no) || 0);
    DZ.render('#diag_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('诊断维度', DZ.number(summary && summary.dimensions), '逐层覆盖', '') +
      DZ.kpi('每层三问', DZ.number(summary && summary.questions), '同一组问法', '') +
      DZ.kpi('有', DZ.number(a.yes), '共 ' + DZ.number(total) + ' 项判定', 'ok') +
      DZ.kpi('部分', DZ.number(a.partial), '共 ' + DZ.number(total) + ' 项判定', 'warn') +
      DZ.kpi('缺', DZ.number(a.no), '共 ' + DZ.number(total) + ' 项判定', 'bad') +
    '</div>');
  }

  function renderDims(dims) {
    var boxes = document.getElementById('diag_dims');
    if (!boxes) return;
    if (!dims.length) { boxes.innerHTML = DZ.empty('暂无诊断维度'); return; }
    boxes.innerHTML = dims.map(function (d) {
      var rows = (d.answers || []).map(function (x) {
        return '<tr>' +
          '<td>' + DZ.esc(x.q) + '</td>' +
          '<td>' + stateBadge(x.state) + '</td>' +
          '<td>' + DZ.esc(x.text) + '</td>' +
        '</tr>';
      }).join('');
      return '<div class="card">' +
        '<h3>维度 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + '</h3>' +
        '<div class="dz-table-wrap"><table>' +
          '<thead><tr><th style="width:130px">三问</th><th style="width:90px">判定</th><th>对应现状</th></tr></thead>' +
          '<tbody>' + rows + '</tbody></table></div>' +
        '<h4>小结</h4><div class="dz-cite"><div>' + DZ.esc(d.note || '—') + '</div></div>' +
        '<h4>下一步</h4><div class="why">' + DZ.esc(d.next || '—') + '</div>' +
      '</div>';
    }).join('');
  }

  async function load(force) {
    if (S.data && !force) { renderKpis(S.data.summary); renderDims(S.data.dimensions || []); return; }
    S.data = null;
    var boxes = document.getElementById('diag_dims');
    if (boxes) boxes.innerHTML = DZ.skeleton(4);
    var res = await DZ.get(API.dimensions);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '现状诊断数据加载失败';
      DZ.render('#diag_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#diag_dims', DZ.empty('诊断维度暂不可用'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderDims(Array.isArray(res.dimensions) ? res.dimensions : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['diag'] = mount;
})();
