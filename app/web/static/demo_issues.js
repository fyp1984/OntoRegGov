/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   逐类问题处置（九类检查发现典型问题 × 失效层 × 管理策略 × 技术防护策略）
   · demo_issues.js
   视图 id：issues   容器：#issues_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   读：GET /api/issues/classes（问题类别读自知识口径，处置工单读自运行台账）
   写：POST /api/issues/disposals、PATCH /api/issues/disposals/{id}（指派）、
      POST /api/issues/disposals/{id}/advance（推进）、
      POST /api/issues/disposals/{id}/close（关闭，须处置证据）、
      DELETE /api/issues/disposals/{id}（移除）
   前后端双重校验：指派须组织 + 岗位；关闭须「待复检」且证据非空；失败 VALIDATION_FAILED。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    classes: '/api/issues/classes',
    disposals: '/api/issues/disposals',
    positions: '/api/admin/org-positions'
  };
  var MGMT_KEYS = ['制度', '培训', '流程规范', '审计检查'];

  var S = { data: null, positions: [], sel: null, layer: 'all',
            mode: 'none', target: null, busy: false };

  function rootEl() { return document.getElementById('issues_root'); }

  function layerFilter() {
    var layers = (S.data && S.data.summary && S.data.summary.layers) || {};
    return Object.keys(layers);
  }
  function classes() {
    var all = (S.data && S.data.classes) || [];
    if (S.layer === 'all') return all;
    return all.filter(function (c) { return c.layer === S.layer; });
  }
  function disposals() { return (S.data && S.data.disposals) || []; }
  function disposalOf(no) {
    return disposals().filter(function (d) { return d.issueNo === no && d.status !== 'closed'; })[0] || null;
  }
  function targetDisposal() {
    return disposals().filter(function (d) { return d.disposalId === S.target; })[0] || null;
  }
  function orgNames() {
    var seen = {}, out = [];
    S.positions.forEach(function (p) {
      if (p.orgNodeName && !seen[p.orgNodeName]) { seen[p.orgNodeName] = 1; out.push(p.orgNodeName); }
    });
    return out;
  }
  function posNamesOf(org) {
    return S.positions.filter(function (p) { return p.orgNodeName === org; })
      .map(function (p) { return p.name; });
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<label class="muted" for="issues_layer" style="margin:0">失效层</label>' +
        '<select id="issues_layer" title="按失效层筛选" aria-label="按失效层筛选"></select>' +
        '<button class="ghost" id="issues_refresh" title="重新拉取问题清单与处置工单" aria-label="刷新">刷新</button>' +
        '<span class="muted">每一类已识别的问题同时落到管理策略与技术防护策略，两组统一收口到「证据与验收」；下发处置工单后按状态机流转。</span>' +
      '</div>' +
      '<div id="issues_msg"></div>' +
      '<div id="issues_form"></div>' +
      '<div id="issues_split">' + DZ.skeleton(5) + '</div>' +
      '<div class="card"><h3 id="issues_disp_title">处置工单</h3>' +
        '<div id="issues_disp" class="dz-table-wrap">' + DZ.skeleton(4) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var sel = document.getElementById('issues_layer');
    if (sel) sel.onchange = function () { S.layer = this.value; renderSplit(); };
    var btn = document.getElementById('issues_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function setMsg(html) { DZ.render('#issues_msg', html || ''); }

  // ------------------------------------------------------------- 表单区
  function renderForm() {
    var box = document.getElementById('issues_form');
    if (!box) return;
    if (S.mode === 'none') { box.innerHTML = ''; return; }
    if (S.mode === 'assign') { renderAssignForm(box); return; }
    if (S.mode === 'close') { renderCloseForm(box); return; }
  }

  function renderAssignForm(box) {
    var d = targetDisposal();
    if (!d) { box.innerHTML = ''; return; }
    var orgs = orgNames();
    var orgOpts = '<option value="">请选择责任组织</option>' + orgs.map(function (o) {
      return '<option value="' + DZ.esc(o) + '">' + DZ.esc(o) + '</option>';
    }).join('');
    box.innerHTML = '<div class="card"><h3>指派处置责任 · ' + DZ.esc(d.issueName) + '</h3>' +
      '<div class="grid2">' +
        '<div>' +
          '<label for="ix_org">责任组织（必填）</label>' +
          '<select id="ix_org">' + orgOpts + '</select>' +
        '</div>' +
        '<div>' +
          '<label for="ix_pos">责任岗位（必填）</label>' +
          '<select id="ix_pos" disabled><option value="">请先选择责任组织</option></select>' +
        '</div>' +
      '</div>' +
      '<label for="ix_plan">处置方案</label>' +
      '<input id="ix_plan" placeholder="例如：统一责任矩阵，落到场景、岗位、审批节点" maxlength="120" value="' + DZ.esc(d.plan || '') + '">' +
      '<div class="dz-actions">' +
        '<button id="ix_org_submit" title="提交指派">提交指派</button>' +
        '<button class="ghost" id="ix_org_cancel" title="取消">取消</button>' +
      '</div></div>';
    var orgSel = document.getElementById('ix_org');
    var posSel = document.getElementById('ix_pos');
    if (orgSel && posSel) {
      orgSel.onchange = function () {
        var names = posNamesOf(this.value);
        posSel.disabled = !names.length;
        posSel.innerHTML = names.length
          ? '<option value="">请选择责任岗位</option>' + names.map(function (n) {
              return '<option value="' + DZ.esc(n) + '">' + DZ.esc(n) + '</option>';
            }).join('')
          : '<option value="">请先选择责任组织</option>';
      };
    }
    var sub = document.getElementById('ix_org_submit');
    if (sub) sub.onclick = submitAssign;
    var can = document.getElementById('ix_org_cancel');
    if (can) can.onclick = function () { S.mode = 'none'; S.target = null; renderForm(); };
  }

  function renderCloseForm(box) {
    var d = targetDisposal();
    if (!d) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="card"><h3>关闭处置工单 · ' + DZ.esc(d.issueName) + '</h3>' +
      '<div class="form-narrow">' +
        '<label for="ix_evidence">处置证据（必填：复检与验收记录）</label>' +
        '<input id="ix_evidence" placeholder="例如：责任矩阵复核单、审批链流转日志、一致性核查记录" maxlength="120">' +
        '<div class="dz-actions">' +
          '<button id="ix_close_submit" title="关闭工单">关闭工单</button>' +
          '<button class="ghost" id="ix_close_cancel" title="取消">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('ix_close_submit');
    if (sub) sub.onclick = submitClose;
    var can = document.getElementById('ix_close_cancel');
    if (can) can.onclick = function () { S.mode = 'none'; S.target = null; renderForm(); };
  }

  // ------------------------------------------------------------- 左列表 / 右详情
  function renderSplit() {
    var box = document.getElementById('issues_split');
    if (!box) return;
    var list = classes();
    if (!list.length) { box.innerHTML = DZ.empty('当前筛选条件下暂无问题类别'); return; }
    if (!S.sel || !list.some(function (c) { return c.no === S.sel; })) S.sel = list[0].no;
    box.innerHTML = '<div class="dz-split">' +
      '<div class="dz-side"><div class="card"><h3>问题类别（' + list.length + '）</h3>' +
        '<div id="issues_list"></div></div></div>' +
      '<div class="dz-main" id="issues_detail"></div>' +
    '</div>';
    renderList(list);
    renderDetail();
  }

  function renderList(list) {
    var box = document.getElementById('issues_list');
    if (!box) return;
    box.innerHTML = '<div class="pick-list" style="grid-template-columns:1fr">' +
      list.map(function (c) {
        var on = c.no === S.sel;
        var style = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
        var inflight = disposalOf(c.no) ? ' ' + DZ.badge('warn', '在办') : '';
        return '<div class="pick" data-no="' + DZ.esc(c.no) + '" role="button" tabindex="0"' + style +
          ' aria-label="查看问题类别 ' + DZ.esc(c.name) + '" title="查看该类处置策略">' +
          '<div style="min-width:0;flex:1">' +
            '<div class="pick-name" style="font-weight:600">' + DZ.esc(c.no) + ' ' + DZ.esc(c.name) + inflight + '</div>' +
            '<div class="row" style="gap:6px;margin-top:6px">' + DZ.pill(c.layer) + '</div>' +
          '</div>' +
        '</div>';
      }).join('') + '</div>';
    box.querySelectorAll('.pick').forEach(function (el) {
      var open = function () { S.sel = el.dataset.no; renderList(list); renderDetail(); };
      el.onclick = open;
      el.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
    });
  }

  function renderDetail() {
    var main = document.getElementById('issues_detail');
    if (!main) return;
    var c = ((S.data && S.data.classes) || []).filter(function (x) { return x.no === S.sel; })[0];
    if (!c) { main.innerHTML = DZ.empty('请选择左侧问题类别查看处置策略'); return; }

    var mgmtRows = MGMT_KEYS.map(function (k) {
      var v = (c.mgmt || {})[k] || '—';
      return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
        '<span class="dz-metric-v" style="font-weight:400;text-align:right;max-width:70%">' + DZ.esc(v) + '</span></div>';
    }).join('');
    var techPills = (c.tech || []).length
      ? c.tech.map(function (t) { return DZ.pill(t); }).join(' ')
      : '<span class="muted">—</span>';
    var evList = (c.evidence || []).length
      ? '<ul style="margin:4px 0 0 18px">' + c.evidence.map(function (e) { return '<li>' + DZ.esc(e) + '</li>'; }).join('') + '</ul>'
      : '<div class="muted">—</div>';
    var inflight = disposalOf(c.no);
    var actBtn = inflight
      ? '<span class="muted">已有在办处置工单，可在下方工单列表推进</span>'
      : '<button data-create="' + DZ.esc(c.no) + '" title="针对该类问题下发一张处置工单">下发处置工单</button>';

    main.innerHTML = '<div class="card">' +
      '<h3>' + DZ.esc(c.no) + ' ' + DZ.esc(c.name) + ' ' + DZ.pill('失效层 · ' + c.layer) + '</h3>' +
      '<h4>管理策略（制度 / 培训 / 流程规范 / 审计检查）</h4>' + mgmtRows +
      '<h4>技术防护策略</h4><div class="row" style="gap:6px">' + techPills + '</div>' +
      '<h4>证据与验收</h4>' +
        '<div class="why">' +
          '<div><b>验收判据：</b>' + DZ.esc(c.accept || '—') + '</div>' +
          '<div style="margin-top:6px"><b>应留证据：</b></div>' + evList +
        '</div>' +
      '<div class="dz-actions">' + actBtn + '</div>' +
    '</div>';
    var cb = main.querySelector('[data-create]');
    if (cb) cb.onclick = function () { createDisposal(cb.getAttribute('data-create')); };
  }

  // ------------------------------------------------------------- 处置工单表
  var FLOW_BTNS = {
    open: [{ act: 'assign', label: '指派责任' }, { act: 'del', label: '移除' }],
    assigned: [{ act: 'advance', label: '推进至整改中' }, { act: 'del', label: '移除' }],
    in_progress: [{ act: 'advance', label: '推进至待复检' }, { act: 'del', label: '移除' }],
    recheck: [{ act: 'close', label: '关闭工单' }, { act: 'del', label: '移除' }],
    closed: [{ act: 'del', label: '移除' }]
  };

  function statusBadge(st, label) {
    if (st === 'closed') return DZ.badge('ok', label || '已关闭');
    if (st === 'recheck') return DZ.badge('warn', label || '待复检');
    if (st === 'in_progress') return DZ.badge('warn', label || '整改中');
    if (st === 'assigned') return DZ.badge('ok', label || '已指派');
    return DZ.badge('unk', label || '待处理');
  }

  function renderDisposals() {
    var box = document.getElementById('issues_disp');
    var title = document.getElementById('issues_disp_title');
    var rows = disposals();
    if (title) title.textContent = '处置工单（' + rows.length + '）';
    if (!box) return;
    if (!rows.length) {
      box.innerHTML = DZ.empty('暂无处置工单', '<span class="muted">在右侧选择一类问题，点击「下发处置工单」开始流转</span>');
      return;
    }
    box.innerHTML = '<table>' +
      '<thead><tr><th style="min-width:170px">问题类别</th><th>失效层</th><th style="width:96px">状态</th>' +
        '<th style="min-width:120px">责任组织</th><th style="min-width:110px">责任岗位</th>' +
        '<th style="min-width:200px">处置方案 / 证据</th><th style="min-width:200px">操作</th></tr></thead>' +
      '<tbody>' + rows.map(function (d) {
        var btns = (FLOW_BTNS[d.status] || []).map(function (b) {
          var cls = b.act === 'del' ? ' class="ghost"' : '';
          return '<button' + cls + ' data-act="' + b.act + '" data-id="' + DZ.esc(d.disposalId) +
            '" title="' + DZ.esc(b.label) + '">' + DZ.esc(b.label) + '</button>';
        }).join(' ');
        var detail = '<div>' + DZ.esc(d.plan || '—') + '</div>' +
          (d.evidence ? '<div class="muted">证据：' + DZ.esc(d.evidence) + '</div>' : '');
        return '<tr>' +
          '<td><b>' + DZ.esc(d.issueNo) + ' ' + DZ.esc(d.issueName) + '</b></td>' +
          '<td>' + DZ.pill(d.layer) + '</td>' +
          '<td>' + statusBadge(d.status, d.statusLabel) + '</td>' +
          '<td>' + DZ.esc(d.org || '—') + '</td>' +
          '<td>' + DZ.esc(d.position || '—') + '</td>' +
          '<td>' + detail + '</td>' +
          '<td><div class="dz-actions" style="margin:0">' + btns + '</div></td>' +
        '</tr>';
      }).join('') + '</tbody></table>' +
      '<div class="muted" style="margin-top:8px">状态机：待处理 →（指派责任）已指派 → 整改中 → 待复检 →（登记处置证据）已关闭。</div>';
    box.querySelectorAll('[data-act]').forEach(function (b) {
      b.onclick = function () { onAction(b.getAttribute('data-act'), b.getAttribute('data-id')); };
    });
  }

  // ------------------------------------------------------------- 动作
  function onAction(act, id) {
    if (act === 'assign') { S.mode = 'assign'; S.target = id; renderForm(); scrollForm(); return; }
    if (act === 'close') { S.mode = 'close'; S.target = id; renderForm(); scrollForm(); return; }
    if (act === 'advance') { advance(id); return; }
    if (act === 'del') { removeDisposal(id); return; }
  }

  function scrollForm() {
    var f = document.getElementById('issues_form');
    if (f && f.scrollIntoView) f.scrollIntoView({ block: 'nearest' });
  }

  async function createDisposal(issueNo) {
    if (S.busy) return;
    S.busy = true;
    setMsg(DZ.banner('', '下发中…'));
    var res = await DZ.post(API.disposals, { issueNo: issueNo });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '下发失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('下发失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('处置工单已下发，已写入审计留痕', 'ok');
    await load(true);
  }

  async function submitAssign() {
    if (S.busy) return;
    var d = targetDisposal();
    if (!d) { setMsg(DZ.banner('bad', '工单不存在')); return; }
    var org = ((document.getElementById('ix_org') || {}).value || '').trim();
    var pos = ((document.getElementById('ix_pos') || {}).value || '').trim();
    var plan = ((document.getElementById('ix_plan') || {}).value || '').trim();
    if (!org) { setMsg(DZ.banner('bad', '请选择责任组织')); DZ.toast('请选择责任组织', 'bad'); return; }
    if (!pos) { setMsg(DZ.banner('bad', '请选择责任岗位')); DZ.toast('请选择责任岗位', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '指派中…'));
    var res = await DZ.patch(API.disposals + '/' + encodeURIComponent(d.disposalId), { org: org, position: pos, plan: plan });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '指派失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('指派失败：' + m, 'bad'); return;
    }
    setMsg(''); DZ.toast('已指派责任，状态置为已指派', 'ok');
    S.mode = 'none'; S.target = null; renderForm();
    await load(true);
  }

  async function submitClose() {
    if (S.busy) return;
    var d = targetDisposal();
    if (!d) { setMsg(DZ.banner('bad', '工单不存在')); return; }
    var evidence = ((document.getElementById('ix_evidence') || {}).value || '').trim();
    if (!evidence) { setMsg(DZ.banner('bad', '关闭工单须登记处置证据（复检与验收记录）')); DZ.toast('请填写处置证据', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '关闭中…'));
    var res = await DZ.post(API.disposals + '/' + encodeURIComponent(d.disposalId) + '/close', { evidence: evidence });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '关闭失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('关闭失败：' + m, 'bad'); return;
    }
    setMsg(''); DZ.toast('处置工单已关闭', 'ok');
    S.mode = 'none'; S.target = null; renderForm();
    await load(true);
  }

  async function advance(id) {
    if (S.busy) return;
    S.busy = true;
    setMsg(DZ.banner('', '推进中…'));
    var res = await DZ.post(API.disposals + '/' + encodeURIComponent(id) + '/advance', {});
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '推进失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('推进失败：' + m, 'bad'); return;
    }
    setMsg(''); DZ.toast('工单已推进至「' + (res.statusLabel || '') + '」', 'ok');
    await load(true);
  }

  async function removeDisposal(id) {
    if (S.busy) return;
    S.busy = true;
    var res = await DZ.del(API.disposals + '/' + encodeURIComponent(id));
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('移除失败：' + m, 'bad'); return;
    }
    setMsg(''); DZ.toast('处置工单已移除', 'ok');
    if (S.target === id) { S.mode = 'none'; S.target = null; renderForm(); }
    await load(true);
  }

  // ------------------------------------------------------------- 装载
  function renderLayerOptions() {
    var sel = document.getElementById('issues_layer');
    if (!sel) return;
    sel.innerHTML = '<option value="all">全部</option>' + layerFilter().map(function (l) {
      return '<option value="' + DZ.esc(l) + '"' + (l === S.layer ? ' selected' : '') + '>' + DZ.esc(l) + '</option>';
    }).join('');
  }

  async function load(force) {
    if (S.data && !force) {
      renderLayerOptions(); renderSplit(); renderForm(); renderDisposals();
      return;
    }
    var box = document.getElementById('issues_split');
    if (box) box.innerHTML = DZ.skeleton(5);
    var out = await Promise.all([DZ.get(API.classes), DZ.get(API.positions)]);
    var res = out[0], pos = out[1];
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '问题清单加载失败';
      if (box) box.innerHTML = DZ.banner('bad', msg, function () { load(true); });
      DZ.render('#issues_disp', DZ.empty('处置工单暂不可用'));
      return;
    }
    S.data = res;
    S.positions = (pos && !pos.error && Array.isArray(pos.positions))
      ? pos.positions.filter(function (p) { return p.status === 'active'; }) : [];
    renderLayerOptions(); renderSplit(); renderForm(); renderDisposals();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['issues'] = mount;
})();
