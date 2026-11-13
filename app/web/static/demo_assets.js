/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   留存资产（台账 / 自查报告 / 方法与模板 / 已确认结果：登记与归档）
   · demo_assets.js
   视图 id：assets   容器：#assets_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/assets（资产读自运行台账）
   写操作：POST /api/assets、POST /api/assets/{id}/archive、DELETE /api/assets/{id}
          （前后端双重校验，失败 VALIDATION_FAILED）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { assets: '/api/assets' };

  var S = { data: null, showForm: false, busy: false, filter: 'all' };

  function rootEl() { return document.getElementById('assets_root'); }

  function statusBadge(st) {
    if (st === '在册') return DZ.badge('ok', '在册');
    return DZ.badge('unk', st || '—');
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="assets_new" title="登记一项留存资产" aria-label="登记留存资产">登记留存资产</button>' +
        '<button class="ghost" id="assets_refresh" title="重新拉取留存资产数据" aria-label="刷新留存资产">刷新</button>' +
        '<span class="muted">资产随轮次积累：上一轮留下的结论，是下一轮的起点与对照基准；不再沿用的资产可归档留存。</span>' +
      '</div>' +
      '<div id="assets_msg"></div>' +
      '<div id="assets_form"></div>' +
      '<div id="assets_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="assets_filter" class="dz-tabs"></div>' +
      '<div class="card"><h3>留存资产登记台账</h3>' +
        '<div id="assets_table" class="dz-table-wrap">' + DZ.skeleton(4) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('assets_new');
    if (nb) nb.onclick = function () { S.showForm = !S.showForm; renderForm(); };
    var rb = document.getElementById('assets_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderForm();
    load(false);
  }

  function categories() { return (S.data && S.data.categories) || []; }
  function sourceStages() { return (S.data && S.data.sourceStages) || []; }

  function renderForm() {
    var box = document.getElementById('assets_form');
    if (!box) return;
    if (!S.showForm) { box.innerHTML = ''; return; }
    var catOpts = categories().map(function (c) {
      return '<option value="' + DZ.esc(c) + '">' + DZ.esc(c) + '</option>';
    }).join('');
    var stageOpts = '<option value="">（不指定）</option>' + sourceStages().map(function (s) {
      return '<option value="' + DZ.esc(s) + '">' + DZ.esc(s) + '</option>';
    }).join('');
    box.innerHTML = '<div class="card"><h3>登记留存资产</h3>' +
      '<div class="form-narrow">' +
        '<label for="asset_name">资产名称</label>' +
        '<input id="asset_name" placeholder="例如：首轮自查报告（演示）" maxlength="60">' +
        '<div class="grid2" style="gap:12px">' +
          '<div><label for="asset_cat">资产类别</label>' +
            '<select id="asset_cat">' + catOpts + '</select></div>' +
          '<div><label for="asset_stage">由哪一轮留下</label>' +
            '<select id="asset_stage">' + stageOpts + '</select></div>' +
        '</div>' +
        '<label for="asset_ref">说明 / 指向（可选）</label>' +
        '<input id="asset_ref" placeholder="例如：分级结果对账、控制补证的依据" maxlength="80">' +
        '<div class="dz-actions">' +
          '<button id="asset_submit" title="提交登记">提交登记</button>' +
          '<button class="ghost" id="asset_cancel" title="取消登记">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('asset_submit');
    if (sub) sub.onclick = submitCreate;
    var can = document.getElementById('asset_cancel');
    if (can) can.onclick = function () { S.showForm = false; renderForm(); };
  }

  function setMsg(html) { DZ.render('#assets_msg', html || ''); }

  async function submitCreate() {
    if (S.busy) return;
    var name = ((document.getElementById('asset_name') || {}).value || '').trim();
    var category = ((document.getElementById('asset_cat') || {}).value || '').trim();
    var sourceStage = ((document.getElementById('asset_stage') || {}).value || '').trim();
    var ref = ((document.getElementById('asset_ref') || {}).value || '').trim();
    if (!name) { setMsg(DZ.banner('bad', '请填写资产名称')); DZ.toast('请填写资产名称', 'bad'); return; }
    if (!category) { setMsg(DZ.banner('bad', '请选择资产类别')); DZ.toast('请选择资产类别', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '登记中…'));
    var res = await DZ.post(API.assets, { name: name, category: category, sourceStage: sourceStage, ref: ref });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '登记失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('登记失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('留存资产已登记，已写入审计留痕', 'ok');
    S.showForm = false;
    await load(true);
  }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#assets_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('资产类别', DZ.number(categories().length), '四类留痕', '') +
      DZ.kpi('资产总数', DZ.number(s.total), '登记在案', '') +
      DZ.kpi('在册', DZ.number(s.active), '可继续沿用', 'ok') +
      DZ.kpi('已归档', DZ.number(s.archived), '不再变更', 'unk') +
    '</div>');
  }

  function renderFilter() {
    var box = document.getElementById('assets_filter');
    if (!box) return;
    var items = [{ key: 'all', label: '全部' }].concat(categories().map(function (c) {
      return { key: c, label: c };
    }));
    DZ.tabs(box, items, S.filter, function (k) { S.filter = k; renderTable(); });
  }

  function filtered() {
    var rows = (S.data && S.data.assets) || [];
    if (S.filter === 'all') return rows;
    return rows.filter(function (a) { return a.category === S.filter; });
  }

  function renderTable() {
    var box = document.getElementById('assets_table');
    if (!box) return;
    var rows = filtered();
    if (!rows.length) { box.innerHTML = DZ.empty('当前筛选条件下暂无留存资产'); return; }
    box.innerHTML = '<table>' +
      '<thead><tr><th style="min-width:180px">资产名称</th><th style="width:110px">类别</th>' +
        '<th style="width:120px">来源轮次</th><th style="min-width:200px">说明 / 指向</th>' +
        '<th style="width:90px">状态</th><th style="width:150px">归档时间</th>' +
        '<th style="width:150px">操作</th></tr></thead>' +
      '<tbody>' + rows.map(function (a) {
        var act = a.status === '在册'
          ? '<button class="ghost" data-act="archive" data-id="' + DZ.esc(a.assetId) + '" title="归档该资产">归档</button>'
          : '';
        return '<tr>' +
          '<td><b>' + DZ.esc(a.name) + '</b></td>' +
          '<td>' + DZ.pill(a.category) + '</td>' +
          '<td>' + DZ.esc(a.sourceStage || '—') + '</td>' +
          '<td>' + DZ.esc(a.ref || '—') + '</td>' +
          '<td>' + statusBadge(a.status) + '</td>' +
          '<td>' + DZ.esc(a.archivedAt ? DZ.date(a.archivedAt) : '—') + '</td>' +
          '<td><div class="dz-actions">' + act +
            '<button class="ghost" data-act="del" data-id="' + DZ.esc(a.assetId) + '" title="移除该资产">移除</button>' +
          '</div></td>' +
        '</tr>';
      }).join('') + '</tbody></table>';
    bindActions();
  }

  function bindActions() {
    var box = document.getElementById('assets_table');
    if (!box) return;
    box.querySelectorAll('[data-act]').forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute('data-id');
        if (btn.getAttribute('data-act') === 'archive') archiveAsset(id);
        else removeAsset(id);
      };
    });
  }

  async function archiveAsset(id) {
    setMsg(DZ.banner('', '归档中…'));
    var res = await DZ.post(API.assets + '/' + encodeURIComponent(id) + '/archive');
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '归档失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('留存资产已归档，已写入审计留痕', 'ok');
    await load(true);
  }

  async function removeAsset(id) {
    setMsg(DZ.banner('', '处理中…'));
    var res = await DZ.del(API.assets + '/' + encodeURIComponent(id));
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('留存资产已移除，已写入审计留痕', 'ok');
    await load(true);
  }

  async function load(force) {
    if (S.data && !force) {
      renderForm();
      renderKpis(S.data.summary);
      renderFilter();
      renderTable();
      return;
    }
    var box = document.getElementById('assets_table');
    if (box) box.innerHTML = DZ.skeleton(4);
    var res = await DZ.get(API.assets);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '留存资产数据加载失败';
      DZ.render('#assets_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#assets_table', DZ.empty('留存资产数据不可读'));
      return;
    }
    S.data = res;
    renderForm();
    renderKpis(res.summary || {});
    renderFilter();
    renderTable();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['assets'] = mount;
})();
