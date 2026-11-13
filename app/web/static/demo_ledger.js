/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   应用与业务层台账（分类分级对账 · 从「管库表」走向「管使用场景」）
   · demo_ledger.js
   视图 id：ledger   容器：#ledger_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   读：GET /api/ledger/rows（对账行读自运行台账）
   写：POST /api/ledger/rows（登记）、PUT /api/ledger/rows/{id}（编辑）、
      DELETE /api/ledger/rows/{id}（移除）
   前后端双重校验：字段必填、分级与结论枚举、结论与实际描述一致性；失败 VALIDATION_FAILED。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { rows: '/api/ledger/rows' };
  var NEG_HINTS = ['未', '尚未', '缺', '暂无', '没有', '不足', '不完整'];

  var LEVEL_KIND = { '敏感': 'bad', '重要': 'warn', '内部': 'unk' };
  var RESULT_KIND = { aligned: 'ok', partial: 'warn', missing: 'bad' };

  var S = { data: null, filter: 'all', mode: 'none', editId: null, busy: false };

  function rootEl() { return document.getElementById('ledger_root'); }

  function rows() { return (S.data && S.data.rows) || []; }
  function levels() { return (S.data && S.data.levels) || ['敏感', '重要', '内部']; }
  function results() {
    return (S.data && S.data.results) || ['aligned', 'partial', 'missing'];
  }
  function resultLabel(r) {
    var map = { aligned: '已对上', partial: '部分对上', missing: '未对上' };
    return map[r] || r;
  }
  function filtered() {
    if (S.filter === 'all') return rows();
    return rows().filter(function (r) { return r.result === S.filter; });
  }
  function editRow() {
    return rows().filter(function (r) { return r.rowId === S.editId; })[0] || null;
  }

  function resultBadge(r) { return DZ.badge(RESULT_KIND[r] || 'unk', resultLabel(r)); }
  function levelBadge(l) { return DZ.badge(LEVEL_KIND[l] || 'unk', l || '—'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button id="ledger_new" title="登记一行新的对账记录" aria-label="登记对账行">登记对账行</button>' +
        '<button class="ghost" id="ledger_refresh" title="重新拉取台账数据" aria-label="刷新台账">刷新</button>' +
        '<span class="muted">沿用已有分类分级成果，补的是应用与业务这一层：把后台接口、导出、角色权限、报表与应用日志，同分级结果、权限、脱敏、导出审批逐项对账。</span>' +
      '</div>' +
      '<div id="ledger_msg"></div>' +
      '<div id="ledger_form"></div>' +
      '<div id="ledger_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>应用与业务层台账对账</h3>' +
        '<div id="ledger_tabs"></div>' +
        '<div id="ledger_table" class="dz-table-wrap">' + DZ.skeleton(4) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('ledger_new');
    if (nb) nb.onclick = function () { openCreate(); };
    var rb = document.getElementById('ledger_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderTabs();
    load(false);
  }

  function setMsg(html) { DZ.render('#ledger_msg', html || ''); }

  // ------------------------------------------------------------- 对账结论页签
  function renderTabs() {
    var items = [{ key: 'all', label: '全部' }].concat(results().map(function (r) {
      return { key: r, label: resultLabel(r) };
    }));
    DZ.tabs('#ledger_tabs', items, S.filter, function (k) { S.filter = k; renderTable(); });
  }

  // ------------------------------------------------------------- 表单
  function openCreate() {
    S.mode = 'create'; S.editId = null; renderForm(); scrollForm();
  }
  function openEdit(id) {
    S.mode = 'edit'; S.editId = id; renderForm(); scrollForm();
  }
  function closeForm() {
    S.mode = 'none'; S.editId = null; renderForm();
  }

  function renderForm() {
    var box = document.getElementById('ledger_form');
    if (!box) return;
    if (S.mode === 'none') { box.innerHTML = ''; return; }
    var r = S.mode === 'edit' ? editRow() : null;
    if (S.mode === 'edit' && !r) { box.innerHTML = ''; return; }
    var v = r || { scene: '', level: '敏感', should: '', actual: '', result: 'aligned' };
    var lvOpts = levels().map(function (l) {
      return '<option value="' + DZ.esc(l) + '"' + (l === v.level ? ' selected' : '') + '>' + DZ.esc(l) + '</option>';
    }).join('');
    var rsOpts = results().map(function (k) {
      return '<option value="' + DZ.esc(k) + '"' + (k === v.result ? ' selected' : '') + '>' + DZ.esc(resultLabel(k)) + '</option>';
    }).join('');
    box.innerHTML = '<div class="card"><h3>' + (S.mode === 'edit' ? '编辑对账行' : '登记对账行') + '</h3>' +
      '<div class="grid2">' +
        '<div><label for="lg_scene">使用场景（必填）</label>' +
          '<input id="lg_scene" maxlength="60" placeholder="例如：系统甲 · 报表导出" value="' + DZ.esc(v.scene) + '"></div>' +
        '<div><label for="lg_level">分级（必填）</label>' +
          '<select id="lg_level">' + lvOpts + '</select></div>' +
      '</div>' +
      '<label for="lg_should">应做到（必填）</label>' +
      '<input id="lg_should" maxlength="120" placeholder="例如：导出审批 + 字段最小化 + 到期回收与删除验证" value="' + DZ.esc(v.should) + '">' +
      '<label for="lg_actual">实际（对账发现，必填）</label>' +
      '<input id="lg_actual" maxlength="120" placeholder="例如：展示层已脱敏；后台接口返回明文" value="' + DZ.esc(v.actual) + '">' +
      '<label for="lg_result">对账结论（必填）</label>' +
      '<select id="lg_result">' + rsOpts + '</select>' +
      '<div class="dz-actions">' +
        '<button id="lg_submit" title="保存对账行">' + (S.mode === 'edit' ? '保存修改' : '登记') + '</button>' +
        '<button class="ghost" id="lg_cancel" title="取消">取消</button>' +
      '</div></div>';
    var sub = document.getElementById('lg_submit');
    if (sub) sub.onclick = submitForm;
    var can = document.getElementById('lg_cancel');
    if (can) can.onclick = closeForm;
  }

  function scrollForm() {
    var f = document.getElementById('ledger_form');
    if (f && f.scrollIntoView) f.scrollIntoView({ block: 'nearest' });
  }

  function val(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }

  function localCheck(p) {
    if (!p.scene) return '「使用场景」必填';
    if (!p.should) return '「应做到」必填';
    if (!p.actual) return '「实际（对账发现）」必填';
    if (p.result === 'aligned' && NEG_HINTS.some(function (w) { return p.actual.indexOf(w) >= 0; })) {
      return '结论「已对上」与「实际」描述不一致：描述中含否定表述，请核对结论';
    }
    return null;
  }

  async function submitForm() {
    if (S.busy) return;
    var payload = {
      scene: val('lg_scene'), level: val('lg_level'),
      should: val('lg_should'), actual: val('lg_actual'), result: val('lg_result')
    };
    var badMsg = localCheck(payload);
    if (badMsg) { setMsg(DZ.banner('bad', badMsg)); DZ.toast(badMsg, 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', S.mode === 'edit' ? '保存中…' : '登记中…'));
    var res = S.mode === 'edit'
      ? await DZ.put(API.rows + '/' + encodeURIComponent(S.editId), payload)
      : await DZ.post(API.rows, payload);
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '保存失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('保存失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast(S.mode === 'edit' ? '对账行已更新，已写入审计留痕' : '对账行已登记，已写入审计留痕', 'ok');
    S.mode = 'none'; S.editId = null;
    await load(true);
  }

  async function removeRow(id) {
    if (S.busy) return;
    S.busy = true;
    var res = await DZ.del(API.rows + '/' + encodeURIComponent(id));
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('移除失败：' + m, 'bad'); return;
    }
    setMsg(''); DZ.toast('对账行已移除', 'ok');
    if (S.editId === id) closeForm();
    await load(true);
  }

  // ------------------------------------------------------------- 指标 / 表格
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
    var list = filtered();
    if (!list.length) {
      box.innerHTML = DZ.empty('当前筛选条件下暂无对账记录',
        '<button class="ghost" onclick="document.getElementById(\'ledger_new\').click()" title="登记对账行">登记对账行</button>');
      return;
    }
    box.innerHTML = '<table>' +
      '<thead><tr><th style="min-width:180px">使用场景</th><th>分级</th>' +
        '<th style="min-width:220px">应做到</th><th style="min-width:220px">实际（对账发现）</th>' +
        '<th style="width:110px">对账结论</th><th style="min-width:140px">操作</th></tr></thead>' +
      '<tbody>' + list.map(function (r) {
        return '<tr>' +
          '<td><b>' + DZ.esc(r.scene) + '</b></td>' +
          '<td>' + levelBadge(r.level) + '</td>' +
          '<td>' + DZ.esc(r.should) + '</td>' +
          '<td>' + DZ.esc(r.actual) + '</td>' +
          '<td>' + resultBadge(r.result) + '</td>' +
          '<td><div class="dz-actions" style="margin:0">' +
            '<button class="ghost" data-edit="' + DZ.esc(r.rowId) + '" title="编辑对账行">编辑</button>' +
            '<button class="ghost" data-del="' + DZ.esc(r.rowId) + '" title="移除对账行">移除</button>' +
          '</div></td>' +
        '</tr>';
      }).join('') + '</tbody></table>' +
      '<div class="muted" style="margin-top:8px">对账结论：已对上＝分级结果与权限／脱敏／导出审批一致；部分对上＝已有控制但未逐项登记；未对上＝控制未落到该链路。</div>';
    box.querySelectorAll('[data-edit]').forEach(function (b) {
      b.onclick = function () { openEdit(b.getAttribute('data-edit')); };
    });
    box.querySelectorAll('[data-del]').forEach(function (b) {
      b.onclick = function () { removeRow(b.getAttribute('data-del')); };
    });
  }

  // ------------------------------------------------------------- 装载
  async function load(force) {
    if (S.data && !force) {
      renderTabs(); renderKpis(S.data.summary); renderTable(); renderForm();
      return;
    }
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
    renderTabs();
    renderKpis(res.summary || {});
    renderTable();
    renderForm();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['ledger'] = mount;
})();
