/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   能力域目录（十四能力域 × 能力实例接入登记：输入项 / 输出项 / 状态）
   · demo_capability.js
   视图 id：capability   容器：#capability_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/capabilities（域目录读自方法论口径，实例读自运行台账）
   写操作：POST /api/capabilities/instances、PATCH /api/capabilities/instances/{id}、
          DELETE /api/capabilities/instances/{id}（前后端双重校验，失败 VALIDATION_FAILED）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    list: '/api/capabilities',
    create: '/api/capabilities/instances'
  };

  var S = { data: null, showForm: false, busy: false };

  function rootEl() { return document.getElementById('capability_root'); }

  function statusBadge(st) {
    if (st === 'ready') return DZ.badge('ok', '已有实例');
    return DZ.badge('unk', '待接入');
  }

  function instanceStatusBadge(st) {
    if (st === 'active') return DZ.badge('ok', '已接入');
    if (st === 'suspended') return DZ.badge('unk', '已停用');
    return DZ.badge('unk', st || '—');
  }

  function checkTags(checks) {
    var list = Array.isArray(checks) ? checks : [];
    if (!list.length) return '<span class="muted">—</span>';
    return list.map(function (c) { return DZ.pill(c); }).join(' ');
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="capability_new" title="登记一个新的能力实例" aria-label="登记能力实例">登记能力实例</button>' +
        '<button class="ghost" id="capability_refresh" title="重新拉取能力域目录" aria-label="刷新能力域目录">刷新</button>' +
        '<span class="muted">按工作环节编排的能力域目录：逐项对应检查主题与接入后的交付物；接入实例须登记输入项与输出项。</span>' +
      '</div>' +
      '<div id="capability_msg"></div>' +
      '<div id="capability_form"></div>' +
      '<div id="capability_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="capability_cards">' + DZ.skeleton(6) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('capability_new');
    if (nb) nb.onclick = function () { S.showForm = !S.showForm; renderForm(); };
    var rb = document.getElementById('capability_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderForm();
    load(false);
  }

  function kinds() { return (S.data && S.data.kinds) || []; }
  function domains() { return (S.data && S.data.capabilities) || []; }

  function renderForm() {
    var box = document.getElementById('capability_form');
    if (!box) return;
    if (!S.showForm) { box.innerHTML = ''; return; }
    var domOpts = domains().map(function (d) {
      return '<option value="' + DZ.esc(d.no) + '">能力域 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + '</option>';
    }).join('');
    var kindOpts = kinds().map(function (k) {
      return '<option value="' + DZ.esc(k) + '">' + DZ.esc(k) + '</option>';
    }).join('');
    box.innerHTML = '<div class="card"><h3>登记能力实例</h3>' +
      '<div class="form-narrow">' +
        '<label for="cap_domain">所属能力域</label>' +
        '<select id="cap_domain">' + domOpts + '</select>' +
        '<label for="cap_name">实例名称</label>' +
        '<input id="cap_name" placeholder="例如：数据分级插件" maxlength="40">' +
        '<label for="cap_kind">能力类别</label>' +
        '<select id="cap_kind">' + kindOpts + '</select>' +
        '<div class="grid2" style="gap:12px">' +
          '<div><label for="cap_input">输入项（调用入参）</label>' +
            '<input id="cap_input" placeholder="例如：待分级字段清单与分级规则" maxlength="80"></div>' +
          '<div><label for="cap_output">输出项（返回结果）</label>' +
            '<input id="cap_output" placeholder="例如：分级结果与打标记录" maxlength="80"></div>' +
        '</div>' +
        '<div class="dz-actions">' +
          '<button id="cap_submit" title="提交登记">提交登记</button>' +
          '<button class="ghost" id="cap_cancel" title="取消登记">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('cap_submit');
    if (sub) sub.onclick = submitCreate;
    var can = document.getElementById('cap_cancel');
    if (can) can.onclick = function () { S.showForm = false; renderForm(); };
  }

  function setMsg(html) { DZ.render('#capability_msg', html || ''); }

  async function submitCreate() {
    if (S.busy) return;
    var domainNo = Number((document.getElementById('cap_domain') || {}).value);
    var name = ((document.getElementById('cap_name') || {}).value || '').trim();
    var kind = ((document.getElementById('cap_kind') || {}).value || '').trim();
    var input = ((document.getElementById('cap_input') || {}).value || '').trim();
    var output = ((document.getElementById('cap_output') || {}).value || '').trim();
    if (!name) { setMsg(DZ.banner('bad', '请填写能力实例名称')); DZ.toast('请填写能力实例名称', 'bad'); return; }
    if (!input) { setMsg(DZ.banner('bad', '请填写输入项（调用入参）')); DZ.toast('请填写输入项', 'bad'); return; }
    if (!output) { setMsg(DZ.banner('bad', '请填写输出项（返回结果）')); DZ.toast('请填写输出项', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '登记中…'));
    var res = await DZ.post(API.create, { domainNo: domainNo, name: name, kind: kind, input: input, output: output });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '登记失败';
      setMsg(DZ.banner('bad', m));
      DZ.toast('登记失败：' + m, 'bad');
      return;
    }
    setMsg('');
    DZ.toast('能力实例已登记，已写入审计留痕', 'ok');
    S.showForm = false;
    await load(true);
  }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#capability_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('能力域总数', DZ.number(s.total), '按工作环节编排', '') +
      DZ.kpi('已有实例', DZ.number(s.ready), '已接入能力实例', 'ok') +
      DZ.kpi('待接入', DZ.number(s.planned), '尚无能力实例', 'warn') +
      DZ.kpi('实例总数', DZ.number(s.instances), '已登记能力实例', '') +
      DZ.kpi('已停用', DZ.number((Number(s.instances) || 0) - (Number(s.active) || 0)), '暂停调用', 'unk') +
    '</div>');
  }

  function instanceRows(insts) {
    if (!insts.length) return '<div class="muted" style="margin-top:8px">暂无已接入能力实例。</div>';
    var rows = insts.map(function (it) {
      var toggleLabel = it.status === 'active' ? '停用' : '启用';
      var toggleTo = it.status === 'active' ? 'suspended' : 'active';
      return '<tr>' +
        '<td><b>' + DZ.esc(it.name) + '</b></td>' +
        '<td>' + DZ.esc(it.kind) + '</td>' +
        '<td>' + DZ.esc(it.input || '—') + '</td>' +
        '<td>' + DZ.esc(it.output || '—') + '</td>' +
        '<td>' + instanceStatusBadge(it.status) + '</td>' +
        '<td>' + DZ.esc(it.owner || '—') + '</td>' +
        '<td><div class="dz-actions">' +
          '<button class="ghost" data-act="toggle" data-id="' + DZ.esc(it.instanceId) + '" ' +
            'data-to="' + toggleTo + '" title="' + toggleLabel + '该实例">' + toggleLabel + '</button>' +
          '<button class="ghost" data-act="del" data-id="' + DZ.esc(it.instanceId) + '" title="移除该实例">移除</button>' +
        '</div></td>' +
      '</tr>';
    }).join('');
    return '<div class="dz-table-wrap" style="margin-top:8px"><table>' +
      '<thead><tr><th style="min-width:150px">实例名称</th><th>能力类别</th>' +
        '<th style="min-width:180px">输入项</th><th style="min-width:180px">输出项</th>' +
        '<th style="width:90px">状态</th><th style="width:110px">登记人</th>' +
        '<th style="width:150px">操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function renderCards(items) {
    var box = document.getElementById('capability_cards');
    if (!box) return;
    if (!items.length) { box.innerHTML = DZ.empty('暂无能力域'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px">' +
      items.map(function (d) {
        return '<div class="card">' +
          '<h3>能力域 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + ' ' + statusBadge(d.status) + '</h3>' +
          '<div class="dz-cite"><div>' + DZ.esc(d.usage || '—') + '</div></div>' +
          '<div class="dz-metric"><span class="dz-metric-k">对应检查主题</span>' +
            '<span class="dz-metric-v" style="text-align:right">' + checkTags(d.checks) + '</span></div>' +
          '<div class="dz-metric"><span class="dz-metric-k">接入后交付物</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(d.deliverable || '—') + '</span></div>' +
          '<h4>已接入能力实例（' + DZ.number(d.instanceCount || 0) + '）</h4>' +
          instanceRows(Array.isArray(d.instances) ? d.instances : []) +
        '</div>';
      }).join('') + '</div>';
    bindActions();
  }

  function bindActions() {
    var box = document.getElementById('capability_cards');
    if (!box) return;
    box.querySelectorAll('[data-act]').forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute('data-id');
        var act = btn.getAttribute('data-act');
        if (act === 'toggle') toggleInstance(id, btn.getAttribute('data-to'));
        else if (act === 'del') removeInstance(id);
      };
    });
  }

  async function toggleInstance(id, to) {
    setMsg(DZ.banner('', '处理中…'));
    var res = await DZ.patch(API.create + '/' + encodeURIComponent(id), { status: to });
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '操作失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast(to === 'active' ? '能力实例已启用' : '能力实例已停用', 'ok');
    await load(true);
  }

  async function removeInstance(id) {
    setMsg(DZ.banner('', '处理中…'));
    var res = await DZ.del(API.create + '/' + encodeURIComponent(id));
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m)); DZ.toast(m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('能力实例已移除，已写入审计留痕', 'ok');
    await load(true);
  }

  async function load(force) {
    if (S.data && !force) {
      renderForm();
      renderKpis(S.data.summary);
      renderCards(Array.isArray(S.data.capabilities) ? S.data.capabilities : []);
      return;
    }
    var box = document.getElementById('capability_cards');
    if (box) box.innerHTML = DZ.skeleton(6);
    var res = await DZ.get(API.list);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '能力域目录加载失败';
      DZ.render('#capability_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#capability_cards', DZ.empty('能力域目录不可读'));
      return;
    }
    S.data = res;
    renderForm();
    renderKpis(res.summary || {});
    renderCards(Array.isArray(res.capabilities) ? res.capabilities : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['capability'] = mount;
})();
