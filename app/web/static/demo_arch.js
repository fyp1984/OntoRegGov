/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   平台架构（知识底座五层 × 层模块接入登记：接入方式 / 绑定能力 / 状态）
   · demo_arch.js
   视图 id：arch   容器：#arch_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/architecture/layers（层说明读自方法论口径，模块读自运行台账）
   写操作：POST /api/architecture/modules、PATCH /api/architecture/modules/{id}、
          DELETE /api/architecture/modules/{id}（前后端双重校验，失败 VALIDATION_FAILED）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { layers: '/api/architecture/layers', modules: '/api/architecture/modules' };

  var S = { data: null, showForm: false, busy: false };

  function rootEl() { return document.getElementById('arch_root'); }

  function moduleStatusBadge(st) {
    if (st === 'active') return DZ.badge('ok', '已接入');
    if (st === 'suspended') return DZ.badge('unk', '已停用');
    return DZ.badge('unk', st || '—');
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="arch_new" title="登记一个新的层模块" aria-label="登记层模块">登记层模块</button>' +
        '<button class="ghost" id="arch_refresh" title="重新拉取平台架构数据" aria-label="刷新平台架构">刷新</button>' +
        '<span class="muted">自上而下：知识层供依据，编排层管作业，接入层给入口，能力层出结果，证据层留痕迹；模块接入须登记接入方式。</span>' +
      '</div>' +
      '<div id="arch_msg"></div>' +
      '<div id="arch_form"></div>' +
      '<div id="arch_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="arch_layers">' + DZ.skeleton(5) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('arch_new');
    if (nb) nb.onclick = function () { S.showForm = !S.showForm; renderForm(); };
    var rb = document.getElementById('arch_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderForm();
    load(false);
  }

  function accessModes() { return (S.data && S.data.accessModes) || []; }
  function layers() { return (S.data && S.data.layers) || []; }

  function renderForm() {
    var box = document.getElementById('arch_form');
    if (!box) return;
    if (!S.showForm) { box.innerHTML = ''; return; }
    var layerOpts = layers().map(function (L) {
      return '<option value="' + DZ.esc(L.no) + '">第 ' + DZ.esc(L.no) + ' 层 · ' + DZ.esc(L.name) + '</option>';
    }).join('');
    var modeOpts = accessModes().map(function (m) {
      return '<option value="' + DZ.esc(m) + '">' + DZ.esc(m) + '</option>';
    }).join('');
    box.innerHTML = '<div class="card"><h3>登记层模块</h3>' +
      '<div class="form-narrow">' +
        '<label for="arch_layer">所属层级</label>' +
        '<select id="arch_layer">' + layerOpts + '</select>' +
        '<div class="grid2" style="gap:12px">' +
          '<div><label for="arch_name">模块名称</label>' +
            '<input id="arch_name" placeholder="例如：知识库" maxlength="40"></div>' +
          '<div><label for="arch_mode">接入方式</label>' +
            '<select id="arch_mode">' + modeOpts + '</select></div>' +
        '</div>' +
        '<label for="arch_bound">绑定能力（可选，填能力实例名称）</label>' +
        '<input id="arch_bound" placeholder="例如：数据分级插件" maxlength="60">' +
        '<div class="dz-actions">' +
          '<button id="arch_submit" title="提交登记">提交登记</button>' +
          '<button class="ghost" id="arch_cancel" title="取消登记">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('arch_submit');
    if (sub) sub.onclick = submitCreate;
    var can = document.getElementById('arch_cancel');
    if (can) can.onclick = function () { S.showForm = false; renderForm(); };
  }

  function setMsg(html) { DZ.render('#arch_msg', html || ''); }

  async function submitCreate() {
    if (S.busy) return;
    var layerNo = Number((document.getElementById('arch_layer') || {}).value);
    var name = ((document.getElementById('arch_name') || {}).value || '').trim();
    var accessMode = ((document.getElementById('arch_mode') || {}).value || '').trim();
    var boundCapability = ((document.getElementById('arch_bound') || {}).value || '').trim();
    if (!name) { setMsg(DZ.banner('bad', '请填写模块名称')); DZ.toast('请填写模块名称', 'bad'); return; }
    if (!accessMode) { setMsg(DZ.banner('bad', '请选择接入方式')); DZ.toast('请选择接入方式', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '登记中…'));
    var res = await DZ.post(API.modules, {
      layerNo: layerNo, name: name, accessMode: accessMode, boundCapability: boundCapability
    });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '登记失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('登记失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('层模块已登记，已写入审计留痕', 'ok');
    S.showForm = false;
    await load(true);
  }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#arch_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('架构层', DZ.number(s.layers), '自上而下分层', '') +
      DZ.kpi('已登记模块', DZ.number(s.modules), '各层可复用模块', '') +
      DZ.kpi('已绑定能力', DZ.number(s.bound), '模块与能力实例关联', 'ok') +
    '</div>');
  }

  function modulesOf(L) {
    var all = (S.data && S.data.modules) || [];
    return all.filter(function (m) { return m.layerNo === L.no; });
  }

  function moduleTable(list) {
    if (!list.length) return '<div class="muted" style="margin-top:8px">该层暂无已登记模块。</div>';
    var rows = list.map(function (m) {
      var toggleLabel = m.status === 'active' ? '停用' : '启用';
      var toggleTo = m.status === 'active' ? 'suspended' : 'active';
      return '<tr>' +
        '<td><b>' + DZ.esc(m.name) + '</b></td>' +
        '<td>' + DZ.pill(m.accessMode) + '</td>' +
        '<td>' + DZ.esc(m.boundCapability || '—') + '</td>' +
        '<td>' + moduleStatusBadge(m.status) + '</td>' +
        '<td>' + DZ.esc(m.owner || '—') + '</td>' +
        '<td><div class="dz-actions">' +
          '<button class="ghost" data-act="toggle" data-id="' + DZ.esc(m.moduleId) + '" ' +
            'data-to="' + toggleTo + '" title="' + toggleLabel + '该模块">' + toggleLabel + '</button>' +
          '<button class="ghost" data-act="del" data-id="' + DZ.esc(m.moduleId) + '" title="移除该模块">移除</button>' +
        '</div></td>' +
      '</tr>';
    }).join('');
    return '<div class="dz-table-wrap" style="margin-top:8px"><table>' +
      '<thead><tr><th style="min-width:140px">模块名称</th><th style="width:110px">接入方式</th>' +
        '<th style="min-width:150px">绑定能力</th><th style="width:90px">状态</th>' +
        '<th style="width:110px">登记人</th><th style="width:150px">操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function renderLayers(layersList) {
    var box = document.getElementById('arch_layers');
    if (!box) return;
    if (!layersList.length) { box.innerHTML = DZ.empty('暂无架构层'); return; }
    box.innerHTML = layersList.map(function (L) {
      return '<div class="card">' +
        '<h3>第 ' + DZ.esc(L.no) + ' 层 · ' + DZ.esc(L.name) + '</h3>' +
        '<div class="dz-cite"><div>' + DZ.esc(L.desc || '—') + '</div></div>' +
        '<h4>已登记模块</h4>' +
        moduleTable(modulesOf(L)) +
      '</div>';
    }).join('');
    bindActions();
  }

  function bindActions() {
    var box = document.getElementById('arch_layers');
    if (!box) return;
    box.querySelectorAll('[data-act]').forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute('data-id');
        var act = btn.getAttribute('data-act');
        if (act === 'toggle') toggleModule(id, btn.getAttribute('data-to'));
        else if (act === 'del') removeModule(id);
      };
    });
  }

  async function toggleModule(id, to) {
    setMsg(DZ.banner('', '处理中…'));
    var res = await DZ.patch(API.modules + '/' + encodeURIComponent(id), { status: to });
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '操作失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast(to === 'active' ? '层模块已启用' : '层模块已停用', 'ok');
    await load(true);
  }

  async function removeModule(id) {
    setMsg(DZ.banner('', '处理中…'));
    var res = await DZ.del(API.modules + '/' + encodeURIComponent(id));
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('层模块已移除，已写入审计留痕', 'ok');
    await load(true);
  }

  async function load(force) {
    if (S.data && !force) {
      renderForm();
      renderKpis(S.data.summary);
      renderLayers(Array.isArray(S.data.layers) ? S.data.layers : []);
      return;
    }
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
    renderForm();
    renderKpis(res.summary || {});
    renderLayers(Array.isArray(res.layers) ? res.layers : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['arch'] = mount;
})();
