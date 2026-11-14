/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   场景包（按业务场景组织知识库调用）
   · demo_scenario.js
   视图 id：scenario   容器：#scenario_root
   读：GET /api/scenario-packs · GET /api/scenario-packs/{id}/detail
   写：POST /api/scenario-packs（新建）、POST /api/scenario-packs/{id}/launch（启动）、
      PUT /api/scenario-packs/{id}/detail（保存调用要素）
   仅使用 window.DZ.* 与现有 class；颜色 / 圆角全部走现有 CSS 变量。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    list: '/api/scenario-packs',
    detail: function (id) { return '/api/scenario-packs/' + encodeURIComponent(id) + '/detail'; },
    launch: function (id) { return '/api/scenario-packs/' + encodeURIComponent(id) + '/launch'; }
  };

  var IND = { bank: '银行', insurance: '保险' };
  // 适用范围对象键 → 中文标签（未知键只呈现值，避免英文键名上屏）
  var SCOPE_LABEL = { lines: '条线', domains: '领域', scope: '范围', reports: '报送', docs: '文号' };
  var TAB_DEFS = [
    { key: 'ks', label: '知识来源' },
    { key: 'kb', label: '知识库' },
    { key: 'org', label: '部门岗位角色' },
    { key: 'tool', label: '工具与系统' },
    { key: 'meta', label: '更新信息' }
  ];

  var S = {
    packs: null,       // null = 未加载
    selPack: null,
    detail: null,
    detailFor: null,
    tab: 'ks',
    creating: false,
    editing: false,
    busy: false,
    launching: null
  };

  function rootEl() { return document.getElementById('scenario_root'); }
  function esc(s) { return DZ.esc(s); }
  function val(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function indLabel(i) { return IND[i] || '—'; }
  function packById(id) { return (S.packs || []).filter(function (p) { return p.packId === id; })[0] || null; }

  function splitList(s) {
    return String(s || '').split(/[,，、;；\s]+/).map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function scopeText(scope) {
    if (!scope || typeof scope !== 'object') return '—';
    var keys = Object.keys(scope);
    if (!keys.length) return '—';
    var parts = keys.map(function (k) {
      var v = scope[k];
      var vals = Array.isArray(v) ? v.join('、') : (v == null ? '' : String(v));
      if (!vals) return '';
      return SCOPE_LABEL[k] ? (SCOPE_LABEL[k] + '：' + vals) : vals;
    }).filter(Boolean);
    return parts.length ? parts.join('；') : '—';
  }

  function pills(list) {
    if (!list || !list.length) return '<span class="muted">—</span>';
    return list.map(function (x) { return DZ.pill(x); }).join(' ');
  }
  function metric(k, vHtml) {
    return '<div class="dz-metric"><span class="dz-metric-k">' + esc(k) + '</span>' +
      '<span class="dz-metric-v">' + vHtml + '</span></div>';
  }
  // 角色在后端以角色标识存储；界面统一按中文角色名呈现，未知值原样保留。
  function roleName(idOrName) {
    var all = (S.detail && S.detail.allRoles) || [];
    for (var i = 0; i < all.length; i++) { if (all[i].roleId === idOrName) return all[i].name; }
    return idOrName;
  }
  function onlineBadge(st) {
    var t = String(st == null ? '' : st);
    if (t === '在线' || t === 'active') return DZ.badge('ok', '在线');
    if (t === '降级' || t === 'degraded') return DZ.badge('warn', '降级');
    if (t === '离线' || t === 'offline') return DZ.badge('bad', '离线');
    return DZ.badge('unk', t || '未知');
  }

  /* ---------------------------------------------------------- 外壳 */
  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button id="scn_new" title="新建场景包" aria-label="新建场景包">＋ 新建场景包</button>' +
        '<button class="ghost" id="scn_refresh" title="重新查询场景包" aria-label="查询场景包">查询</button>' +
      '</div>' +
      '<div id="scn_launch_result"></div>' +
      DZ.guide('<b>场景包</b>：按业务场景组织知识库与工具调用；左侧选择场景包，右侧维护其调用要素（知识来源 / 知识库 / 部门岗位角色 / 工具与系统 / 更新信息）。') +
      '<div id="scn_area">' + DZ.skeleton(5) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('scn_new');
    if (nb) nb.onclick = function () { S.creating = true; S.editing = false; renderArea(); };
    var rb = document.getElementById('scn_refresh');
    if (rb) rb.onclick = function () { loadPacks(true); };
    loadPacks(false);
  }

  /* ---------------------------------------------------------- 列表 / 详情分区 */
  function renderArea() {
    var area = document.getElementById('scn_area');
    if (!area) return;
    if (S.creating) { area.innerHTML = createFormHtml(); bindCreate(); return; }
    if (S.packs === null) { area.innerHTML = DZ.skeleton(5); return; }
    if (!S.packs.length) {
      area.innerHTML = DZ.empty('暂无场景包', '<button id="scn_empty_new" title="新建场景包">＋ 新建场景包</button>');
      var b = document.getElementById('scn_empty_new');
      if (b) b.onclick = function () { S.creating = true; renderArea(); };
      return;
    }
    area.innerHTML = '<div class="dz-split">' +
        '<div class="dz-side dz-sticky"><div class="card"><h3>场景包（' + S.packs.length + '）</h3>' +
          '<div id="scn_list"></div></div></div>' +
        '<div class="dz-main" id="scn_main"></div>' +
      '</div>';
    renderList();
    renderMain();
  }

  function renderList() {
    var box = document.getElementById('scn_list');
    if (!box) return;
    box.innerHTML = '<div class="pick-list" style="grid-template-columns:1fr">' +
      S.packs.map(function (p) {
        var on = p.packId === S.selPack;
        var sel = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
        return '<div class="pick" data-pack="' + esc(p.packId) + '" role="button" tabindex="0"' + sel +
          ' aria-label="查看场景包 ' + esc(p.name) + '" title="查看该场景包的知识库调用要素">' +
          '<div style="min-width:0;flex:1">' +
            '<div class="pick-name" style="font-weight:600">' + esc(p.name) + '</div>' +
            '<div class="muted" style="margin-top:4px">' + esc(indLabel(p.industry)) + ' · ' + esc(scopeText(p.scope)) + '</div>' +
            '<div class="row" style="gap:6px;margin-top:6px">' +
              onlineBadge(p.status) +
              '<button class="ghost" data-launch="' + esc(p.packId) + '" title="启动该场景包" aria-label="启动 ' + esc(p.name) + '">启动场景包</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      }).join('') + '</div>';

    box.querySelectorAll('.pick').forEach(function (el) {
      var open = function () {
        S.editing = false;
        S.selPack = el.getAttribute('data-pack');
        S.detail = null; S.detailFor = null; S.tab = 'ks';
        renderList(); renderMain();
      };
      el.onclick = open;
      el.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
    });
    box.querySelectorAll('[data-launch]').forEach(function (b) {
      b.onclick = function (ev) {
        ev.stopPropagation();
        var p = packById(b.getAttribute('data-launch'));
        if (p) doLaunch(p, b);
      };
    });
  }

  function renderMain() {
    var main = document.getElementById('scn_main');
    if (!main) return;
    if (!S.selPack) { main.innerHTML = DZ.empty('请选择左侧场景包查看调用要素'); return; }
    if (S.editing) { main.innerHTML = editFormHtml(); bindEdit(); return; }
    if (S.detailFor === S.selPack && S.detail) { main.innerHTML = detailHtml(S.detail); bindDetail(); return; }
    main.innerHTML = DZ.skeleton(6);
    loadDetail(S.selPack);
  }

  function loadDetail(id) {
    DZ.get(API.detail(id)).then(function (res) {
      if (S.selPack !== id) return;
      var main = document.getElementById('scn_main');
      if (!main) return;
      if (res && res.error) {
        main.innerHTML = DZ.banner('bad', res.error.message || '场景包明细加载失败', function () {
          S.detail = null; S.detailFor = null; renderMain();
        });
        return;
      }
      S.detail = res; S.detailFor = id;
      if (S.editing) return;
      main.innerHTML = detailHtml(res);
      bindDetail();
    });
  }

  function detailHtml(d) {
    return '<div class="card">' +
      '<h3>' + esc(d.name || '场景包') + ' ' + onlineBadge(d.status) + '</h3>' +
      '<div id="scn_tabs"></div>' +
      '<div id="scn_pane" class="dz-pane"></div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
        '<button id="scn_edit" title="编辑该场景包" aria-label="编辑场景包">编辑场景包</button>' +
      '</div>' +
    '</div>';
  }

  function bindDetail() {
    var eb = document.getElementById('scn_edit');
    if (eb) eb.onclick = function () { S.editing = true; renderMain(); };
    DZ.tabs('#scn_tabs', TAB_DEFS.map(function (t) { return { key: t.key, label: t.label }; }), S.tab, function (k) {
      S.tab = k; renderPane();
    });
    renderPane();
  }

  function renderPane() {
    var box = document.getElementById('scn_pane');
    if (!box || !S.detail) return;
    var d = S.detail;
    if (S.tab === 'kb') box.innerHTML = paneKb(d);
    else if (S.tab === 'org') box.innerHTML = paneOrg(d);
    else if (S.tab === 'tool') box.innerHTML = paneTool(d);
    else if (S.tab === 'meta') box.innerHTML = paneMeta(d);
    else box.innerHTML = paneKs(d);
  }

  function paneKs(d) {
    return DZ.sectionTitle('知识来源') +
      (d.knowledgeSource
        ? '<div class="dz-cite"><div>' + esc(d.knowledgeSource) + '</div></div>'
        : '<div class="muted">尚未声明知识来源</div>');
  }
  function paneKb(d) {
    var names = (d.kbNames && d.kbNames.length) ? d.kbNames : (d.kbIds || []);
    return DZ.sectionTitle('调用的知识库') +
      '<div class="row" style="gap:8px">' + pills(names) + '</div>' +
      '<div class="muted" style="margin-top:8px">共 ' + names.length + ' 个知识库，来自场景包声明的调用范围。</div>';
  }
  function paneOrg(d) {
    return DZ.sectionTitle('部门 / 岗位 / 角色') +
      metric('涉及部门', pills(d.depts)) +
      metric('涉及岗位', pills(d.positions)) +
      metric('涉及角色', pills((d.roles || []).map(roleName)));
  }
  function paneTool(d) {
    return DZ.sectionTitle('工具 / 系统 / 工作模板') +
      metric('需要调用的工具', pills(d.tools)) +
      metric('涉及的系统', pills(d.systems)) +
      metric('工作模板', pills(d.templates));
  }
  function paneMeta(d) {
    return DZ.sectionTitle('更新信息') +
      metric('更新时间', esc(DZ.date(d.updatedAt))) +
      metric('更新人', esc(d.updatedBy || '—'));
  }

  /* ---------------------------------------------------------- 编辑场景包 */
  function editFormHtml() {
    var d = S.detail || {};
    var kbs = d.allKbs || [];
    var chosen = d.kbIds || [];
    var kbList = kbs.length
      ? kbs.map(function (k) {
          var on = chosen.indexOf(k.kbId) >= 0;
          return '<label class="pick"><input type="checkbox" value="' + esc(k.kbId) + '"' + (on ? ' checked' : '') + '>' +
            ' <span class="pick-name">' + esc(k.name) + '</span></label>';
        }).join('')
      : '<div class="muted">暂无可选知识库</div>';
    var roleText = (d.roles || []).map(roleName).join('，');
    return '<div class="card"><h3>编辑场景包：' + esc(d.name || '') + '</h3>' +
      '<label for="scn_f_ks">知识来源</label>' +
      '<input id="scn_f_ks" value="' + esc(d.knowledgeSource || '') + '" placeholder="例如：知识库 + 内部制度" title="知识来源" aria-label="知识来源">' +
      '<label>调用的知识库（多选）</label>' +
      '<div class="pick-list" id="scn_f_kbs">' + kbList + '</div>' +
      '<div class="grid2">' +
        '<div><label for="scn_f_depts">涉及部门（逗号分隔）</label>' +
          '<textarea id="scn_f_depts" rows="2" title="涉及部门" aria-label="涉及部门">' + esc((d.depts || []).join('，')) + '</textarea></div>' +
        '<div><label for="scn_f_positions">涉及岗位（逗号分隔）</label>' +
          '<textarea id="scn_f_positions" rows="2" title="涉及岗位" aria-label="涉及岗位">' + esc((d.positions || []).join('，')) + '</textarea></div>' +
        '<div><label for="scn_f_roles">涉及角色（逗号分隔）</label>' +
          '<textarea id="scn_f_roles" rows="2" title="涉及角色" aria-label="涉及角色">' + esc(roleText) + '</textarea></div>' +
        '<div><label for="scn_f_tools">需要调用的工具（逗号分隔）</label>' +
          '<textarea id="scn_f_tools" rows="2" title="需要调用的工具" aria-label="需要调用的工具">' + esc((d.tools || []).join('，')) + '</textarea></div>' +
        '<div><label for="scn_f_systems">涉及的系统（逗号分隔）</label>' +
          '<textarea id="scn_f_systems" rows="2" title="涉及的系统" aria-label="涉及的系统">' + esc((d.systems || []).join('，')) + '</textarea></div>' +
        '<div><label for="scn_f_templates">工作模板（逗号分隔）</label>' +
          '<textarea id="scn_f_templates" rows="2" title="工作模板" aria-label="工作模板">' + esc((d.templates || []).join('，')) + '</textarea></div>' +
      '</div>' +
      '<div id="scn_f_msg"></div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
        '<button id="scn_f_save" title="保存场景包" aria-label="保存场景包">保存</button>' +
        '<button class="ghost" id="scn_f_cancel" title="取消编辑" aria-label="取消">取消</button>' +
      '</div></div>';
  }

  function bindEdit() {
    var s = document.getElementById('scn_f_save');
    if (s) s.onclick = saveEdit;
    var c = document.getElementById('scn_f_cancel');
    if (c) c.onclick = function () { S.editing = false; renderMain(); };
  }

  function saveEdit() {
    if (S.busy) return;
    var kbs = [];
    document.querySelectorAll('#scn_f_kbs input[type=checkbox]').forEach(function (n) { if (n.checked) kbs.push(n.value); });
    var body = {
      knowledgeSource: val('scn_f_ks'),
      kbIds: kbs,
      depts: splitList(val('scn_f_depts')),
      positions: splitList(val('scn_f_positions')),
      roles: splitList(val('scn_f_roles')),
      tools: splitList(val('scn_f_tools')),
      systems: splitList(val('scn_f_systems')),
      templates: splitList(val('scn_f_templates'))
    };
    var msg = document.getElementById('scn_f_msg');
    var btn = document.getElementById('scn_f_save');
    S.busy = true;
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    if (msg) msg.innerHTML = '';
    DZ.put(API.detail(S.selPack), body).then(function (res) {
      S.busy = false;
      if (btn) { btn.disabled = false; btn.textContent = '保存'; }
      if (res && res.error) {
        if (msg) msg.innerHTML = DZ.banner('bad', res.error.message || '保存失败', saveEdit);
        return;
      }
      DZ.toast('场景包已保存，已写入审计留痕', 'ok');
      S.editing = false;
      S.detail = null; S.detailFor = null;
      renderMain();
    });
  }

  /* ---------------------------------------------------------- 新建场景包 */
  function createFormHtml() {
    return '<div class="card"><h3>新建场景包</h3>' +
      '<div class="form-narrow">' +
        '<label for="scn_n_name">场景包名称（必填）</label>' +
        '<input id="scn_n_name" placeholder="例如：反洗钱专项自查" title="场景包名称" aria-label="场景包名称">' +
        '<label for="scn_n_industry">行业</label>' +
        '<select id="scn_n_industry" title="行业" aria-label="行业">' +
          '<option value="bank">银行</option><option value="insurance">保险</option></select>' +
        '<label for="scn_n_lines">适用范围（条线，逗号分隔）</label>' +
        '<input id="scn_n_lines" placeholder="例如：账户管理，信贷" title="适用范围（条线）" aria-label="适用范围（条线）">' +
        '<div id="scn_n_msg"></div>' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
          '<button id="scn_n_submit" title="创建场景包" aria-label="创建场景包">创建场景包</button>' +
          '<button class="ghost" id="scn_n_cancel" title="取消新建" aria-label="取消">取消</button>' +
        '</div>' +
      '</div></div>';
  }

  function bindCreate() {
    var c = document.getElementById('scn_n_cancel');
    if (c) c.onclick = function () { S.creating = false; renderArea(); };
    var s = document.getElementById('scn_n_submit');
    if (s) s.onclick = submitCreate;
  }

  function submitCreate() {
    if (S.busy) return;
    var msg = document.getElementById('scn_n_msg');
    var btn = document.getElementById('scn_n_submit');
    var name = val('scn_n_name');
    if (!name) { if (msg) msg.innerHTML = DZ.banner('bad', '请填写场景包名称'); return; }
    var body = {
      name: name,
      industry: val('scn_n_industry') || 'bank',
      scope: { lines: splitList(val('scn_n_lines')) }
    };
    S.busy = true;
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    DZ.post(API.list, body).then(function (res) {
      S.busy = false;
      if (btn) { btn.disabled = false; btn.textContent = '创建场景包'; }
      if (res && res.error) {
        if (msg) msg.innerHTML = DZ.banner('bad', res.error.message || '创建失败', submitCreate);
        return;
      }
      DZ.toast('场景包已创建', 'ok');
      S.creating = false;
      if (res && res.packId) { S.selPack = res.packId; S.detail = null; S.detailFor = null; }
      loadPacks(true);
    });
  }

  /* ---------------------------------------------------------- 启动场景包 */
  function doLaunch(p, btn) {
    if (S.launching) return;
    S.launching = p.packId;
    var old = btn ? btn.textContent : '启动场景包';
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    var box = document.getElementById('scn_launch_result');
    if (box) box.innerHTML = DZ.banner('', '正在启动场景包…');
    DZ.post(API.launch(p.packId), {}).then(function (res) {
      S.launching = null;
      if (btn) { btn.disabled = false; btn.textContent = old; }
      if (res && res.error) {
        if (box) box.innerHTML = DZ.banner('bad', res.error.message || '启动失败', function () { doLaunch(p, btn); });
        return;
      }
      DZ.toast('场景包已启动', 'ok');
      if (box) {
        box.innerHTML = '<div class="why">已按场景包“' + esc(p.name) + '”启动，可前往「安全自查」查看运行中的自查任务。' +
          '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
            '<button class="ghost" id="scn_goto_dsc" title="前往安全自查" aria-label="前往安全自查">前往安全自查</button>' +
          '</div></div>';
        var go = document.getElementById('scn_goto_dsc');
        if (go) go.onclick = function () {
          if (typeof window.showView === 'function') window.showView('dsc');
          else DZ.toast('安全自查视图不可用', 'warn');
        };
      }
    });
  }

  /* ---------------------------------------------------------- 取数 */
  function loadPacks(force) {
    if (S.packs !== null && !force) { renderArea(); return; }
    S.packs = null;
    var area = document.getElementById('scn_area');
    if (area) area.innerHTML = DZ.skeleton(5);
    DZ.get(API.list).then(function (res) {
      if (res && res.error) {
        var a = document.getElementById('scn_area');
        if (a) a.innerHTML = DZ.banner('bad', res.error.message || '场景包加载失败', function () { loadPacks(true); });
        return;
      }
      S.packs = (res && Array.isArray(res.packs)) ? res.packs : [];
      if (!S.selPack || !S.packs.some(function (p) { return p.packId === S.selPack; })) {
        S.selPack = S.packs.length ? S.packs[0].packId : null;
        S.detail = null; S.detailFor = null;
      }
      renderArea();
    });
  }

  /* ---------------------------------------------------------- 视图装载 */
  function init() {
    var r = rootEl();
    if (r) r.innerHTML = DZ.skeleton(6);
    mount();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['scenario'] = init;
})();
