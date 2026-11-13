/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   场景与插件（E1 场景包 / E2 工具插件）
   · demo_ext.js
   视图 id：ext   容器：#ext_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var TAB_SC = 'sc';   // 场景包页签
  var TAB_PL = 'pl';   // 工具插件页签

  // 后端 capability 英文键 → 中文能力名
  var CAP = {
    grading: '数据分级', classification: '数据分类', masking: '数据脱敏',
    scan: '敏感数据识别', watermark: '水印'
  };
  var IND = { bank: '银行', insurance: '保险' };
  // 五元组"知识"字段的中文标签（scope_json 仅返回对象，键名因场景而异）
  var KN_LABEL = { lines: '条线', docs: '文号', reports: '报表', domains: '领域', scope: '范围' };

  // 模块状态（视图可重入，保留选择态）
  var S = {
    tab: TAB_SC,
    packs: null,        // null = 未加载
    selPack: null,
    creating: false,    // 是否展示"新建场景包"表单
    launching: false,
    plugins: null,
    selPlugin: null,
    invocations: null,
    invLimit: 50
  };

  function rootEl() { return document.getElementById('ext_root'); }
  function esc(s) { return DZ.esc(s); }
  function j(v) { try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); } }

  // 插件运行状态徽章（在线=ok / 降级=warn；文字与颜色并存，不只靠颜色）
  function onlineBadge(st) {
    var t = String(st == null ? '' : st);
    if (t === '在线' || t === 'ok' || t === 'active') return DZ.badge('ok', '在线');
    if (t === '降级' || t === 'degraded') return DZ.badge('warn', '降级');
    if (t === '离线' || t === 'offline' || t === 'down') return DZ.badge('bad', '离线');
    return DZ.badge('unk', t || '未知');
  }
  // 调用记录状态徽章
  function invStatusBadge(st) {
    var t = String(st || '');
    if (t === 'ok') return DZ.badge('ok', '成功');
    if (t === 'degraded') return DZ.badge('warn', '降级');
    if (t === 'failed' || t === 'error') return DZ.badge('bad', '失败');
    return DZ.badge('unk', t || '—');
  }
  function builtinBadge(b) { return b ? DZ.badge('ok', '内置种子') : DZ.badge('unk', '自定义'); }
  function capLabel(c) { return CAP[c] || c || '—'; }
  function indLabel(i) { return IND[i] || i || '—'; }

  // 五元组"知识"摘要（后端 scope 为任意对象）
  function knowledgeText(k) {
    if (k == null) return '—';
    if (typeof k !== 'object') return String(k);
    var keys = Object.keys(k);
    if (!keys.length) return '—';
    return keys.map(function (key) {
      var v = k[key];
      var label = KN_LABEL[key] || key;
      if (Array.isArray(v)) return label + '：' + (v.length ? v.join('、') : '—');
      if (v && typeof v === 'object') return label + '：' + j(v);
      return label + '：' + String(v);
    }).join('；');
  }
  function splitList(s) {
    return String(s || '').split(/[,，、\s]+/).map(function (x) { return x.trim(); }).filter(Boolean);
  }

  /* ============================================================
     外壳与页签
     ============================================================ */
  function renderShell() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML =
      DZ.sectionTitle('场景与插件') +
      '<div id="ext_tabs"></div>' +
      '<div id="ext_body"></div>';
  }

  function renderTabs() {
    var items = [
      { key: TAB_SC, label: '场景包', count: S.packs ? S.packs.length : null },
      { key: TAB_PL, label: '工具插件', count: S.plugins ? S.plugins.length : null }
    ];
    DZ.tabs(document.getElementById('ext_tabs'), items, S.tab, function (k) {
      S.tab = k;
      renderTab();
    });
  }

  function renderTab() {
    renderTabs();
    var body = document.getElementById('ext_body');
    if (!body) return;
    if (S.tab === TAB_SC) renderScenarios(body);
    else renderPlugins(body);
  }

  /* ============================================================
     A. 场景包（E1）
     ============================================================ */
  function renderScenarios(body) {
    body.innerHTML =
      '<div class="dz-toolbar">' +
        '<button id="ext_new_pack" title="新建场景包（演示底座零改动扩展）" aria-label="新建场景包">＋ 新建场景包</button>' +
        '<button class="ghost" id="ext_refresh_packs" title="刷新场景包列表" aria-label="刷新场景包列表">刷新</button>' +
      '</div>' +
      '<div id="ext_sc_area"></div>';
    document.getElementById('ext_new_pack').onclick = function () {
      S.creating = true;
      renderScenariosArea();
    };
    document.getElementById('ext_refresh_packs').onclick = function () { loadPacks(true); };
    renderScenariosArea();
  }

  function renderScenariosArea() {
    var area = document.getElementById('ext_sc_area');
    if (!area) return;

    if (S.creating) { area.innerHTML = createFormHtml(); bindCreateForm(); return; }

    if (S.packs === null) { area.innerHTML = DZ.skeleton(4); loadPacks(); return; }

    if (!S.packs.length) {
      area.innerHTML = DZ.empty('暂无场景包', '<button id="ext_empty_new" title="新建场景包">＋ 新建场景包</button>');
      var b = document.getElementById('ext_empty_new');
      if (b) b.onclick = function () { S.creating = true; renderScenariosArea(); };
      return;
    }

    area.innerHTML =
      '<div class="dz-split">' +
        '<div class="dz-side"><div class="card"><h3>场景包（' + S.packs.length + '）</h3>' +
          '<div id="ext_pack_list"></div></div></div>' +
        '<div class="dz-main" id="ext_pack_main"></div>' +
      '</div>';

    renderPackList();
    if (S.selPack) renderPackDetail(S.selPack);
    else DZ.render('#ext_pack_main', DZ.empty('请选择左侧场景包查看五元组'));
  }

  function renderPackList() {
    var box = document.getElementById('ext_pack_list');
    if (!box) return;
    box.innerHTML = '<div class="pick-list" style="grid-template-columns:1fr">' +
      S.packs.map(function (p) {
        var on = p.packId === S.selPack;
        var sel = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
        return '<div class="pick" data-pack="' + esc(p.packId) + '" role="button" tabindex="0"' + sel +
          ' aria-label="查看场景包 ' + esc(p.name) + '" title="查看五元组详情">' +
          '<div style="min-width:0;flex:1">' +
            '<div class="pick-name" style="font-weight:600">' + esc(p.name) + '</div>' +
            '<div class="muted" style="margin-top:4px">' + esc(indLabel(p.industry)) + ' · ' + esc(knowledgeText(p.scope)) + '</div>' +
            '<div class="row" style="gap:6px;margin-top:6px">' + onlineBadge(p.status) + builtinBadge(p.builtin) +
              DZ.pill('产出 ' + (p.reportTemplate || '—')) + '</div>' +
          '</div>' +
        '</div>';
      }).join('') + '</div>';

    box.querySelectorAll('.pick').forEach(function (el) {
      var open = function () { S.selPack = el.dataset.pack; renderPackList(); renderPackDetail(S.selPack); };
      el.onclick = open;
      el.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
    });
  }

  function renderPackDetail(packId) {
    var main = document.getElementById('ext_pack_main');
    if (!main) return;
    main.innerHTML = DZ.skeleton(5);
    DZ.get('/api/scenario-packs/' + encodeURIComponent(packId)).then(function (res) {
      // 视图可能已被重渲染 / 选择已变更
      var cur = document.getElementById('ext_pack_main');
      if (!cur || S.selPack !== packId) return;
      if (res && res.error) {
        cur.innerHTML = DZ.banner('bad', res.error.message || '场景包详情加载失败', function () { renderPackDetail(packId); });
        return;
      }
      cur.innerHTML = packDetailHtml(res);
      bindPackDetail(res);
    });
  }

  function packDetailHtml(d) {
    var ft = d.fiveTuple || {};
    var nodes = [
      ['知识', knowledgeText(ft.knowledge)],
      ['检查项', ft.checks ? ('来源 ' + ft.checks) : '—'],
      ['作业', ft.jobs || '—'],
      ['判定', ft.verdict || '—'],
      ['产出', ft.output || '—']
    ];
    var flow = '<div class="dz-flow" role="list" aria-label="场景包五元组">' + nodes.map(function (n, i) {
      return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
        '<div class="dz-node on" role="listitem" title="' + esc(n[0] + '：' + n[1]) + '">' +
          '<div class="dz-node-title">' + esc(n[0]) + '</div>' +
          '<div class="muted" style="margin-top:4px;white-space:normal;max-width:180px">' + esc(n[1]) + '</div>' +
        '</div>';
    }).join('') + '</div>';

    var fields = (d.form && Array.isArray(d.form.fields)) ? d.form.fields : [];
    var fieldHtml = fields.length
      ? fields.map(function (f) { return DZ.pill(f); }).join(' ')
      : '<span class="muted">—</span>';

    return '<div class="card">' +
      '<h3>' + esc(d.name) + ' ' + onlineBadge(d.status) + builtinBadge(d.builtin) + '</h3>' +
      '<div class="row" style="gap:10px;margin-bottom:6px">' +
        '<span class="pill">行业 ' + esc(indLabel(d.industry)) + '</span>' +
        '<span class="pill">场景包编号 ' + esc(d.packId) + '</span>' +
        '<span class="pill">报告模板 ' + esc(d.reportTemplate || '—') + '</span>' +
      '</div>' +
      flow +
      '<div class="grid2" style="margin-top:14px">' +
        '<div>' +
          '<h4>表单字段</h4><div class="row" style="gap:6px">' + fieldHtml + '</div>' +
          '<h4>报告产出</h4><div class="dz-cite"><div>' + esc(d.reportTemplate || '—') + '</div></div>' +
        '</div>' +
        '<div>' +
          '<h4>启动演示实例</h4>' +
          '<button id="ext_launch" title="以该场景包创建一次自查任务实例（写入运行台账，不改动底座）" aria-label="启动演示实例">启动演示实例</button>' +
          '<div id="ext_launch_result" style="margin-top:10px"></div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function bindPackDetail(d) {
    var btn = document.getElementById('ext_launch');
    if (btn) btn.onclick = function () { doLaunch(d); };
  }

  function doLaunch(d) {
    if (S.launching) return;
    S.launching = true;
    var btn = document.getElementById('ext_launch');
    var box = document.getElementById('ext_launch_result');
    if (btn) { btn.disabled = true; btn.textContent = '启动中…'; }
    if (box) box.innerHTML = '<span class="muted">处理中…</span>';

    DZ.post('/api/scenario-packs/' + encodeURIComponent(d.packId) + '/launch', {}).then(function (res) {
      S.launching = false;
      if (btn) { btn.disabled = false; btn.textContent = '启动演示实例'; }
      if (res && res.error) {
        if (box) box.innerHTML = DZ.banner('bad', res.error.message || '启动失败', function () { doLaunch(d); });
        return;
      }
      DZ.toast('场景实例已启动', 'ok');
      if (box) {
        box.innerHTML =
          '<div class="why">已以场景包“' + esc(d.name) + '”启动演示实例，底座零改动。<br>' +
          '实例任务：<code>' + esc(res.launchedTaskId || '—') + '</code>' +
          '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
            '<button class="ghost" id="ext_goto_dsc" title="跳转到安全自查视图" aria-label="去自查视图查看">去自查视图查看</button>' +
          '</div></div>';
        var go = document.getElementById('ext_goto_dsc');
        if (go) go.onclick = function () {
          if (typeof window.showView === 'function') window.showView('dsc');
          else DZ.toast('自查视图不可用', 'warn');
        };
      }
    });
  }

  function createFormHtml() {
    return '<div class="card">' +
      '<h3>新建场景包（演示零代码扩展）</h3>' +
      '<div class="form-narrow">' +
        '<label for="np_name">场景包名称 <span class="muted">（必填）</span></label>' +
        '<input id="np_name" placeholder="如：反洗钱专项自查" title="场景包名称" aria-label="场景包名称">' +
        '<label for="np_industry">行业</label>' +
        '<select id="np_industry" title="行业" aria-label="行业">' +
          '<option value="bank">银行</option><option value="insurance">保险</option></select>' +
        '<label for="np_scope">适用范围（条线，逗号分隔）</label>' +
        '<input id="np_scope" placeholder="acct,credit" title="适用范围（条线）" aria-label="适用范围">' +
        '<label for="np_mapping">检查项来源文号</label>' +
        '<input id="np_mapping" value="jg24" title="检查项来源文号" aria-label="检查项来源文号">' +
        '<label for="np_form">表单字段（逗号分隔）</label>' +
        '<input id="np_form" value="orgName,cycle,topic" title="表单字段" aria-label="表单字段">' +
        '<label for="np_tpl">报告模板</label>' +
        '<input id="np_tpl" value="custom-v1" title="报告模板" aria-label="报告模板">' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
          '<button id="np_submit" title="提交创建" aria-label="创建场景包">创建场景包</button>' +
          '<button class="ghost" id="np_cancel" title="取消" aria-label="取消">取消</button>' +
        '</div>' +
        '<div id="np_msg"></div>' +
      '</div>' +
    '</div>';
  }

  function bindCreateForm() {
    var c = document.getElementById('np_cancel');
    if (c) c.onclick = function () { S.creating = false; renderScenariosArea(); };
    var s = document.getElementById('np_submit');
    if (s) s.onclick = submitCreate;
  }

  function submitCreate() {
    var nameEl = document.getElementById('np_name');
    var msg = document.getElementById('np_msg');
    var btn = document.getElementById('np_submit');
    var name = ((nameEl && nameEl.value) || '').trim();
    if (!name) { if (msg) msg.innerHTML = DZ.banner('bad', '请填写场景包名称'); return; }

    var body = {
      name: name,
      industry: (document.getElementById('np_industry') || {}).value || 'bank',
      scope: { lines: splitList((document.getElementById('np_scope') || {}).value) },
      mapping: { checkSource: (document.getElementById('np_mapping') || {}).value || '' },
      form: { fields: splitList((document.getElementById('np_form') || {}).value) },
      reportTemplate: (document.getElementById('np_tpl') || {}).value || 'custom-v1'
    };
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }

    DZ.post('/api/scenario-packs', body).then(function (res) {
      if (btn) { btn.disabled = false; btn.textContent = '创建场景包'; }
      if (res && res.error) {
        if (msg) msg.innerHTML = DZ.banner('bad', res.error.message || '创建失败');
        return;
      }
      DZ.toast('场景包已创建：' + ((res && res.packId) || ''), 'ok');
      S.creating = false;
      if (res && res.packId) S.selPack = res.packId;
      loadPacks(true);
    });
  }

  function loadPacks(force) {
    if (S.packs !== null && !force) { renderScenariosArea(); return; }
    S.packs = null;
    var area = document.getElementById('ext_sc_area');
    if (area) area.innerHTML = DZ.skeleton(4);
    DZ.get('/api/scenario-packs').then(function (res) {
      if (res && res.error) {
        var a = document.getElementById('ext_sc_area');
        if (a) a.innerHTML = DZ.banner('bad', res.error.message || '场景包加载失败', function () { loadPacks(true); });
        return;
      }
      S.packs = (res && Array.isArray(res.packs)) ? res.packs : [];
      if (!S.selPack || !S.packs.some(function (p) { return p.packId === S.selPack; })) {
        S.selPack = S.packs.length ? S.packs[0].packId : null;
      }
      if (S.tab === TAB_SC) { renderTabs(); renderScenariosArea(); }
    });
  }

  /* ============================================================
     B. 工具插件（E2）
     ============================================================ */
  function renderPlugins(body) {
    body.innerHTML =
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="ext_refresh_pl" title="刷新插件与调用记录" aria-label="刷新">刷新</button>' +
        '<label class="muted" for="ext_inv_limit" style="margin:0">调用记录条数</label>' +
        '<select id="ext_inv_limit" style="width:auto" title="调用记录条数" aria-label="调用记录条数">' +
          [20, 50, 100].map(function (n) { return '<option value="' + n + '"' + (n === S.invLimit ? ' selected' : '') + '>' + n + '</option>'; }).join('') +
        '</select>' +
        '<span class="muted">接入契约 · 可插拔 · 可回滚 · 主流程零改动</span>' +
      '</div>' +
      '<div class="card"><h3>插件列表</h3><div id="ext_pl_list"></div></div>' +
      '<div id="ext_invoke_area"></div>' +
      '<div class="card"><h3>调用记录</h3><div id="ext_inv_list"></div></div>';

    document.getElementById('ext_refresh_pl').onclick = function () { loadPlugins(true); loadInvocations(true); };
    document.getElementById('ext_inv_limit').onchange = function () {
      S.invLimit = Number(this.value) || 50;
      loadInvocations(true);
    };
    renderPluginList();
    renderInvokeArea();
    renderInvocationList();
  }

  function renderPluginList() {
    var box = document.getElementById('ext_pl_list');
    if (!box) return;
    if (S.plugins === null) { box.innerHTML = DZ.skeleton(5); loadPlugins(); return; }
    if (!S.plugins.length) {
      box.innerHTML = DZ.empty('暂无已注册插件', '<button id="ext_pl_refresh" title="刷新">刷新</button>');
      var b = document.getElementById('ext_pl_refresh');
      if (b) b.onclick = function () { loadPlugins(true); };
      return;
    }
    box.innerHTML = '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th>名称</th><th>能力</th><th>状态</th><th>厂商</th><th>响应时延（毫秒）</th>' +
      '<th>鉴权方式</th><th>限流</th><th>操作</th></tr></thead><tbody>' +
      S.plugins.map(function (p) {
        var on = p.pluginId === S.selPlugin;
        return '<tr data-plugin="' + esc(p.pluginId) + '"' + (on ? ' style="background:var(--brand-soft)"' : '') + '>' +
          '<td><b>' + esc(p.name) + '</b><br><span class="muted">' + esc(p.pluginId) + '</span></td>' +
          '<td>' + DZ.pill(capLabel(p.capability)) + '</td>' +
          '<td>' + onlineBadge(p.status) + '</td>' +
          '<td>' + esc(p.vendor || '—') + '</td>' +
          '<td>' + DZ.number(p.latencyMs) + '</td>' +
          '<td>' + esc(p.authType || '—') + '</td>' +
          '<td>' + esc(p.rateLimit || '—') + '</td>' +
          '<td><button class="ghost" data-invoke="' + esc(p.pluginId) + '" title="调用该插件" aria-label="调用 ' + esc(p.name) + '">调用</button></td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';

    box.querySelectorAll('[data-invoke]').forEach(function (btn) {
      btn.onclick = function (ev) { ev.stopPropagation(); selectPlugin(btn.dataset.invoke); };
    });
    box.querySelectorAll('tbody tr').forEach(function (tr) {
      tr.onclick = function () { selectPlugin(tr.dataset.plugin); };
    });
  }

  function selectPlugin(id) {
    S.selPlugin = id;
    renderPluginList();
    renderInvokeArea();
    var area = document.getElementById('ext_invoke_area');
    if (area && area.scrollIntoView) { try { area.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) { /* noop */ } }
  }

  function renderInvokeArea() {
    var area = document.getElementById('ext_invoke_area');
    if (!area) return;
    var p = (S.plugins || []).filter(function (x) { return x.pluginId === S.selPlugin; })[0];
    if (!p) { area.innerHTML = DZ.empty('请选择一个插件进行调用'); return; }

    var contract = {
      pluginId: p.pluginId,
      capability: p.capability,
      ioSchema: p.ioSchema || {},
      auth: { type: p.authType },
      rateLimit: p.rateLimit,
      endpoint: 'POST /api/plugins/' + p.pluginId + '/invoke',
      request: { taskId: 'string (可选)', input: 'object' },
      response: { invocationId: 'string', status: 'ok | degraded', output: 'object', latencyMs: 'number' }
    };

    area.innerHTML = '<div class="card"><h3>调用插件：' + esc(p.name) + ' ' + onlineBadge(p.status) + '</h3>' +
      '<div class="grid2">' +
        '<div>' +
          '<label for="ext_inv_task">任务编号（可选）</label>' +
          '<input id="ext_inv_task" placeholder="t-bank-2026q4" title="任务编号" aria-label="任务编号">' +
          '<label for="ext_inv_input">调用输入（JSON）</label>' +
          '<textarea id="ext_inv_input" rows="5" title="调用输入（JSON）" aria-label="调用输入（JSON）">' +
            esc(j({ text: '示例数据：客户姓名 张三 / 身份证 110101********1234' })) +
          '</textarea>' +
          '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
            '<button id="ext_inv_run" title="调用插件" aria-label="调用插件">调用</button>' +
          '</div>' +
        '</div>' +
        '<div id="ext_inv_result"><div class="muted">选择插件并点击“调用”，将展示调用编号 / 状态 / 输出 / 耗时。</div></div>' +
      '</div>' +
      '<h4>插件接入契约（可插拔 · 可回滚 · 主流程零改动）</h4>' +
      '<div class="dz-contract" aria-label="插件接入契约">' + esc(j(contract)) + '</div>' +
    '</div>';

    document.getElementById('ext_inv_run').onclick = function () { doInvoke(p); };
  }

  function doInvoke(p) {
    var btn = document.getElementById('ext_inv_run');
    var resBox = document.getElementById('ext_inv_result');
    var taskId = (document.getElementById('ext_inv_task') || {}).value || null;
    var raw = (document.getElementById('ext_inv_input') || {}).value || '';
    var input;
    try { input = raw.trim() ? JSON.parse(raw) : {}; }
    catch (e) {
      if (resBox) resBox.innerHTML = DZ.banner('bad', '输入不是合法 JSON：' + ((e && e.message) || e));
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '调用中…'; }
    if (resBox) resBox.innerHTML = '<span class="muted">处理中…</span>';

    DZ.post('/api/plugins/' + encodeURIComponent(p.pluginId) + '/invoke', { taskId: taskId, input: input })
      .then(function (res) {
        if (btn) { btn.disabled = false; btn.textContent = '调用'; }
        if (res && res.error) {
          if (resBox) resBox.innerHTML = DZ.banner('bad', res.error.message || '调用失败', function () { doInvoke(p); });
          return;
        }
        renderInvokeResult(res, p);
        loadInvocations(true);
      });
  }

  function renderInvokeResult(res, p) {
    var box = document.getElementById('ext_inv_result');
    if (!box) return;
    var degraded = res.status === 'degraded' || (res.output && res.output.routedToHuman);
    var html = '';
    if (degraded) {
      html += DZ.banner('warn', '插件“' + esc(p.name) + '”当前不可用，已降级为人工处理，主流程不阻断。');
    }
    html += '<div class="dz-metric"><span class="dz-metric-k">调用编号</span><span class="dz-metric-v">' + esc(res.invocationId || '—') + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">状态</span><span class="dz-metric-v">' + invStatusBadge(res.status) + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">耗时</span><span class="dz-metric-v">' + DZ.number(res.latencyMs) + ' 毫秒</span></div>';
    html += '<h4>输出</h4><div class="dz-contract">' + esc(j(res.output || {})) + '</div>';
    if (degraded) {
      html += '<div class="row" style="margin-top:10px;gap:8px">' +
        '<button class="ghost" id="ext_human" title="提示转人工确认" aria-label="转人工确认">转人工确认</button>' +
        '<span class="muted">降级路径不阻断主流程，结果转由人工复核确认。</span></div>';
    }
    box.innerHTML = html;
    var h = document.getElementById('ext_human');
    if (h) h.onclick = function () { DZ.toast('已提示：转人工确认（演示，不阻断主流程）', 'warn'); };
  }

  function renderInvocationList() {
    var box = document.getElementById('ext_inv_list');
    if (!box) return;
    if (S.invocations === null) { box.innerHTML = DZ.skeleton(4); loadInvocations(); return; }
    if (!S.invocations.length) { box.innerHTML = DZ.empty('暂无调用记录'); return; }
    box.innerHTML = '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th>时间</th><th>插件</th><th>任务</th><th>状态</th><th>响应时延（毫秒）</th><th>操作者</th></tr></thead><tbody>' +
      S.invocations.map(function (r) {
        var p = (S.plugins || []).filter(function (x) { return x.pluginId === r.pluginId; })[0];
        return '<tr>' +
          '<td>' + esc(DZ.date(r.createdAt)) + '</td>' +
          '<td>' + esc(p ? p.name : r.pluginId) + '<br><span class="muted">' + esc(r.pluginId || '') + '</span></td>' +
          '<td>' + esc(r.taskId || '—') + '</td>' +
          '<td>' + invStatusBadge(r.status) + '</td>' +
          '<td>' + DZ.number(r.latencyMs) + '</td>' +
          '<td>' + esc(r.actor || '—') + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>' +
      '<div class="muted" style="margin-top:8px">备注：该接口仅返回后端已归档的摘要字段（时间 / 插件 / 任务 / 状态 / 时延 / 操作者）；输入 / 输出内容由后端按调用编号关联，未在本接口展开。</div>';
  }

  function loadPlugins(force) {
    if (S.plugins !== null && !force) { renderPluginList(); renderInvokeArea(); return; }
    S.plugins = null;
    var box = document.getElementById('ext_pl_list');
    if (box) box.innerHTML = DZ.skeleton(5);
    DZ.get('/api/plugins').then(function (res) {
      if (res && res.error) {
        var b = document.getElementById('ext_pl_list');
        if (b) b.innerHTML = DZ.banner('bad', res.error.message || '插件加载失败', function () { loadPlugins(true); });
        return;
      }
      S.plugins = (res && Array.isArray(res.plugins)) ? res.plugins : [];
      if (!S.selPlugin || !S.plugins.some(function (p) { return p.pluginId === S.selPlugin; })) {
        S.selPlugin = S.plugins.length ? S.plugins[0].pluginId : null;
      }
      if (S.tab === TAB_PL) { renderTabs(); renderPluginList(); renderInvokeArea(); renderInvocationList(); }
    });
  }

  function loadInvocations(force) {
    if (S.invocations !== null && !force) { renderInvocationList(); return; }
    S.invocations = null;
    var box = document.getElementById('ext_inv_list');
    if (box) box.innerHTML = DZ.skeleton(4);
    DZ.get('/api/plugins/invocations?limit=' + encodeURIComponent(S.invLimit)).then(function (res) {
      if (res && res.error) {
        var b = document.getElementById('ext_inv_list');
        if (b) b.innerHTML = DZ.banner('bad', res.error.message || '调用记录加载失败', function () { loadInvocations(true); });
        return;
      }
      S.invocations = (res && Array.isArray(res.invocations)) ? res.invocations : [];
      if (S.tab === TAB_PL) renderInvocationList();
    });
  }

  /* ============================================================
     视图装载
     ============================================================ */
  function init() {
    renderShell();
    renderTab();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['ext'] = init;
})();
