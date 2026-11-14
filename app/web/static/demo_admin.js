/* ============================================================
   权限与组织 · demo_admin.js（拆分为两个菜单，各注册一个视图初始化）
   视图 gov（权限与组织 / 容器 #gov_root）：组织 / 角色能力 / 人员绑定
   视图 perm（权限策略与审计 / 容器 #perm_root）：菜单权限 / 数据范围 /
            单点登录 / 文号注册 / 审计日志 / 治理看板
   严格只用 DZ.* 与 dz- 前缀 class；颜色 / 圆角仅走现有 CSS 变量。
   新增页签取数惰性加载（切到该页签才请求后端）。
   所有异步先骨架屏；失败横幅 + 重试；空数据空态；写操作处理中反馈。
   ============================================================ */
(function () {
  'use strict';

  // 当前视图标识（gov / perm），与页签 key 区分：VIEW 是视图，S.tab 是页签
  var VIEW = 'gov';

  // 后端真实路径（app/demo/router.py §5.10 / §auth）
  var API = {
    orgNodes:   '/api/admin/org-nodes',
    orgCreate:  '/api/admin/org-nodes',
    positions:  '/api/admin/org-positions',
    roles:      '/api/admin/roles',
    bindings:   '/api/admin/role-bindings',
    bindCreate: '/api/admin/role-bindings',
    capabilities:'/api/admin/capabilities',
    users:      '/api/admin/users',
    userStatus: function (acc) { return '/api/admin/users/' + encodeURIComponent(acc) + '/status'; },
    audit:      '/api/admin/audit',
    auditExport:'/api/admin/audit/export',
    docReg:     '/api/admin/doc-registry',
    docConfirm: function (k) { return '/api/admin/doc-registry/' + encodeURIComponent(k); },
    gov:        '/api/admin/gov-dashboard',
    menuPerms:  '/api/admin/menu-perms',
    dataScopes: '/api/admin/data-scopes',
    dataScope:  function (rid) { return '/api/admin/data-scopes/' + encodeURIComponent(rid); },
    ssoConfig:  '/api/admin/sso-config',
    session:    '/api/auth/session'
  };

  var INDUSTRY_LABEL = { bank: '银行', insurance: '保险' };
  // 层级与组织节点类型（后端枚举 → 中文），仅用于展示，提交值仍为英文编码
  var LEVEL_LABEL = { L0: '总行级', L1: '分行级', L2: '支行级', L3: '网点级' };
  var KIND_LABEL = { hq: '总部', branch: '分行', subbranch: '支行', outlet: '网点', counter: '柜面' };
  function levelLabel(l) { return LEVEL_LABEL[l] || l || '—'; }
  function kindLabel(k) { return KIND_LABEL[k] || k || '—'; }

  // 页签注册表：按视图标识分槽（视图 gov / perm 各有自己的页签集合）
  var TABS = {
    gov: [
      { key: 'org',     label: '组织' },
      { key: 'roles',   label: '角色能力' },
      { key: 'binding', label: '人员绑定' }
    ],
    perm: [
      { key: 'menu',    label: '菜单权限' },
      { key: 'scope',   label: '数据范围' },
      { key: 'sso',     label: '单点登录' },
      { key: 'docreg',  label: '文号注册' },
      { key: 'audit',   label: '审计日志' },
      { key: 'gov',     label: '治理看板' }
    ]
  };

  // 各页签的引导说明：一句话讲清本页签要做什么
  var TAB_GUIDE = {
    org: '「组织」：维护组织架构树，可按行业切换查看。',
    roles: '「角色能力」：配置角色及其能力清单，作为权限控制的基础。',
    binding: '「人员绑定」：将人员绑定到组织、岗位与角色。',
    menu: '「菜单权限」：配置各角色可见的菜单。',
    scope: '「数据范围」：配置各角色可见的数据层级范围，实现按层级隔离。',
    sso: '「单点登录」：查看与配置单点登录对接信息。',
    docreg: '「文号注册」：注册与维护依据文号，供自查与报告引用。',
    audit: '「审计日志」：查看系统操作审计留痕，只追加不可改写。',
    gov: '「治理看板」：总览治理与合规关键指标。'
  };

  // 各视图独立状态（互不覆盖跨页签的选择项）
  function newState(tab) {
    return {
      tab: tab,
      industry: 'bank',
      roleSel: null,
      roleNew: false,
      roles: [],
      caps: [],
      matrix: {},
      docs: [],
      users: [],
      session: null,
      menuData: null,
      menuRoleSel: null,
      scopeData: null,
      ssoData: null,
      ssoNames: {}
    };
  }
  var STATE = { gov: newState('org'), perm: newState('menu') };
  var S = STATE[VIEW]; // 当前视图状态（在 init 中按 VIEW 切换）

  // ---------- 通用工具 ----------
  function title(t) { return '<div class="dz-section-title">' + DZ.esc(t) + '</div>'; }
  function card(t, inner) { return '<div class="card">' + (t ? title(t) : '') + inner + '</div>'; }
  function fail(e, retry) {
    var msg = (e && e.error && e.error.message) || (e && e.message) || '加载失败';
    return DZ.banner('bad', msg, retry);
  }
  function opts(list, val, lab, sel) {
    return (list || []).map(function (x) {
      var v = (typeof val === 'function') ? val(x) : x[val];
      var l = (typeof lab === 'function') ? lab(x) : x[lab];
      return '<option value="' + DZ.esc(v) + '"' + (String(v) === String(sel) ? ' selected' : '') + '>' + DZ.esc(l) + '</option>';
    }).join('');
  }
  function emptyOpt(label) { return '<option value="">' + DZ.esc(label) + '</option>'; }
  function pct(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    if (n <= 1) n = n * 100;
    return Math.round(n) + '%';
  }
  function flatten(nodes) {
    var out = [];
    (nodes || []).forEach(function (n) {
      out.push(n);
      if (n.children && n.children.length) out = out.concat(flatten(n.children));
    });
    return out;
  }
  function roleName(rid) {
    var f = (S.roles || []).filter(function (r) { return r.roleId === rid; })[0];
    return f ? f.name : rid;
  }
  // 处理中按钮反馈（300–700ms，不伪造后端成功）
  function busy(btn, text, fn) {
    if (!btn) return fn();
    var old = btn.textContent, was = btn.disabled;
    btn.disabled = true; btn.textContent = text || '处理中…';
    return Promise.resolve(fn()).then(function (r) { btn.disabled = was; btn.textContent = old; return r; },
      function (e) { btn.disabled = was; btn.textContent = old; throw e; });
  }

  // ---------- 装载 ----------
  // 统一渲染：按 VIEW 切换状态槽与根容器（#gov_root / #perm_root），只渲染当前视图
  async function init() {
    S = STATE[VIEW];
    var box = document.getElementById(VIEW + '_root');
    if (!box) return;
    box.innerHTML =
      '<div id="' + VIEW + '_tabs"></div><div id="' + VIEW + '_hint"></div><div id="' + VIEW + '_body"></div>';
    DZ.tabs('#' + VIEW + '_tabs', TABS[VIEW], S.tab, function (k) { S.tab = k; renderTab(); });
    await loadSession();
    renderTab();
  }

  async function loadSession() {
    var s = await DZ.get(API.session, { delay: false });
    S.session = (s && !s.error) ? s : null;
  }

  var RENDERERS = { org: renderOrg, roles: renderRoles, binding: renderBindings,
    menu: renderMenu, scope: renderScope, sso: renderSso,
    docreg: renderDocReg, audit: renderAudit, gov: renderGov };

  function renderTab() {
    var body = document.getElementById(VIEW + '_body');
    if (!body) return;
    DZ.render('#' + VIEW + '_hint', DZ.guide(TAB_GUIDE[S.tab] || ''));
    body.innerHTML = DZ.skeleton(5);
    var f = RENDERERS[S.tab] || RENDERERS[TABS[VIEW][0].key];
    Promise.resolve(f(body)).catch(function (e) {
      body.innerHTML = fail({ error: { message: '渲染异常：' + ((e && e.message) || e) } });
    });
  }

  // =========================================================================
  // 1. 组织架构（G3 / §2.5）
  // =========================================================================
  async function renderOrg(body) {
    body.innerHTML = '<div class="dz-split"><div class="dz-side" id="org_side">' + DZ.skeleton(5) +
      '</div><div class="dz-main" id="org_main">' + DZ.skeleton(4) + '</div></div>';

    var res = await Promise.all([
      DZ.get(API.orgNodes + '?industry=' + encodeURIComponent(S.industry)),
      DZ.get(API.positions)
    ]);
    var t = res[0], p = res[1];
    var side = document.querySelector('#org_side');
    var main = document.querySelector('#org_main');
    if (!side || !main) return;

    var chips = '<div class="dz-chipbar">' + ['bank', 'insurance'].map(function (ind) {
      return '<button type="button" class="dz-chip' + (S.industry === ind ? ' on' : '') + '" data-ind="' + ind + '" ' +
        'title="查看' + INDUSTRY_LABEL[ind] + '组织树" aria-label="切换' + INDUSTRY_LABEL[ind] + '组织树">' + INDUSTRY_LABEL[ind] + '</button>';
    }).join('') + '</div>';

    if (t && t.error) {
      side.innerHTML = card('组织架构', chips + fail(t.error, function () { renderOrg(body); }));
    } else {
      var tree = (t && t.tree) || [];
      var treeHtml = tree.length ? treeRenderer(tree) : DZ.empty('该行业暂无组织节点，可在下方新增', '');
      side.innerHTML = card('组织架构（' + INDUSTRY_LABEL[S.industry] + '）',
        chips + '<div class="dz-table-wrap">' + treeHtml + '</div>' +
        '<div class="muted" style="margin-top:6px">共 ' + DZ.number((t && t.total) || 0) + ' 个节点</div>');
      side.querySelectorAll('.dz-chip').forEach(function (c) {
        c.onclick = function () { S.industry = c.dataset.ind; renderOrg(body); };
      });
      side.insertAdjacentHTML('beforeend', addNodeCard(tree));
      bindAddNode(side, body);
    }

    // 主区：层级可见规则示意 + 岗位
    main.innerHTML = visibilityCard(S.session) + positionsCard(p, function () { renderOrg(body); });
  }

  function levelBadge(level) {
    var k = { L0: 'p0', L1: 'p1', L2: 'p2', L3: 'unk' }[level] || 'unk';
    return DZ.badge(k, levelLabel(level));
  }
  function treeRenderer(nodes) {
    return '<ul class="treelist">' + (nodes || []).map(function (n) {
      return '<li><a title="' + DZ.esc(n.name) + '（' + DZ.esc(levelLabel(n.level)) + '，' + DZ.esc(kindLabel(n.kind)) + '）" ' +
        'aria-label="组织节点 ' + DZ.esc(n.name) + '">' + levelBadge(n.level) + ' ' + DZ.esc(n.name) +
        '<span class="muted"> ' + DZ.esc(n.node_id) + ' · ' + DZ.esc(kindLabel(n.kind)) + '</span></a>' +
        (n.children && n.children.length ? treeRenderer(n.children) : '') + '</li>';
    }).join('') + '</ul>';
  }

  function addNodeCard(tree) {
    var nodes = flatten(tree);
    return card('新增组织节点',
      '<div><label for="nn_name">节点名称 *</label><input id="nn_name" placeholder="如：浦东新区支行" autocomplete="off" /></div>' +
      '<div class="grid2">' +
        '<div><label for="nn_parent">上级节点</label><select id="nn_parent">' + emptyOpt('（作为根节点）') +
          opts(nodes, 'node_id', function (n) { return n.name + '（' + levelLabel(n.level) + '）'; }, '') + '</select></div>' +
        '<div><label for="nn_level">层级</label><select id="nn_level">' +
          ['L1', 'L2', 'L3'].map(function (l) { return '<option value="' + l + '"' + (l === 'L3' ? ' selected' : '') + '>' + levelLabel(l) + '</option>'; }).join('') + '</select></div>' +
      '</div>' +
      '<div class="grid2">' +
        '<div><label for="nn_kind">节点类型</label><select id="nn_kind">' +
          [['branch', '分行'], ['subbranch', '支行'], ['outlet', '网点'], ['counter', '柜面'], ['hq', '总部']]
            .map(function (k) { return '<option value="' + k[0] + '">' + k[1] + '</option>'; }).join('') + '</select></div>' +
        '<div><label for="nn_line">条线编码</label><input id="nn_line" placeholder="可选，如：华东" autocomplete="off" /></div>' +
      '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
        '<button id="nn_submit" title="提交新增组织节点" aria-label="提交新增组织节点">新增节点</button></div>');
  }

  function bindAddNode(scope, body) {
    var btn = scope.querySelector('#nn_submit');
    if (!btn) return;
    btn.onclick = function () {
      var name = (scope.querySelector('#nn_name').value || '').trim();
      if (!name) { DZ.toast('请填写节点名称', 'warn'); return; }
      var payload = {
        name: name,
        parentId: scope.querySelector('#nn_parent').value || null,
        level: scope.querySelector('#nn_level').value,
        kind: scope.querySelector('#nn_kind').value,
        lineCode: (scope.querySelector('#nn_line').value || '').trim() || null,
        industry: S.industry
      };
      busy(btn, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.post(API.orgCreate, payload);
        if (r && r.error) { DZ.toast('新增失败：' + (r.error.message || ''), 'bad'); return; }
        DZ.toast('已新增节点「' + name + '」' + (r && r.nodeId ? '（' + r.nodeId + '）' : '') + '，已写入审计', 'ok');
        renderOrg(body);
      });
    };
  }

  // 层级可见规则可视化：当前账号所在层 → 可见层级
  function visibilityCard(session) {
    var order = ['L0', 'L1', 'L2', 'L3'];
    var lv = (session && session.org && session.org.level) || 'L0';
    var roles = (session && session.roles) || [];
    var isGlobal = !!(session && (session.isBootstrap || roles.indexOf('sys_admin') >= 0));
    var curIdx = order.indexOf(lv); if (curIdx < 0) curIdx = 0;
    var flow = order.map(function (L, i) {
      var vis = isGlobal || i >= curIdx;
      var isCur = (i === curIdx);
      return '<div class="dz-node' + (vis ? ' on' : '') + '" title="' + L + (vis ? '：可见' : '：不可见') + '" ' +
        'aria-label="层级 ' + L + (vis ? ' 可见' : ' 不可见') + '">' +
        '<div class="dz-node-title">' + L + (isCur ? '（本级）' : '') + '</div>' +
        '<div class="muted">' + (vis ? '可见' : '不可见') + '</div></div>';
    }).join('<span class="dz-arrow">→</span>');

    return card('层级可见规则',
      '<div class="row" style="justify-content:space-between">' +
        '<div class="muted">当前账号：' + DZ.esc((session && session.displayName) || '—') +
          '（' + DZ.esc((session && session.account) || '—') + '）</div>' +
        '<div>' + (isGlobal ? DZ.badge('ok', '全层级可见') : DZ.badge('warn', '受限可见')) + '</div>' +
      '</div>' +
      '<div class="dz-flow" style="margin-top:10px">' + flow + '</div>' +
      '<div class="why">当前账号所属层级 <b>' + DZ.esc(levelLabel(lv)) + '</b>：' +
        (isGlobal ? '可查看各层级的汇总与详情。' :
          '可查看 <b>本级及其下级</b> 的汇总与详情，<b>上级节点不可见</b>。') + '</div>');
  }

  function positionsCard(p, retry) {
    if (p && p.error) return card('岗位列表', fail(p.error, retry));
    var list = (p && p.positions) || [];
    if (!list.length) return card('岗位列表', DZ.empty('暂无岗位数据', ''));
    var rows = list.map(function (x) {
      return '<tr><td>' + DZ.esc(x.positionId) + '</td><td>' + DZ.esc(x.name) + '</td>' +
        '<td>' + DZ.esc(x.orgNodeName || '—') + '</td><td>' + DZ.statusBadge(x.status) + '</td></tr>';
    }).join('');
    return card('岗位列表（' + list.length + '）',
      '<div class="dz-table-wrap"><table><thead><tr><th>岗位 ID</th><th>名称</th><th>所属机构</th><th>状态</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
  }

  // =========================================================================
  // 2. 角色与能力矩阵（§2.8）
  // =========================================================================
  async function renderRoles(body) {
    body.innerHTML = '<div class="dz-split"><div class="dz-side" id="role_side">' + DZ.skeleton(6) +
      '</div><div class="dz-main" id="role_main">' + DZ.skeleton(4) + '</div></div>' +
      '<div id="role_matrix" style="margin-top:18px">' + DZ.skeleton(5) + '</div>';

    var res = await Promise.all([DZ.get(API.roles), DZ.get(API.capabilities)]);
    var rl = res[0], cp = res[1];
    if (rl && rl.error) {
      document.querySelector('#role_side').innerHTML = card('角色列表', fail(rl.error, function () { renderRoles(body); }));
      document.querySelector('#role_main').innerHTML = '';
      document.querySelector('#role_matrix').innerHTML = '';
      return;
    }
    S.roles = (rl && rl.roles) || [];
    S.caps = (cp && cp.capabilities) || [];
    S.matrix = (cp && cp.matrix) || {};
    if (!S.roleSel && !S.roleNew && S.roles.length) S.roleSel = S.roles[0].roleId;
    renderRolePanels(body);
  }

  function renderRolePanels(body) {
    renderRoleSide(body);
    renderRoleEditor(body);
    renderRoleMatrix();
  }

  function renderRoleSide(body) {
    var roles = S.roles || [];
    var rows = roles.map(function (r) {
      var on = S.roleSel === r.roleId;
      return '<tr data-rid="' + DZ.esc(r.roleId) + '" role="button" tabindex="0" style="cursor:pointer" title="查看/编辑角色 ' + DZ.esc(r.name) + '" ' +
        'aria-label="角色 ' + DZ.esc(r.name) + '">' +
        '<td>' + (on ? '<b>' + DZ.esc(r.name) + '</b>' : DZ.esc(r.name)) + '</td>' +
        '<td>' + DZ.pill(levelLabel(r.levelVisibility)) + '</td>' +
        '<td>' + DZ.statusBadge(r.status) + (r.builtin ? ' ' + DZ.badge('unk', '内置') : '') + '</td></tr>';
    }).join('');
    document.querySelector('#role_side').innerHTML = card('角色列表（' + roles.length + '）',
      '<div class="dz-actions" style="justify-content:flex-start;margin-bottom:10px">' +
        '<button id="role_new" class="ghost" title="新建角色" aria-label="新建角色">+ 新建角色</button></div>' +
      (roles.length
        ? '<div class="dz-table-wrap"><table><thead><tr><th>角色</th><th>可见层级</th><th>状态</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        : DZ.empty('暂无角色，可点击「新建角色」', '')));

    document.querySelectorAll('#role_side tbody tr').forEach(function (tr) {
      tr.onclick = function () { S.roleSel = tr.dataset.rid; S.roleNew = false; renderRolePanels(body); };
      tr.onkeydown = function (ev) {
        if (ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); tr.click(); }
      };
    });
    var nb = document.querySelector('#role_new');
    if (nb) nb.onclick = function () { S.roleNew = true; S.roleSel = null; renderRolePanels(body); };
  }

  function expandCaps(caps) {
    if ((caps || []).indexOf('*') >= 0) return (S.caps || []).map(function (c) { return c.key; });
    return (caps || []).slice();
  }

  function renderRoleEditor(body) {
    var cur = (!S.roleNew && S.roleSel) ? (S.roles || []).filter(function (r) { return r.roleId === S.roleSel; })[0] : null;
    var isNew = !cur;
    var selected = expandCaps(cur ? cur.capabilities : []);
    var selMap = {}; selected.forEach(function (k) { selMap[k] = 1; });

    var capPicks = (S.caps || []).map(function (c) {
      return '<label class="pick" title="' + DZ.esc(c.label) + '" aria-label="能力 ' + DZ.esc(c.label) + '">' +
        '<input type="checkbox" class="rc_cap" value="' + DZ.esc(c.key) + '"' + (selMap[c.key] ? ' checked' : '') + ' />' +
        '<span class="pick-name">' + DZ.esc(c.label) + '</span>' +
        '<span class="pick-meta">' + DZ.esc(c.key) + '</span></label>';
    }).join('');

    var scopeJson = cur && cur.scope ? JSON.stringify(cur.scope) : '{}';

    document.querySelector('#role_main').innerHTML = card(isNew ? '新建角色' : '角色详情 · ' + cur.name,
      '<div class="grid2">' +
        '<div><label for="rc_id">角色编码 *</label><input id="rc_id" value="' + DZ.esc(cur ? cur.roleId : '') + '" ' +
          (isNew ? 'placeholder="请输入角色编码"' : 'disabled') + ' autocomplete="off" /></div>' +
        '<div><label for="rc_name">角色名称</label><input id="rc_name" value="' + DZ.esc(cur ? cur.name : '') + '" placeholder="如：审计员" autocomplete="off" /></div>' +
      '</div>' +
      '<div class="grid2">' +
        '<div><label for="rc_lv">可见层级</label><select id="rc_lv">' +
          ['L0', 'L1', 'L2', 'L3'].map(function (l) {
            return '<option value="' + l + '"' + ((cur ? cur.levelVisibility : 'L1') === l ? ' selected' : '') + '>' + levelLabel(l) + '</option>';
          }).join('') + '</select></div>' +
        '<div><label for="rc_status">状态</label><select id="rc_status">' +
          '<option value="active"' + ((!cur || cur.status === 'active') ? ' selected' : '') + '>启用</option>' +
          '<option value="disabled"' + ((cur && cur.status === 'disabled') ? ' selected' : '') + '>停用</option>' +
        '</select></div>' +
      '</div>' +
      '<label style="margin-top:12px">能力集（勾选可视化）</label>' +
      '<div class="pick-list">' + capPicks + '</div>' +
      '<div class="muted">数据范围：<code>' + DZ.esc(scopeJson) + '</code>' +
        (cur && cur.builtin ? '　' + DZ.badge('unk', '内置角色') : '') + '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:12px">' +
        '<button id="rc_save" title="保存角色（新建/更新）" aria-label="保存角色">' + (isNew ? '创建角色' : '保存修改') + '</button>' +
        (isNew ? '' : '<button id="rc_disable" class="ghost" title="停用角色" aria-label="停用角色">停用角色</button>') +
      '</div>');

    var save = document.querySelector('#rc_save');
    if (save) save.onclick = function () {
      var roleId = document.querySelector('#rc_id').value.trim();
      if (!roleId) { DZ.toast('请填写角色 ID', 'warn'); return; }
      var caps = Array.prototype.map.call(document.querySelectorAll('#role_main .rc_cap:checked'), function (c) { return c.value; });
      var payload = {
        roleId: roleId,
        name: document.querySelector('#rc_name').value.trim() || roleId,
        capabilities: caps,
        levelVisibility: document.querySelector('#rc_lv').value,
        status: document.querySelector('#rc_status').value
      };
      busy(save, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.post(API.roles, payload);
        if (r && r.error) { DZ.toast('保存失败：' + (r.error.message || ''), 'bad'); return; }
        DZ.toast('已保存角色「' + payload.name + '」并写入审计', 'ok');
        var rl = await DZ.get(API.roles, { delay: false });
        S.roles = (rl && rl.roles) || S.roles;
        S.roleSel = roleId; S.roleNew = false;
        renderRolePanels(body);
      });
    };
    var dis = document.querySelector('#rc_disable');
    if (dis) dis.onclick = function () {
      document.querySelector('#rc_status').value = 'disabled';
      save.click();
    };
  }

  function renderRoleMatrix() {
    var el = document.querySelector('#role_matrix');
    if (!el) return;
    var roles = S.roles || [], caps = S.caps || [];
    if (!roles.length || !caps.length) { el.innerHTML = card('能力基准矩阵', DZ.empty('无角色或能力字典', '')); return; }
    var head = '<tr><th>角色 \\ 能力</th>' + caps.map(function (c) {
      return '<th title="' + DZ.esc(c.label) + '">' + DZ.esc(c.key) + '</th>';
    }).join('') + '</tr>';
    var body = roles.map(function (r) {
      var sel = expandCaps(r.capabilities);
      var selMap = {}; sel.forEach(function (k) { selMap[k] = 1; });
      return '<tr><td><b>' + DZ.esc(r.name) + '</b></td>' +
        caps.map(function (c) {
          return '<td style="text-align:center" title="' + DZ.esc(r.name) + ' × ' + DZ.esc(c.label) + '">' +
            (selMap[c.key] ? '<span style="color:var(--ok-ink);font-weight:700" aria-label="具备">●</span>' : '<span class="muted" aria-label="不具备">—</span>') + '</td>';
        }).join('') + '</tr>';
    }).join('');
    el.innerHTML = card('能力基准矩阵（角色 × 能力，§2.8）',
      '<div class="dz-table-wrap"><table><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>' +
      '<details style="margin-top:8px"><summary title="展开能力字典" aria-label="能力字典">能力字典（' + caps.length + '）</summary>' +
        '<div class="dz-table-wrap"><table><thead><tr><th>能力键</th><th>中文</th></tr></thead><tbody>' +
        caps.map(function (c) { return '<tr><td><code>' + DZ.esc(c.key) + '</code></td><td>' + DZ.esc(c.label) + '</td></tr>'; }).join('') +
        '</tbody></table></div></details>');
  }

  // =========================================================================
  // 3. 人员—角色—机构绑定（§2.6）
  // =========================================================================
  async function renderBindings(body) {
    body.innerHTML = '<div id="bind_sod"></div>' +
      '<div class="grid2"><div id="bind_list">' + DZ.skeleton(5) + '</div><div id="bind_form">' + DZ.skeleton(4) + '</div></div>' +
      '<div id="bind_users" style="margin-top:18px">' + DZ.skeleton(5) + '</div>';

    var res = await Promise.all([
      DZ.get(API.bindings), DZ.get(API.users), DZ.get(API.roles, { delay: false }),
      DZ.get(API.orgNodes), DZ.get(API.positions, { delay: false })
    ]);
    var rb = res[0], us = res[1], rl = res[2], nn = res[3], ps = res[4];
    if (!S.roles.length && rl && rl.roles) S.roles = rl.roles;
    var users = (us && us.users) || []; S.users = users;
    var roles = (rl && rl.roles) || S.roles || [];
    var nodes = flatten((nn && nn.tree) || []);
    var positions = (ps && ps.positions) || [];

    document.querySelector('#bind_sod').innerHTML = sodCard(users);

    if (rb && rb.error) {
      document.querySelector('#bind_list').innerHTML = card('绑定列表', fail(rb.error, function () { renderBindings(body); }));
    } else {
      document.querySelector('#bind_list').innerHTML = bindingsCard((rb && rb.bindings) || []);
    }
    document.querySelector('#bind_form').innerHTML = bindFormCard(users, roles, nodes, positions, body);
    bindingsBindHandler(body);
    document.querySelector('#bind_users').innerHTML = usersCard(users, body);
  }

  function sodCard(users) {
    var multi = (users || []).filter(function (u) { return (u.roles || []).length > 1; });
    if (!multi.length) return card('职责分离（一人多角色）', '<div class="muted">未检测到「一人多角色」账号。</div>');
    return card('职责分离（一人多角色）',
      '<div class="muted" style="margin-bottom:8px">检测到 ' + multi.length +
        ' 个账号持有多角色：复核签署与经办提交须为不同账号，同账号签署将被后端以 403 拦截并写入审计。</div>' +
      '<div class="dz-table-wrap"><table><thead><tr><th>账号</th><th>姓名</th><th>角色</th></tr></thead><tbody>' +
        multi.map(function (u) {
          return '<tr><td>' + DZ.esc(u.account) + '</td><td>' + DZ.esc(u.displayName) + '</td><td>' +
            (u.roles || []).map(function (r) { return DZ.pill(roleName(r)); }).join(' ') + '</td></tr>';
        }).join('') + '</tbody></table></div>');
  }

  function bindingsCard(bindings) {
    if (!bindings.length) return card('绑定列表', DZ.empty('暂无绑定关系', ''));
    var rows = bindings.map(function (b) {
      return '<tr><td>' + DZ.esc(b.account) + '<div class="muted">' + DZ.esc(b.displayName || '') + '</div></td>' +
        '<td>' + DZ.esc(roleName(b.roleId)) + '</td>' +
        '<td>' + DZ.esc(b.orgNodeName || b.orgNodeId || '—') + '</td>' +
        '<td>' + DZ.esc(b.positionName || b.positionId || '—') + '</td>' +
        '<td>' + DZ.pill(levelLabel(b.levelVisibility)) + '</td></tr>';
    }).join('');
    return card('绑定列表（' + bindings.length + '）',
      '<div class="dz-table-wrap"><table><thead><tr><th>账号</th><th>角色</th><th>机构</th><th>岗位</th><th>可见层级</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
  }

  function bindFormCard(users, roles, nodes, positions, body) {
    return card('新增绑定',
      '<div class="grid2">' +
        '<div><label for="bd_account">账号 *</label><select id="bd_account">' + emptyOpt('请选择账号') +
          opts(users, 'account', function (u) { return u.displayName + '（' + u.account + '）'; }, '') + '</select></div>' +
        '<div><label for="bd_role">角色 *</label><select id="bd_role">' + emptyOpt('请选择角色') +
          opts(roles, 'roleId', function (r) { return r.name; }, '') + '</select></div>' +
      '</div>' +
      '<div class="grid2">' +
        '<div><label for="bd_org">机构</label><select id="bd_org">' + emptyOpt('（可选）') +
          opts(nodes, 'node_id', function (n) { return n.name + '（' + levelLabel(n.level) + '）'; }, '') + '</select></div>' +
        '<div><label for="bd_pos">岗位</label><select id="bd_pos">' + emptyOpt('（可选）') +
          opts(positions, 'positionId', function (p) { return p.name; }, '') + '</select></div>' +
      '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
        '<button id="bd_submit" title="新增人员角色机构绑定" aria-label="新增绑定">新增绑定</button></div>' +
      '<div id="bd_msg"></div>');
  }

  function bindingsBindHandler(body) {
    var btn = document.querySelector('#bd_submit');
    if (!btn) return;
    btn.onclick = function () {
      var account = document.querySelector('#bd_account').value;
      var roleId = document.querySelector('#bd_role').value;
      if (!account || !roleId) { DZ.toast('账号与角色为必填', 'warn'); return; }
      var payload = {
        account: account, roleId: roleId,
        orgNodeId: document.querySelector('#bd_org').value || null,
        positionId: document.querySelector('#bd_pos').value || null
      };
      busy(btn, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.post(API.bindCreate, payload);
        if (r && r.error) { DZ.toast('绑定失败：' + (r.error.message || ''), 'bad'); return; }
        DZ.toast('已绑定 ' + account + ' → ' + roleName(roleId) + '，已写入审计', 'ok');
        renderBindings(body);
      });
    };
  }

  function usersCard(users, body) {
    if (!users.length) return card('账号列表', DZ.empty('暂无账号', ''));
    var rows = users.map(function (u) {
      var active = u.status === 'active';
      var multi = (u.roles || []).length > 1;
      return '<tr><td>' + DZ.esc(u.account) + (u.isBootstrap ? ' ' + DZ.badge('unk', '兜底') : '') + '</td>' +
        '<td>' + DZ.esc(u.displayName || '') + (multi ? ' ' + DZ.badge('warn', '多角色') : '') + '</td>' +
        '<td>' + DZ.esc(u.orgNodeName || u.orgNodeId || '—') + '</td>' +
        '<td>' + (u.roles || []).map(function (r) { return DZ.pill(roleName(r)); }).join(' ') + '</td>' +
        '<td>' + DZ.statusBadge(u.status) + '</td>' +
        '<td>' + DZ.date(u.lastLoginAt) + '</td>' +
        '<td><button class="' + (active ? 'ghost' : '') + ' ud_toggle" data-account="' + DZ.esc(u.account) + '" ' +
          'data-status="' + (active ? 'disabled' : 'active') + '" ' +
          'title="' + (active ? '停用账号（即时失效）' : '启用账号') + '" aria-label="' + (active ? '停用账号 ' : '启用账号 ') + DZ.esc(u.account) + '">' +
          (active ? '停用' : '启用') + '</button></td></tr>';
    }).join('');
    var html = card('账号列表（' + users.length + '）',
      '<div class="dz-table-wrap"><table><thead><tr><th>账号</th><th>姓名</th><th>机构</th><th>角色</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
    setTimeout(function () {
      document.querySelectorAll('#bind_users .ud_toggle').forEach(function (b) {
        b.onclick = function () {
          var account = b.dataset.account, status = b.dataset.status;
          busy(b, '处理中…', async function () {
            await DZ.delay(300);
            var r = await DZ.post(API.userStatus(account), { status: status });
            if (r && r.error) { DZ.toast('操作失败：' + (r.error.message || ''), 'bad'); return; }
            if (status === 'disabled') DZ.toast('已停用 ' + account + '：' + ((r && r.effective) || '即时失效') + '，并已写审计', 'ok');
            else DZ.toast('已启用 ' + account + '，并已写审计', 'ok');
            renderBindings(body);
          });
        };
      });
    }, 0);
    return html;
  }

  // =========================================================================
  // 3A. 菜单操作权限（角色 × 菜单 × 操作）
  // =========================================================================
  function roleLabelOf(roles, rid) {
    var f = (roles || []).filter(function (r) { return r.roleId === rid; })[0];
    return f ? f.name : rid;
  }

  async function renderMenu(body) {
    body.innerHTML = '<div id="mp_top">' + DZ.skeleton(2) + '</div>' +
      '<div id="mp_matrix" style="margin-top:14px">' + DZ.skeleton(6) + '</div>';
    var r = await DZ.get(API.menuPerms);
    if (r && r.error) {
      document.querySelector('#mp_top').innerHTML = card('菜单操作权限', fail(r.error, function () { renderMenu(body); }));
      document.querySelector('#mp_matrix').innerHTML = '';
      return;
    }
    S.menuData = r;
    var roles = (r && r.roles) || [];
    var has = roles.some(function (x) { return x.roleId === S.menuRoleSel; });
    if (!has) S.menuRoleSel = (roles[0] || {}).roleId || null;
    renderMenuPanels(body);
  }

  function renderMenuPanels(body) {
    var d = S.menuData || {};
    var roles = d.roles || [];
    var role = S.menuRoleSel;
    var isAdmin = (role === 'sys_admin');
    var roleOpts = roles.map(function (x) {
      return '<option value="' + DZ.esc(x.roleId) + '"' + (x.roleId === role ? ' selected' : '') + '>' + DZ.esc(x.name) + '</option>';
    }).join('');
    var hint = isAdmin
      ? '系统管理员须至少保留「查看」权限，该列不可取消；其余操作可按需调整。'
      : '勾选表示该角色在该功能菜单上拥有的操作；「查看」为其余操作的隐含前提。';
    document.querySelector('#mp_top').innerHTML = card('角色与操作权限',
      '<div class="row" style="justify-content:space-between;flex-wrap:wrap;gap:10px">' +
        '<div class="row" style="gap:8px;align-items:center">' +
          '<label for="mp_role" style="margin:0">角色</label>' +
          '<select id="mp_role" title="选择角色" aria-label="选择角色">' + roleOpts + '</select>' +
        '</div>' +
        '<div class="row" style="gap:8px">' +
          '<button id="mp_all" class="ghost" title="全部菜单全选" aria-label="全部菜单全选">全选</button>' +
          '<button id="mp_clear" class="ghost" title="全部菜单清空" aria-label="全部菜单清空">清空</button>' +
          '<button id="mp_save" title="保存该角色的菜单操作权限" aria-label="保存菜单操作权限">保存</button>' +
        '</div>' +
      '</div>' +
      '<div id="mp_status" class="muted" style="margin-top:8px">' + DZ.esc(hint) + '</div>');
    renderMenuMatrix(body);

    var sel = document.querySelector('#mp_role');
    if (sel) sel.onchange = function () { S.menuRoleSel = sel.value; renderMenuPanels(body); };
    var all = document.querySelector('#mp_all');
    if (all) all.onclick = function () { menuBulk(true); };
    var clr = document.querySelector('#mp_clear');
    if (clr) clr.onclick = function () { menuBulk(false); };
    var save = document.querySelector('#mp_save');
    if (save) save.onclick = function () { menuSave(body, save); };
  }

  function renderMenuMatrix(body) {
    var d = S.menuData || {};
    var role = S.menuRoleSel;
    var isAdmin = (role === 'sys_admin');
    var menus = d.menus || [], actions = d.actions || [], labels = d.actionLabels || {};
    var perm = (d.perms && d.perms[role]) || {};
    var el = document.querySelector('#mp_matrix');
    if (!el) return;
    if (!menus.length || !actions.length) { el.innerHTML = card('菜单 × 操作权限矩阵', DZ.empty('无菜单或操作字典', '')); return; }
    var head = '<tr><th style="min-width:130px">功能菜单</th>' + actions.map(function (a) {
      return '<th title="' + DZ.esc(labels[a] || a) + '">' + DZ.esc(labels[a] || a) + '</th>';
    }).join('') + '<th>整行</th></tr>';
    var rows = menus.map(function (m) {
      var acts = perm[m.key] || [];
      var cells = actions.map(function (a) {
        var on = acts.indexOf(a) >= 0;
        var lock = (isAdmin && a === 'view');
        var lbl = labels[a] || a;
        var cb = lock
          ? '<input type="checkbox" class="mp_cb" data-act="view" checked disabled title="系统管理员须保留查看权限" aria-label="' + DZ.esc(m.label + ' ' + lbl) + '" />'
          : '<input type="checkbox" class="mp_cb" data-act="' + DZ.esc(a) + '"' + (on ? ' checked' : '') +
            ' title="' + DZ.esc(m.label + ' × ' + lbl) + '" aria-label="' + DZ.esc(m.label + ' ' + lbl) + '" />';
        return '<td style="text-align:center">' + cb + '</td>';
      }).join('');
      return '<tr data-menu="' + DZ.esc(m.key) + '"><td><b>' + DZ.esc(m.label) + '</b></td>' + cells +
        '<td style="white-space:nowrap">' +
          '<button class="ghost mp_rowall" title="该行全选" aria-label="' + DZ.esc(m.label) + ' 行全选">全选</button> ' +
          '<button class="ghost mp_rowclear" title="该行清空" aria-label="' + DZ.esc(m.label) + ' 行清空">清空</button>' +
        '</td></tr>';
    }).join('');
    el.innerHTML = card('菜单 × 操作权限矩阵 · ' + roleLabelOf(d.roles, role),
      '<div class="dz-table-wrap"><table><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="muted" style="margin-top:8px">' + (isAdmin ? '系统管理员的「查看」不可取消。' : '可按功能菜单逐行授予或收回操作权限。') + '</div>');

    el.querySelectorAll('tbody tr').forEach(function (tr) {
      var a = tr.querySelector('.mp_rowall'), c = tr.querySelector('.mp_rowclear');
      if (a) a.onclick = function () { tr.querySelectorAll('input.mp_cb').forEach(function (cb) { if (!cb.disabled) cb.checked = true; }); };
      if (c) c.onclick = function () { tr.querySelectorAll('input.mp_cb').forEach(function (cb) { if (!cb.disabled) cb.checked = false; }); };
    });
  }

  function menuBulk(on) {
    var el = document.querySelector('#mp_matrix');
    if (!el) return;
    el.querySelectorAll('input.mp_cb').forEach(function (cb) { if (!cb.disabled) cb.checked = on; });
  }

  function menuSave(body, btn) {
    var d = S.menuData || {};
    var role = S.menuRoleSel;
    var isAdmin = (role === 'sys_admin');
    var menus = d.menus || [];
    var el = document.querySelector('#mp_matrix');
    var st = document.querySelector('#mp_status');
    if (!el) return;
    function setSt(t) { if (st) st.textContent = t; }

    var changed = [];
    el.querySelectorAll('tbody tr').forEach(function (tr) {
      var key = tr.getAttribute('data-menu');
      var arr = [];
      tr.querySelectorAll('input.mp_cb').forEach(function (cb) { if (cb.checked) arr.push(cb.getAttribute('data-act')); });
      if (isAdmin && arr.indexOf('view') < 0) arr.unshift('view');
      var orig = (((d.perms && d.perms[role] && d.perms[role][key]) || []).slice()).sort();
      var next = arr.slice().sort();
      if (orig.join('|') !== next.join('|')) {
        var m = menus.filter(function (x) { return x.key === key; })[0] || { label: key };
        changed.push({ menuKey: key, actions: arr, label: m.label });
      }
    });
    if (!changed.length) { setSt('没有需要保存的变更。'); DZ.toast('权限未发生变化', 'warn'); return; }

    busy(btn, '处理中…', async function () {
      for (var i = 0; i < changed.length; i++) {
        setSt('保存中…（' + i + '/' + changed.length + '）' + changed[i].label);
        var resp = await DZ.put(API.menuPerms, { roleId: role, menuKey: changed[i].menuKey, actions: changed[i].actions });
        if (resp && resp.error) {
          var msg = resp.error.message || '保存失败';
          if (st) st.innerHTML = DZ.banner('bad', msg);
          DZ.toast('保存失败：' + msg, 'bad');
          return;
        }
      }
      DZ.toast('已保存「' + roleLabelOf(d.roles, role) + '」的菜单操作权限（' + changed.length + ' 项），已写入审计', 'ok');
      renderMenu(body);
    });
  }

  // =========================================================================
  // 3B. 数据可见范围（角色 × 组织 / 条线）
  // =========================================================================
  async function renderScope(body) {
    body.innerHTML = '<div id="ds_table">' + DZ.skeleton(5) + '</div>' +
      '<div id="ds_form" style="margin-top:18px"></div>';
    var r = await DZ.get(API.dataScopes);
    if (r && r.error) {
      document.querySelector('#ds_table').innerHTML = card('数据可见范围', fail(r.error, function () { renderScope(body); }));
      document.querySelector('#ds_form').innerHTML = '';
      return;
    }
    S.scopeData = r;
    document.querySelector('#ds_table').innerHTML = scopeTable(r);
    document.querySelector('#ds_form').innerHTML = '';
    document.querySelectorAll('#ds_table .ds_set').forEach(function (b) {
      b.onclick = function () { openScopeForm(b.getAttribute('data-role'), body); };
    });
  }

  function deptNameMap(depts) {
    var m = {};
    (depts || []).forEach(function (d) { m[d.deptId] = d.name; });
    return m;
  }

  function scopeDetail(sc, dmap) {
    if (sc.scopeType !== 'CUSTOM') return '<span class="muted">—</span>';
    var s = sc.scope || {};
    var ds = (s.depts || []).map(function (d) { return dmap[d] || d; });
    var ls = (s.lines || []);
    var parts = [];
    if (ds.length) parts.push('组织：' + ds.join('、'));
    if (ls.length) parts.push('条线：' + ls.join('、'));
    return parts.length ? DZ.esc(parts.join('；')) : '<span class="muted">—</span>';
  }

  function scopeTable(r) {
    var list = (r && r.scopes) || [];
    var dmap = deptNameMap((r && r.depts) || []);
    var types = (r && r.types) || [];
    var descMap = {};
    types.forEach(function (t) { descMap[t.type] = t.desc || ''; });
    if (!list.length) return card('数据可见范围', DZ.empty('暂无角色数据范围', ''));
    var rows = list.map(function (sc) {
      var desc = descMap[sc.scopeType] || '';
      return '<tr><td><b>' + DZ.esc(sc.roleName) + '</b></td>' +
        '<td>' + DZ.esc(sc.scopeLabel) + (desc ? '<div class="muted">' + DZ.esc(desc) + '</div>' : '') + '</td>' +
        '<td>' + scopeDetail(sc, dmap) + '</td>' +
        '<td>' + DZ.esc(sc.updatedBy || '—') + '</td>' +
        '<td>' + DZ.date(sc.updatedAt) + '</td>' +
        '<td><button class="ghost ds_set" data-role="' + DZ.esc(sc.roleId) + '" title="设置数据可见范围" ' +
          'aria-label="设置 ' + DZ.esc(sc.roleName) + ' 的数据可见范围">设置</button></td></tr>';
    }).join('');
    return card('数据可见范围（' + list.length + '）',
      '<div class="dz-table-wrap"><table><thead><tr><th>角色</th><th>可见范围类型</th><th>自定义范围</th><th>更新人</th><th>更新时间</th><th>操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
  }

  function openScopeForm(roleId, body) {
    var d = S.scopeData || {};
    var sc = (d.scopes || []).filter(function (x) { return x.roleId === roleId; })[0] || {};
    var types = d.types || [];
    var depts = d.depts || [];
    var curType = sc.scopeType || (types[0] && types[0].type) || '';
    var curScope = sc.scope || {};
    var typeOpts = types.map(function (t) {
      return '<option value="' + DZ.esc(t.type) + '"' + (t.type === curType ? ' selected' : '') + '>' + DZ.esc(t.label) + '</option>';
    }).join('');
    var selDepts = {};
    (curScope.depts || []).forEach(function (x) { selDepts[x] = 1; });
    var deptOpts = depts.map(function (dp) {
      return '<option value="' + DZ.esc(dp.deptId) + '"' + (selDepts[dp.deptId] ? ' selected' : '') + '>' +
        DZ.esc(dp.name + '（' + levelLabel(dp.level) + '）') + '</option>';
    }).join('');
    var linesVal = (curScope.lines || []).join(',');

    document.querySelector('#ds_form').innerHTML = card('设置数据可见范围 · ' + DZ.esc(sc.roleName || roleLabelOf(S.roles, roleId)),
      '<div class="form-narrow">' +
        '<div><label for="ds_type">范围类型</label><select id="ds_type">' + typeOpts + '</select>' +
          '<div id="ds_type_desc" class="muted" style="margin-top:4px"></div></div>' +
        '<div id="ds_custom" style="margin-top:12px">' +
          '<label for="ds_depts">自定义组织（可多选）</label>' +
          '<select id="ds_depts" multiple size="6" aria-label="自定义组织">' + deptOpts + '</select>' +
          '<div style="margin-top:10px"><label for="ds_lines">自定义条线编码（逗号分隔，可留空）</label>' +
            '<input id="ds_lines" value="' + DZ.esc(linesVal) + '" placeholder="多个条线编码以逗号分隔，可留空" autocomplete="off" /></div>' +
        '</div>' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:12px">' +
          '<button id="ds_save" title="保存数据可见范围" aria-label="保存数据可见范围">保存</button>' +
          '<button id="ds_cancel" class="ghost" title="取消设置" aria-label="取消设置">取消</button>' +
        '</div>' +
        '<div id="ds_msg"></div>' +
      '</div>');

    var typeSel = document.querySelector('#ds_type');
    function syncDesc() {
      var t = types.filter(function (x) { return x.type === typeSel.value; })[0] || {};
      var dsc = document.querySelector('#ds_type_desc');
      if (dsc) dsc.textContent = t.desc || '';
      var cus = document.querySelector('#ds_custom');
      if (cus) cus.classList.toggle('hidden', typeSel.value !== 'CUSTOM');
    }
    typeSel.onchange = syncDesc;
    syncDesc();

    var cancel = document.querySelector('#ds_cancel');
    if (cancel) cancel.onclick = function () { document.querySelector('#ds_form').innerHTML = ''; };
    var save = document.querySelector('#ds_save');
    if (save) save.onclick = function () {
      var st = typeSel.value;
      var scope = {};
      if (st === 'CUSTOM') {
        var dep = [];
        document.querySelectorAll('#ds_depts option:checked').forEach(function (o) { dep.push(o.value); });
        var ln = (document.querySelector('#ds_lines').value || '').split(',').map(function (x) { return x.trim(); }).filter(function (x) { return x; });
        if (!dep.length && !ln.length) { DZ.toast('自定义范围须至少指定一个组织或条线', 'warn'); return; }
        scope = { depts: dep, lines: ln };
      }
      busy(save, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.put(API.dataScope(roleId), { scopeType: st, scope: scope });
        if (r && r.error) {
          var msg = r.error.message || '保存失败';
          var m = document.querySelector('#ds_msg');
          if (m) m.innerHTML = DZ.banner('bad', msg);
          DZ.toast('保存失败：' + msg, 'bad');
          return;
        }
        DZ.toast('已更新「' + (sc.roleName || roleId) + '」的数据可见范围，已写入审计', 'ok');
        renderScope(body);
      });
    };
  }

  // =========================================================================
  // 3C. 单点登录（轻量对接统一身份源）
  // =========================================================================
  async function renderSso(body) {
    body.innerHTML = '<div id="sso_card">' + DZ.skeleton(4) + '</div>' +
      '<div id="sso_form" style="margin-top:18px">' + DZ.skeleton(4) + '</div>';
    var res = await Promise.all([DZ.get(API.ssoConfig), DZ.get(API.users, { delay: false })]);
    var r = res[0], us = res[1];
    if (r && r.error) {
      document.querySelector('#sso_card').innerHTML = card('单点登录', fail(r.error, function () { renderSso(body); }));
      document.querySelector('#sso_form').innerHTML = '';
      return;
    }
    var nameMap = {};
    ((us && us.users) || []).forEach(function (u) { nameMap[u.account] = u.displayName || u.account; });
    S.ssoData = r; S.ssoNames = nameMap;
    renderSsoPanels(body);
  }

  function ssoMetric(k, v) {
    return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
      '<span class="dz-metric-v" style="text-align:right">' + v + '</span></div>';
  }

  function renderSsoPanels(body) {
    var d = S.ssoData || {};
    var cfg = d.config || {};
    var protocols = d.protocols || [];
    var syncModes = d.syncModes || [];
    var names = S.ssoNames || {};
    var updBy = cfg.updatedBy ? (names[cfg.updatedBy] || cfg.updatedBy) : '—';

    document.querySelector('#sso_card').innerHTML = card('当前配置',
      '<div class="dz-metric"><span class="dz-metric-k">启用状态</span>' +
        '<span class="dz-metric-v">' + (cfg.enabled ? DZ.badge('ok', '已启用') : DZ.badge('unk', '未启用')) + '</span></div>' +
      ssoMetric('协议', DZ.esc(cfg.protocol || '—')) +
      ssoMetric('发行方地址', DZ.esc(cfg.issuer || '—')) +
      ssoMetric('客户端标识', DZ.esc(cfg.clientId || '—')) +
      ssoMetric('账号映射说明', DZ.esc(cfg.mapping || '—')) +
      ssoMetric('同步方式', DZ.esc(cfg.syncMode || '—')) +
      ssoMetric('自动开通账号', cfg.jitProvision ? DZ.badge('ok', '首次登录自动开通') : DZ.badge('unk', '不自动开通')) +
      ssoMetric('最近更新', DZ.esc(updBy) + ' · ' + DZ.date(cfg.updatedAt)));

    var protoOpts = protocols.map(function (p) {
      return '<option value="' + DZ.esc(p) + '"' + (p === cfg.protocol ? ' selected' : '') + '>' + DZ.esc(p) + '</option>';
    }).join('');
    var syncOpts = syncModes.map(function (m) {
      return '<option value="' + DZ.esc(m) + '"' + (m === cfg.syncMode ? ' selected' : '') + '>' + DZ.esc(m) + '</option>';
    }).join('');

    document.querySelector('#sso_form').innerHTML = card('编辑配置',
      '<div class="form-narrow">' +
        '<div class="grid2">' +
          '<div><label for="sso_proto">协议</label><select id="sso_proto">' + protoOpts + '</select></div>' +
          '<div><label for="sso_sync">同步方式</label><select id="sso_sync">' + syncOpts + '</select></div>' +
        '</div>' +
        '<div><label for="sso_issuer">发行方地址 *</label><input id="sso_issuer" value="' + DZ.esc(cfg.issuer || '') + '" placeholder="如：https://sso.example.com/realms/datasec" autocomplete="off" /></div>' +
        '<div><label for="sso_client">客户端标识</label><input id="sso_client" value="' + DZ.esc(cfg.clientId || '') + '" autocomplete="off" /></div>' +
        '<div><label for="sso_mapping">账号映射说明</label><input id="sso_mapping" value="' + DZ.esc(cfg.mapping || '') + '" autocomplete="off" /></div>' +
        '<div class="row" style="gap:18px;margin-top:10px;flex-wrap:wrap">' +
          '<label class="pick"><input type="checkbox" id="sso_enabled"' + (cfg.enabled ? ' checked' : '') + ' />' +
            '<span class="pick-name">启用单点登录</span></label>' +
          '<label class="pick"><input type="checkbox" id="sso_jit"' + (cfg.jitProvision ? ' checked' : '') + ' />' +
            '<span class="pick-name">首次登录自动开通账号</span></label>' +
        '</div>' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:12px">' +
          '<button id="sso_save" title="保存单点登录配置" aria-label="保存单点登录配置">保存</button>' +
        '</div>' +
        '<div id="sso_msg"></div>' +
      '</div>');

    var save = document.querySelector('#sso_save');
    if (save) save.onclick = function () {
      var payload = {
        enabled: document.querySelector('#sso_enabled').checked,
        protocol: document.querySelector('#sso_proto').value,
        issuer: (document.querySelector('#sso_issuer').value || '').trim(),
        clientId: (document.querySelector('#sso_client').value || '').trim(),
        mapping: (document.querySelector('#sso_mapping').value || '').trim(),
        syncMode: document.querySelector('#sso_sync').value,
        jitProvision: document.querySelector('#sso_jit').checked
      };
      if (payload.enabled && !payload.issuer) { DZ.toast('启用单点登录须填写身份源地址', 'warn'); return; }
      busy(save, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.put(API.ssoConfig, payload);
        if (r && r.error) {
          var msg = r.error.message || '保存失败';
          var m = document.querySelector('#sso_msg');
          if (m) m.innerHTML = DZ.banner('bad', msg);
          DZ.toast('保存失败：' + msg, 'bad');
          return;
        }
        DZ.toast('单点登录配置已保存，已写入审计', 'ok');
        renderSso(body);
      });
    };

    var syncList = syncModes.length
      ? '<ul style="margin:6px 0 0;padding-left:18px">' + syncModes.map(function (m) { return '<li>' + DZ.esc(m) + '</li>'; }).join('') + '</ul>'
      : '<div class="muted">—</div>';
    document.querySelector('#sso_form').insertAdjacentHTML('beforeend',
      card('可选账号同步方式',
        '<div class="muted">按身份源同步账号信息的方式：</div>' + syncList));
  }

  // =========================================================================
  // 4. 文号注册三步接入（K1.3 / 零代码扩展）
  // =========================================================================
  async function renderDocReg(body) {
    body.innerHTML = '<div id="dr_steps"></div>' +
      '<div id="dr_table">' + DZ.skeleton(4) + '</div>' +
      '<div id="dr_form" style="margin-top:18px">' + DZ.skeleton(4) + '</div>';

    var r = await DZ.get(API.docReg);
    if (r && r.error) {
      document.querySelector('#dr_table').innerHTML = card('文号注册表', fail(r.error, function () { renderDocReg(body); }));
      document.querySelector('#dr_form').innerHTML = '';
      return;
    }
    S.docs = (r && r.docs) || [];
    renderDocSteps(S.docs);
    document.querySelector('#dr_table').innerHTML = docTableCard(S.docs, body);
    document.querySelector('#dr_form').innerHTML = docFormCard(body);
    docFormBind(body);
  }

  function renderDocSteps(docs) {
    var pending = (docs || []).filter(function (d) { return d.status === 'pending'; }).length;
    var steps = [
      { no: '1', label: '登记新文号', hint: '登记后状态为「待确认」', state: 'done' },
      { no: '2', label: '上传样例·适配器推断结构', hint: '待确认 · 自动推断结构', state: pending ? 'on' : 'done' },
      { no: '3', label: '确认结构映射 → 已接入', hint: '确认后状态更新为「已接入」', state: pending ? '' : 'done' }
    ];
    document.querySelector('#dr_steps').innerHTML = card('文号接入三步',
      '<ul class="dz-steps">' + steps.map(function (s) {
        return '<li class="dz-step ' + s.state + '" title="' + DZ.esc(s.hint) + '" aria-label="步骤 ' + s.no + ' ' + DZ.esc(s.label) + '">' +
          '<span class="dz-step-no">' + s.no + '</span>' + DZ.esc(s.label) + '</li>';
      }).join('') + '</ul>' +
      '<div class="muted">当前待确认文号 ' + pending + ' 个。</div>');
  }

  function docTableCard(docs, body) {
    if (!docs.length) return card('文号注册表', DZ.empty('暂无文号，可在下方登记', ''));
    var rows = docs.map(function (d) {
      var sp = d.structureProfile || {};
      var levels = (sp.levels || []).join(' / ') || '—';
      var pending = d.status === 'pending';
      return '<tr><td><code>' + DZ.esc(d.docKey) + '</code></td>' +
        '<td>' + DZ.esc(d.docNo || '—') + '</td>' +
        '<td>' + DZ.esc(d.title || '—') + '</td>' +
        '<td>' + DZ.esc(d.issuingBody || '—') + '</td>' +
        '<td>' + DZ.esc(d.effectiveDate || '—') + '</td>' +
        '<td><span class="dz-tag-soft">' + DZ.esc(levels) + '</span> <span class="muted">' + DZ.esc(sp.checkPattern || '') + '</span></td>' +
        '<td>' + DZ.number(d.checkCount || 0) + '</td>' +
        '<td>' + DZ.statusBadge(d.status) + '</td>' +
        '<td>' + (pending
          ? '<button class="dc_confirm" data-key="' + DZ.esc(d.docKey) + '" title="确认结构映射（第③步）" aria-label="确认结构映射 ' + DZ.esc(d.docKey) + '">确认映射</button>'
          : '<span class="muted">已接入</span>') + '</td></tr>';
    }).join('');
    setTimeout(function () {
      document.querySelectorAll('#dr_table .dc_confirm').forEach(function (b) {
        b.onclick = function () {
          var key = b.dataset.key;
          busy(b, '处理中…', async function () {
            await DZ.delay(300);
            var cur = (S.docs || []).filter(function (x) { return x.docKey === key; })[0] || {};
            var r = await DZ.patch(API.docConfirm(key), { structureProfile: cur.structureProfile || {} });
            if (r && r.error) { DZ.toast('确认失败：' + (r.error.message || ''), 'bad'); return; }
            DZ.toast('已确认 ' + key + ' 结构映射，状态更新为「已接入」，并写审计', 'ok');
            renderDocReg(body);
          });
        };
      });
    }, 0);
    return card('文号注册表（' + docs.length + '）',
      '<div class="dz-table-wrap"><table><thead><tr><th>文号键</th><th>文号</th><th>标题</th><th>发布机构</th><th>生效日</th><th>结构映射</th><th>检查项</th><th>状态</th><th>操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
  }

  function docFormCard(body) {
    return card('登记新文号（第 ① 步）',
      '<div class="grid2">' +
        '<div><label for="dr_key">文号键 *</label><input id="dr_key" placeholder="如：pboc8" autocomplete="off" /></div>' +
        '<div><label for="dr_no">文号 *</label><input id="dr_no" placeholder="如：中国人民银行令〔2026〕第8号" autocomplete="off" /></div>' +
      '</div>' +
      '<div><label for="dr_title">标题</label><input id="dr_title" placeholder="办法 / 通知名称" autocomplete="off" /></div>' +
      '<div class="grid2">' +
        '<div><label for="dr_body">发布机构</label><input id="dr_body" placeholder="如：中国人民银行" autocomplete="off" /></div>' +
        '<div><label for="dr_eff">生效日期</label><input id="dr_eff" type="date" /></div>' +
      '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
        '<button id="dr_submit" title="登记新文号（第①步）" aria-label="登记新文号">登记新文号</button></div>' +
      '<div id="dr_msg"></div>');
  }

  function docFormBind(body) {
    var btn = document.querySelector('#dr_submit');
    if (!btn) return;
    btn.onclick = function () {
      var docKey = (document.querySelector('#dr_key').value || '').trim();
      var docNo = (document.querySelector('#dr_no').value || '').trim();
      if (!docKey || !docNo) { DZ.toast('文号键与文号为必填', 'warn'); return; }
      var payload = {
        docKey: docKey, docNo: docNo,
        title: (document.querySelector('#dr_title').value || '').trim() || null,
        issuingBody: (document.querySelector('#dr_body').value || '').trim() || null,
        effectiveDate: document.querySelector('#dr_eff').value || null
      };
      busy(btn, '处理中…', async function () {
        await DZ.delay(300);
        var r = await DZ.post(API.docReg, payload);
        if (r && r.error) { DZ.toast('登记失败：' + (r.error.message || ''), 'bad'); return; }
        var ns = (r && r.nextSteps) || [];
        DZ.toast('已登记「' + docKey + '」（待确认），已写审计；下一步：' + (ns.join('；') || '上传样例 → 确认映射'), 'ok');
        renderDocReg(body);
      });
    };
  }

  // =========================================================================
  // 5. 审计日志（G3 / 只追加）
  // =========================================================================
  function auditFilterBar() {
    // 统一走扁平筛选行组件：控件不再依赖内联 width:auto，且同排一行
    return DZ.filterBar([
      { label: '起始', html: '<input id="au_from" type="datetime-local" title="起始时间" aria-label="起始时间" />' },
      { label: '结束', html: '<input id="au_to" type="datetime-local" title="结束时间" aria-label="结束时间" />' },
      { label: '操作者', html: '<input id="au_actor" placeholder="操作者账号" title="操作者账号" aria-label="操作者账号" />' },
      { label: '动作', html: '<input id="au_action" placeholder="中文或代码，模糊匹配" title="动作" aria-label="动作" />' },
      { label: '条数', html: '<select id="au_limit" title="返回条数" aria-label="返回条数">' +
        ['50', '100', '200', '500'].map(function (n) { return '<option' + (n === '100' ? ' selected' : '') + '>' + n + '</option>'; }).join('') +
        '</select>' }
    ], {
      aria: '审计日志筛选',
      end: '<button id="au_query" title="查询审计日志" aria-label="查询审计日志">查询</button>' +
        '<button id="au_reset" class="ghost" title="重置筛选" aria-label="重置筛选">重置</button>' +
        '<button id="au_export" class="ghost" title="导出记录表（导出动作本身留痕）" aria-label="导出审计记录表">导出记录表</button>'
    });
  }

  async function renderAudit(body) {
    body.innerHTML = auditFilterBar() +
      card('哈希链（只追加）', '<div id="au_chain">' + DZ.skeleton(2) + '</div>') +
      '<div id="au_table">' + DZ.skeleton(6) + '</div>';
    var q = document.querySelector('#au_query');
    var rs = document.querySelector('#au_reset');
    var ex = document.querySelector('#au_export');
    if (q) q.onclick = function () { loadAudit(); };
    if (rs) rs.onclick = function () {
      ['#au_from', '#au_to', '#au_actor', '#au_action'].forEach(function (s) { var e = document.querySelector(s); if (e) e.value = ''; });
      loadAudit();
    };
    if (ex) ex.onclick = function () { exportCsv(ex); };
    loadAudit();
  }

  async function loadAudit() {
    var tbl = document.querySelector('#au_table');
    if (tbl) tbl.innerHTML = DZ.skeleton(6);
    var p = new URLSearchParams();
    var from = document.querySelector('#au_from'), to = document.querySelector('#au_to');
    var actor = document.querySelector('#au_actor'), action = document.querySelector('#au_action'), lim = document.querySelector('#au_limit');
    if (from && from.value) p.set('from', from.value.replace('T', 'T'));
    if (to && to.value) p.set('to', to.value.replace('T', 'T'));
    if (actor && actor.value) p.set('actor', actor.value.trim());
    if (action && action.value) p.set('action', DZ.actionCode(action.value));
    p.set('limit', (lim && lim.value) || '100');

    var r = await DZ.get(API.audit + '?' + p.toString());
    if (!tbl) return;
    if (r && r.error) { tbl.innerHTML = card('审计日志', fail(r.error, function () { loadAudit(); })); return; }

    var chain = document.querySelector('#au_chain');
    if (chain) {
      var ok = !!(r && r.chainOk);
      chain.innerHTML = '<div>' + (ok ? DZ.badge('ok', '哈希链完整') : DZ.badge('bad', '哈希链校验失败')) + '</div>';
    }

    var list = (r && r.audit) || [];
    if (!list.length) { tbl.innerHTML = card('审计日志', DZ.empty('无匹配的审计记录，请调整筛选条件', '<button class="ghost" onclick="document.querySelector(\'#au_reset\').click()">重置筛选</button>')); return; }
    var rows = list.map(function (a) {
      var params = a.params ? JSON.stringify(a.params) : '{}';
      return '<tr><td>' + DZ.date(a.ts) + '</td>' +
        '<td>' + DZ.esc(a.actor) + '<div class="muted">' + DZ.esc(a.actorName || '') + '</div></td>' +
        '<td><span title="' + DZ.esc(a.action) + '">' + DZ.esc(DZ.actionLabel(a.action)) + '</span></td>' +
        '<td>' + DZ.esc(a.target || '—') + '</td>' +
        '<td style="max-width:260px"><span class="muted" title="' + DZ.esc(params) + '">' + DZ.esc(params.length > 60 ? params.slice(0, 60) + '…' : params) + '</span></td>' +
        '<td>' + resultBadgeAudit(a.result) + '</td>' +
        '<td style="font-family:ui-monospace,Menlo,monospace;font-size:11.5px">' +
          '<span class="muted" title="前序哈希=' + DZ.esc(a.prevHash || '') + '">' + DZ.esc((a.prevHash || '').slice(0, 10)) + '</span>' +
          ' → <span title="当前哈希=' + DZ.esc(a.hash || '') + '">' + DZ.esc((a.hash || '').slice(0, 10)) + '…</span></td></tr>';
    }).join('');
    tbl.innerHTML = card('审计日志（' + list.length + ' 条）',
      '<div class="dz-table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>参数</th><th>结果</th><th>哈希链</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>');
  }

  function resultBadgeAudit(res) {
    var k = String(res == null ? '' : res);
    var m = { ok: ['ok', '成功'], degraded: ['warn', '降级'], fail: ['bad', '失败'], failed: ['bad', '失败'], denied: ['bad', '拒绝'], error: ['bad', '错误'], forbidden_sod: ['bad', '职责分离拦截'], forbidden: ['bad', '已拦截'], blocked: ['bad', '已拦截'] };
    var x = m[k] || ['unk', k || '—'];
    return DZ.badge(x[0], x[1]);
  }

  async function exportCsv(btn) {
    busy(btn, '导出中…', async function () {
      await DZ.delay(300);
      try {
        var resp = await fetch(API.auditExport + '?limit=500');
        var text = await resp.text();
        var blob = new Blob([text], { type: 'text/csv;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = '审计日志.csv';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
        DZ.toast('已导出记录表；导出动作本身已写入审计（只追加）', 'ok');
        loadAudit();
      } catch (e) {
        DZ.toast('导出失败：' + ((e && e.message) || e), 'bad');
      }
    });
  }

  // =========================================================================
  // 6. 治理看板（G2.8）
  // =========================================================================
  async function renderGov(body) {
    body.innerHTML = '<div id="gv_kpi">' + DZ.skeleton(4) + '</div>' +
      '<div class="grid2" id="gv_bars">' + DZ.skeleton(4) + '</div>';
    var d = await DZ.get(API.gov);
    if (d && d.error) {
      document.querySelector('#gv_kpi').innerHTML = fail(d.error, function () { renderGov(body); });
      document.querySelector('#gv_bars').innerHTML = '';
      return;
    }
    var audit = (d && d.audit) || {};
    var rebuild = (d && d.rebuild) || {};
    var kq = (d && d.knowledgeQuality) || {};

    document.querySelector('#gv_kpi').innerHTML = '<div class="dz-kpi-row is-compact">' +
      DZ.kpi('审计留痕总数', DZ.number(audit.total || 0), '只追加不可改写') +
      DZ.kpi('哈希链校验', audit.chainOk ? '通过' : '失败', '前序哈希 → 当前哈希', audit.chainOk ? 'ok' : 'bad') +
      DZ.kpi('来源命中率', pct(d && d.sourceHitRate), '知识取数命中真实来源占比', 'ok') +
      DZ.kpi('降级率', pct(d && d.degradeRate), '插件降级自动转人工', (Number(d && d.degradeRate) > 0.2 ? 'warn' : 'ok')) +
      DZ.kpi('工具 / 插件调用量', DZ.number(d && d.mcpCalls), '插件调用累计') +
      DZ.kpi('知识质量评分', pct(kq.score), '清单一致性加权') +
      DZ.kpi('当前发布版本', DZ.esc(rebuild.currentVersion || '—'), '当前生效版本') +
      '</div>';

    var bars = '';
    bars += card('审计结果分布', barList(audit.byResult, audit.total || 1, { ok: '成功', degraded: '降级', failed: '失败', denied: '拒绝' }));
    bars += card('重建作业统计', barList(listToMap(rebuild.runs), sumCounts(rebuild.runs), { success: '成功', failed: '失败', running: '进行中', partial: '部分' }) +
      '<div class="muted" style="margin-top:8px">当前版本：<code>' + DZ.esc(rebuild.currentVersion || '—') + '</code></div>');
    bars += card('来源命中率 / 降级率', barList({ '来源命中': d.sourceHitRate, '降级': d.degradeRate }, 1, null));
    bars += card('知识质量 · 清单状态', barList(listToMap(kq.manifest), sumCounts(kq.manifest), { published: '已发布', pending: '待发布', failed: '失败', draft: '草稿' }) +
      '<div class="muted" style="margin-top:8px">综合评分：' + pct(kq.score) + '。</div>');

    document.querySelector('#gv_bars').innerHTML = bars;
  }

  function listToMap(arr) {
    var m = {};
    (arr || []).forEach(function (x) { m[x.status] = x.count; });
    return m;
  }
  function sumCounts(arr) {
    var s = 0; (arr || []).forEach(function (x) { s += Number(x.count || 0); }); return s || 1;
  }
  function barList(map, total, labelMap) {
    var entries = Object.keys(map || {});
    if (!entries.length) return '<div class="muted">暂无数据</div>';
    return entries.map(function (k) {
      var n = Number(map[k] || 0);
      var p = 0;
      if (total && total > 1) p = (n / total) * 100;
      else p = n <= 1 ? n * 100 : n; // 已是比例
      p = Math.max(0, Math.min(100, Math.round(p)));
      var label = (labelMap && labelMap[k]) || k;
      return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(label) + '</span>' +
        '<span class="dz-metric-v" style="min-width:180px;display:flex;align-items:center;gap:10px;justify-content:flex-end">' +
          DZ.bar(p) + '<span>' + DZ.number(n) + (total > 1 ? '' : '') + '</span></span></div>';
    }).join('');
  }

  // =========================================================================
  // 注册视图初始化（两个菜单各注册一个：gov / perm）
  // =========================================================================
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['gov'] = function () {
    // 权限与组织：每次进入视图重新渲染（幂等；保留当前页签与选择）
    VIEW = 'gov';
    init();
  };
  window.DEMO_VIEW_INIT['perm'] = function () {
    // 权限策略与审计：每次进入视图重新渲染（幂等；保留当前页签与选择）
    VIEW = 'perm';
    init();
  };
})();
