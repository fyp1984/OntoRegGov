/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   安全治理（多角色互动闭环工作流） · demo_issues.js
   视图 id：issues   容器：#issues_root   菜单：安全治理（诊断与治理）
   页签（按流程）：问题清单 / 处置详情 / 复检反馈

   闭环：自查发现问题 → 定级拆分 → 下发治理工单 → 部门接收 → 整改回复（附工作证明）
        → 复检反馈 → 人工核查确认 → 确认归档；并含「退回重办」分支。
   读：GET /api/gov/issues、GET /api/gov/issues/{id}、GET /api/admin/org-positions
   写：POST /api/gov/issues（手工创建待治理问题）
      POST /api/gov/issues/{id}/transition（triage/dispatch/accept/start/respond/recheck/confirm/close/reject）

   仅使用 window.DZ.* 与既有 dz-* 类；全程先骨架屏、失败给可重试提示条、无数据渲染空态。
   状态与严重程度一律取后端返回的中文标签，不直接渲染英文状态码。
   ============================================================ */
(function(){
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    list:       '/api/gov/issues',
    detail:     function(id){ return '/api/gov/issues/' + encodeURIComponent(id); },
    create:     '/api/gov/issues',
    transition: function(id){ return '/api/gov/issues/' + encodeURIComponent(id) + '/transition'; },
    positions:  '/api/admin/org-positions'
  };

  // 状态码 → 徽章配色（文案一律用后端 statusLabel）
  var ST_KIND = {
    open:'unk', triaged:'warn', dispatched:'warn', accepted:'warn',
    remediating:'warn', responded:'warn', rechecking:'warn',
    pending_confirm:'warn', closed:'ok'
  };
  // 动作名兜底（优先用后端 actions[].name）
  var ACT_NAME = {
    triage:'定级拆分', dispatch:'下发处置工单', accept:'接收工单', start:'启动整改',
    respond:'提交整改回复', recheck:'提交复检反馈', confirm:'提交核查确认',
    close:'确认归档', reject:'退回重办'
  };

  // 页签定义（按流程排序）
  var TABS = [
    { key:'list',    label:'问题清单' },
    { key:'detail',  label:'处置详情' },
    { key:'recheck', label:'复检反馈' }
  ];
  // 复检反馈相关动作（归入「复检反馈」页签，其余处置动作留在「处置详情」页签）
  var RECHECK_CODES = { recheck:1, confirm:1, close:1, reject:1 };

  // 视图内常驻状态（跨重入保留筛选与选中项）
  var S = {
    tab: 'list',
    data: null, detail: null, sel: null,
    positions: [],
    f: { status:'', source:'', severity:'' },
    mode: 'none', action: null, busy: false
  };

  /* ---------------- DOM 便捷（限定在 #issues_root 内，避免 document 级监听） ---------------- */
  function rootEl(){ return document.getElementById('issues_root'); }
  function q(s){ var r = rootEl(); return r ? r.querySelector(s) : null; }
  function qq(s){ var r = rootEl(); return r ? Array.prototype.slice.call(r.querySelectorAll(s)) : []; }
  function each(s, fn){ qq(s).forEach(fn); }
  function val(s){ var el = q(s); return el ? String(el.value == null ? '' : el.value) : ''; }

  function errMsg(r){ return (r && r.error && (r.error.message || r.error.code)) || '接口不可达'; }

  /* ---------------- 语义小工具 ---------------- */
  function statusBadge(it){
    var k = ST_KIND[it.status] || 'unk';
    return DZ.badge(k, it.statusLabel || '—');
  }
  function actionName(code){
    var list = (S.data && S.data.actions) || [];
    var hit = null;
    for (var i=0;i<list.length;i++){ if (list[i].action === code){ hit = list[i]; break; } }
    return (hit && hit.name) || ACT_NAME[code] || '流转';
  }
  function sources(){ return (S.data && S.data.sources) || ['自查发现','监管检查','内部审计','事件驱动']; }
  function categories(){ return (S.data && S.data.categories) || ['治理层','流程层','资产层','技术层']; }
  function severities(){
    return (S.data && S.data.severities) ||
      [{value:'high',label:'高'},{value:'medium',label:'中'},{value:'low',label:'低'}];
  }
  function optList(list, sel){
    return (list || []).map(function(x){
      return '<option value="' + DZ.esc(x) + '"' + (x === sel ? ' selected' : '') + '>' + DZ.esc(x) + '</option>';
    }).join('');
  }
  function sevOptions(sel){
    return severities().map(function(s){
      return '<option value="' + DZ.esc(s.value) + '"' + (s.value === sel ? ' selected' : '') + '>' + DZ.esc(s.label) + '</option>';
    }).join('');
  }

  // 部门候选取自组织岗位表的去重组织节点
  function orgList(){
    var seen = {}, out = [];
    S.positions.forEach(function(p){
      if (p.orgNodeId && !seen[p.orgNodeId]){ seen[p.orgNodeId] = 1; out.push({ id:p.orgNodeId, name:p.orgNodeName }); }
    });
    return out;
  }
  function deptOptions(sel, placeholder){
    var ph = placeholder || '请选择责任部门';
    return '<option value="">' + DZ.esc(ph) + '</option>' + orgList().map(function(o){
      return '<option value="' + DZ.esc(o.id) + '"' + (o.id === sel ? ' selected' : '') + '>' + DZ.esc(o.name) + '</option>';
    }).join('');
  }
  function posOptions(orgId, sel){
    if (!orgId) return '<option value="">请先选择责任部门</option>';
    var list = S.positions.filter(function(p){ return p.orgNodeId === orgId; });
    if (!list.length) return '<option value="">该部门暂无岗位</option>';
    return '<option value="">请选择责任岗位</option>' + list.map(function(p){
      return '<option value="' + DZ.esc(p.positionId) + '"' + (p.positionId === sel ? ' selected' : '') + '>' + DZ.esc(p.name) + '</option>';
    }).join('');
  }

  // 期限提示（临近 / 逾期）
  function daysLeft(due){
    var d = new Date(String(due) + 'T23:59:59');
    return Math.ceil((d.getTime() - Date.now()) / 86400000);
  }
  function slaClass(due, status){
    if (!due || status === 'closed') return 'ok';
    var n = daysLeft(due);
    if (isNaN(n)) return '';
    if (n < 0) return 'over';
    if (n <= 3) return 'soon';
    return 'ok';
  }
  function slaText(it){
    if (!it.dueDate) return '<span class="muted">未指定</span>';
    var cls = slaClass(it.dueDate, it.status);
    var n = daysLeft(it.dueDate);
    var hint = '';
    if (it.status === 'closed') hint = '（已归档）';
    else if (!isNaN(n) && n < 0) hint = '（已逾期）';
    else if (!isNaN(n) && n <= 3) hint = '（临近）';
    return '<span class="dz-sla ' + cls + '">' + DZ.esc(it.dueDate) + hint + '</span>';
  }

  function metricKV(k, vHtml){
    return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
      '<span class="dz-metric-v">' + vHtml + '</span></div>';
  }
  function metricText(k, text){
    return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
      '<span class="dz-metric-v" style="font-weight:400;text-align:right;max-width:68%">' +
      DZ.esc(text == null || text === '' ? '—' : text) + '</span></div>';
  }

  function setMsg(html){ var el = q('#iss_msg'); if (el) el.innerHTML = html || ''; }
  function setActMsg(html){ var el = q('#iss_action_msg'); if (el) el.innerHTML = html || ''; }
  function busyBtn(btn){ if (btn){ btn.disabled = true; btn.textContent = '处理中…'; } }
  function restoreBtn(btn, label){ if (btn){ btn.disabled = false; btn.textContent = label; } }

  /* ---------------- 视图装载 ---------------- */
  function shell(){
    return '' +
      '<div id="is_tabs"></div>' +
      '<div id="iss_msg"></div>' +
      '<div id="is_pane" class="dz-pane"></div>';
  }

  function mount(){
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    renderTabs();
    load(false);
  }

  /* ---------------- 页签 ---------------- */
  function renderTabs(){
    DZ.tabs('#is_tabs', TABS.map(function(t){ return { key:t.key, label:t.label }; }), S.tab, function(k){
      S.tab = k;
      renderPane();
    });
  }

  function switchTab(k){
    S.tab = k;
    renderTabs();
    renderPane();
  }

  function renderPane(){
    var box = q('#is_pane');
    if (!box) return;
    if (S.tab === 'detail'){
      box.innerHTML = '<div id="iss_detail"></div>';
      loadDetailInto('#iss_detail', detailBodyHtml);
    } else if (S.tab === 'recheck'){
      box.innerHTML = '<div id="iss_recheck"></div>';
      loadDetailInto('#iss_recheck', recheckBodyHtml);
    } else {
      box.innerHTML = '<div id="iss_listpane"></div>';
      renderListPane();
    }
  }

  /* ---------------- 取数 ---------------- */
  async function load(force){
    if (S.data && !force){ renderAll(); return; }
    if (!S.data) renderPane();     // 首次进入先渲染骨架屏占位

    var out = await Promise.all([DZ.get(API.list), DZ.get(API.positions)]);
    var res = out[0], pos = out[1];

    if (!res || res.error){
      setMsg('');
      var box = q('#is_pane');
      if (box){
        box.innerHTML = DZ.banner('bad', '治理问题数据加载失败：' + errMsg(res), function(){ load(true); });
      }
      var meta0 = q('#iss_meta'); if (meta0) meta0.textContent = '';
      return;
    }

    S.data = res;
    S.positions = (pos && !pos.error && Array.isArray(pos.positions))
      ? pos.positions.filter(function(p){ return p.status === 'active'; })
      : [];
    renderAll();
  }

  function renderAll(){
    renderTabs();
    renderPane();
  }

  function renderMeta(){
    var el = q('#iss_meta');
    if (!el) return;
    el.textContent = S.data ? ('取数时间 ' + DZ.date(S.data.fetchedAt || '')) : '';
  }

  /* ---------------- KPI 指标 ---------------- */
  function renderKpis(){
    var box = q('#iss_kpis');
    if (!box) return;
    var s = (S.data && S.data.summary) || {};
    var bs = s.byStatus || {};
    box.innerHTML =
      DZ.kpi('问题总数', DZ.number(s.total || 0), '累计登记的待治理问题') +
      DZ.kpi('已确认归档', DZ.number(s.closed || 0), '整改核查确认完成', 'ok') +
      DZ.kpi('流转中', DZ.number(s.inFlight || 0), '尚未确认归档', 'warn') +
      DZ.kpi('待核查确认', DZ.number(bs.pending_confirm || 0), '等待管理部门核查');
  }

  /* ---------------- 问题清单页签 ---------------- */
  function renderListPane(){
    var box = q('#iss_listpane');
    if (!box) return;
    if (!S.data){ box.innerHTML = DZ.skeleton(5); return; }
    var list = filtered();

    box.innerHTML =
      DZ.guide('<b>安全治理闭环</b>：登记 → 定级 → 派单 → 接收 → 整改 → 回复 → 复检 → 会签 → 归档。' +
        '点选下方清单中的任一问题即可进入「处置详情」推进流转。') +
      '<div id="iss_kpis" class="dz-kpi-row is-compact"></div>' +
      '<div class="card">' +
        '<div class="dz-card-head">' +
          '<h3>问题清单（<span id="iss_list_count">' + list.length + '</span>）</h3>' +
          '<div class="dz-card-actions">' +
            '<span class="muted" id="iss_meta"></span>' +
            '<button id="iss_query" class="ghost" title="重新拉取治理问题数据" aria-label="查询">查询</button>' +
            '<button id="iss_new" title="手工创建待治理的问题" aria-label="新建待治理问题">新建待治理问题</button>' +
          '</div>' +
        '</div>' +
        '<div id="iss_form"></div>' +
        filterBar() +
        '<div id="iss_list"></div>' +
      '</div>';

    bindListPane();
    renderMeta();
    renderKpis();
    renderForm();
    renderList(list);
  }

  function bindListPane(){
    var qb = q('#iss_query');
    if (qb) qb.onclick = function(){ load(true); };
    var nb = q('#iss_new');
    if (nb) nb.onclick = function(){
      S.mode = (S.mode === 'create' ? 'none' : 'create');
      S.action = null;
      if (S.mode === 'create') setMsg('');
      renderForm();
    };
    bindFilters();
  }

  function filtered(){
    var all = (S.data && S.data.issues) || [];
    return all.filter(function(it){
      if (S.f.status && it.status !== S.f.status) return false;
      if (S.f.source && it.source !== S.f.source) return false;
      if (S.f.severity && it.severity !== S.f.severity) return false;
      return true;
    });
  }

  function filterBar(){
    var flow = (S.data && S.data.flow) || [];
    var sum = (S.data && S.data.summary) || {};
    var bs = sum.byStatus || {};
    // 状态分布直接并入下拉选项文案（「全部状态（6）」/「整改中（2）」），
    // 取代原先独立的一整行状态胶囊，减少一条横向元素、缩短页面篇幅。
    var stOpts = '<option value="">全部状态（' + DZ.number(sum.total || 0) + '）</option>' + flow.map(function(x){
      return '<option value="' + DZ.esc(x.status) + '"' + (S.f.status === x.status ? ' selected' : '') + '>' +
        DZ.esc(x.label) + '（' + DZ.number(bs[x.status] || 0) + '）</option>';
    }).join('');
    var srcOpts = '<option value="">全部来源</option>' + sources().map(function(s){
      return '<option value="' + DZ.esc(s) + '"' + (S.f.source === s ? ' selected' : '') + '>' + DZ.esc(s) + '</option>';
    }).join('');
    var sevOpts = '<option value="">全部严重程度</option>' + severities().map(function(s){
      return '<option value="' + DZ.esc(s.value) + '"' + (S.f.severity === s.value ? ' selected' : '') + '>' + DZ.esc(s.label) + '</option>';
    }).join('');
    var dirty = S.f.status || S.f.source || S.f.severity;
    return DZ.filterBar([
      { label: '状态', html: '<select id="iss_f_status" title="按状态筛选" aria-label="按状态筛选">' + stOpts + '</select>' },
      { label: '来源', html: '<select id="iss_f_source" title="按来源筛选" aria-label="按来源筛选">' + srcOpts + '</select>' },
      { label: '严重程度', html: '<select id="iss_f_sev" title="按严重程度筛选" aria-label="按严重程度筛选">' + sevOpts + '</select>' }
    ], {
      aria: '问题清单筛选',
      end: '<span class="dz-filterbar-note">共 ' + filtered().length + ' 条</span>' +
        (dirty ? '<button class="ghost" id="iss_f_reset" title="清除全部筛选条件" aria-label="重置筛选">重置</button>' : '')
    });
  }

  function bindFilters(){
    var a = q('#iss_f_status');
    if (a) a.onchange = function(){ S.f.status = a.value; renderList(filtered()); refreshFilterBar(); };
    var b = q('#iss_f_source');
    if (b) b.onchange = function(){ S.f.source = b.value; renderList(filtered()); refreshFilterBar(); };
    var c = q('#iss_f_sev');
    if (c) c.onchange = function(){ S.f.severity = c.value; renderList(filtered()); refreshFilterBar(); };
    var r = q('#iss_f_reset');
    if (r) r.onclick = function(){
      S.f.status = ''; S.f.source = ''; S.f.severity = '';
      renderList(filtered()); refreshFilterBar();
    };
  }

  // 筛选条件变化后原地重刷筛选行（保持焦点不跳屏，避免整页重绘）
  function refreshFilterBar(){
    var card = q('#iss_listpane') && q('#iss_listpane').querySelector('.card');
    if (!card) return;
    var bar = card.querySelector('.dz-filterbar');
    if (!bar) return;
    var tmp = document.createElement('div');
    tmp.innerHTML = filterBar();
    bar.parentNode.replaceChild(tmp.firstChild, bar);
    bindFilters();
  }

  function renderList(list){
    var box = q('#iss_list');
    if (!box) return;
    var cnt = q('#iss_list_count');
    if (cnt) cnt.textContent = list.length;
    if (!list.length){
      box.innerHTML = DZ.empty('当前筛选条件下暂无治理问题');
      return;
    }
    if (!S.sel || !list.some(function(x){ return x.issueId === S.sel; })) S.sel = list[0].issueId;
    box.innerHTML = '<div class="pick-list" style="grid-template-columns:1fr">' +
      list.map(itemHtml).join('') + '</div>';
    each('#iss_list .pick', function(el){
      var open = function(){ selectIssue(el.getAttribute('data-id')); };
      el.onclick = open;
      el.onkeydown = function(e){ if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); open(); } };
    });
  }

  function itemHtml(it){
    var on = it.issueId === S.sel;
    var style = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
    return '<div class="pick" data-id="' + DZ.esc(it.issueId) + '" role="button" tabindex="0"' + style +
      ' aria-label="查看问题 ' + DZ.esc(it.title) + '" title="查看问题详情">' +
      '<div style="min-width:0;flex:1">' +
        '<div class="pick-name" style="font-weight:600">' + DZ.esc(it.issueNo) + ' ' + DZ.esc(it.title) + '</div>' +
        '<div class="row" style="gap:6px;margin-top:6px">' + statusBadge(it) +
          '<span class="muted">' + DZ.esc(it.deptName || '未指定部门') + '</span>' +
          slaText(it) +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // 清单点选 → 自动切到「处置详情」页签
  function selectIssue(id){
    S.sel = id;
    if (!S.detail || S.detail.issueId !== id){ S.detail = null; }
    S.mode = 'none'; S.action = null;
    switchTab('detail');
  }

  /* ---------------- 处置详情 / 复检反馈 页签（共享选中项） ---------------- */
  function backBar(){
    return '<div class="dz-actions" style="justify-content:flex-start;margin-bottom:10px">' +
      '<button class="ghost" id="iss_back_list" title="返回问题清单" aria-label="返回问题清单">返回问题清单</button>' +
    '</div>';
  }

  function loadDetailInto(sel, buildHtml){
    var main = q(sel);
    if (!main) return;
    if (!S.sel){
      main.innerHTML = DZ.empty('请先在「问题清单」中选择一个问题查看处置详情');
      return;
    }
    if (S.detail && S.detail.issueId === S.sel){
      main.innerHTML = buildHtml(S.detail);
      afterDetailRender(sel);
      return;
    }
    var id = S.sel;
    main.innerHTML = DZ.skeleton(4);
    DZ.get(API.detail(id)).then(function(r){
      if (S.sel !== id) return;   // 已切换选中项，丢弃本次结果
      if (!r || r.error){
        main.innerHTML = DZ.banner('bad', '问题详情加载失败：' + errMsg(r), function(){ S.detail = null; renderPane(); });
        return;
      }
      S.detail = r;
      main.innerHTML = buildHtml(r);
      afterDetailRender(sel);
    });
  }

  function afterDetailRender(sel){
    each(sel + ' [data-act]', function(b){
      b.onclick = function(){ openAction(b.getAttribute('data-act')); };
    });
    var back = q('#iss_back_list');
    if (back) back.onclick = function(){ switchTab('list'); };
    renderActionForm();
  }

  function actButtons(acts, emptyHint){
    return acts.length ? acts.map(function(a){
      var nm = actionName(a);
      return '<button data-act="' + DZ.esc(a) + '" title="' + DZ.esc(nm) + '" aria-label="' + DZ.esc(nm) + '">' +
        DZ.esc(nm) + '</button>';
    }).join(' ') : '<span class="muted">' + emptyHint + '</span>';
  }

  // 处置详情：状态流转 / 流转记录 / 证据与工作证明 / 可执行动作（处置类）
  function detailBodyHtml(it){
    // 状态机流转条
    var flow = (S.data && S.data.flow) || [];
    var cur = -1;
    for (var i=0;i<flow.length;i++){ if (flow[i].status === it.status){ cur = i; break; } }
    var steps = flow.map(function(x, idx){
      var cls = idx < cur ? 'done' : (idx === cur ? 'on' : '');
      return '<li class="dz-step ' + cls + '"><span class="dz-step-no">' + (idx + 1) + '</span>' +
        '<span>' + DZ.esc(x.label) + '</span></li>';
    }).join('');

    // 流转记录
    var trans = it.transitions || [];
    var tlHtml = trans.length ? trans.map(function(t){
      var title = t.actionName || ACT_NAME[t.action] || '流转';
      return '<li class="dz-tl-item">' +
        '<div class="dz-tl-title">' + DZ.esc(title) +
          (t.toLabel ? ' <span class="muted">→ ' + DZ.esc(t.toLabel) + '</span>' : '') + '</div>' +
        '<div class="dz-tl-time">' + DZ.esc(DZ.date(t.createdAt)) + ' · ' + DZ.esc(t.actorName || t.actor || '—') + '</div>' +
        (t.comment ? '<div class="muted">' + DZ.esc(t.comment) + '</div>' : '') +
      '</li>';
    }).join('') : '<li class="dz-tl-item"><div class="dz-tl-time">暂无流转记录</div></li>';

    // 证据与工作证明
    var ev = it.evidence || [];
    var evHtml = ev.length ? ev.map(function(e){
      return '<div class="dz-file">' +
        '<div class="dz-file-name" title="' + DZ.esc(e.fileName) + '">' + DZ.esc(e.fileName) + '</div>' +
        '<div class="dz-file-meta">' + DZ.pill(e.step || '材料') + ' ' +
          DZ.esc(e.uploadedByName || e.uploadedBy || '—') + ' · ' + DZ.esc(DZ.date(e.uploadedAt)) + '</div>' +
      '</div>' +
      (e.note ? '<div class="muted" style="margin:4px 0 10px 4px">说明：' + DZ.esc(e.note) + '</div>'
              : '<div style="height:8px"></div>');
    }).join('') : '<div class="muted">暂无佐证材料</div>';

    // 可执行动作（处置类：不含复检反馈相关动作）
    var acts = (it.allowedActions || []).filter(function(a){ return !RECHECK_CODES[a]; });
    var actBtns = actButtons(acts, it.status === 'closed'
      ? '该问题已确认归档，流程已结束'
      : '当前无可执行的处置动作，请前往「复检反馈」页签');

    return '' +
      backBar() +
      '<div class="card">' +
        '<h3>' + DZ.esc(it.issueNo) + ' ' + DZ.esc(it.title) + ' ' + statusBadge(it) + '</h3>' +
        metricText('问题来源', it.source) +
        metricText('问题类别', it.category) +
        metricText('严重程度', it.severityLabel) +
        metricText('责任部门', it.deptName || '未指定') +
        metricText('责任岗位', it.positionName || '未指定') +
        metricKV('整改期限', slaText(it)) +
        metricText('整改计划', it.plan) +
      '</div>' +
      '<div class="card">' +
        '<h3>状态流转</h3>' +
        '<ul class="dz-steps">' + steps + '</ul>' +
      '</div>' +
      '<div class="card">' +
        '<h3>流转记录</h3>' +
        '<ul class="dz-tl">' + tlHtml + '</ul>' +
      '</div>' +
      '<div class="card">' +
        '<h3>证据与工作证明</h3>' +
        evHtml +
      '</div>' +
      '<div class="card">' +
        '<h3>可执行动作</h3>' +
        '<div class="dz-actions" style="justify-content:flex-start">' + actBtns + '</div>' +
        '<div id="iss_action_msg"></div>' +
        '<div id="iss_action_form"></div>' +
      '</div>';
  }

  // 复检反馈：复检结论 + 复检/核查/归档类动作
  function recheckBodyHtml(it){
    var acts = (it.allowedActions || []).filter(function(a){ return RECHECK_CODES[a]; });
    var actBtns = actButtons(acts, it.status === 'closed'
      ? '该问题已确认归档，流程已结束'
      : '当前状态无可执行的复检反馈动作');

    return '' +
      backBar() +
      '<div class="card">' +
        '<h3>' + DZ.esc(it.issueNo) + ' ' + DZ.esc(it.title) + ' ' + statusBadge(it) + '</h3>' +
        metricText('问题来源', it.source) +
        metricText('严重程度', it.severityLabel) +
        metricText('责任部门', it.deptName || '未指定') +
        metricText('责任岗位', it.positionName || '未指定') +
        metricKV('整改期限', slaText(it)) +
        metricText('复检结论', it.recheckResult) +
      '</div>' +
      '<div class="card">' +
        '<h3>复检反馈</h3>' +
        '<div class="muted" style="margin-bottom:8px">提交复检反馈，并进行人工核查确认与归档（含退回重办分支）。</div>' +
        '<div class="dz-actions" style="justify-content:flex-start">' + actBtns + '</div>' +
        '<div id="iss_action_msg"></div>' +
        '<div id="iss_action_form"></div>' +
      '</div>';
  }

  /* ---------------- 动作表单 ---------------- */
  function openAction(a){
    S.mode = 'action';
    S.action = a;
    setActMsg('');
    renderActionForm();
    var box = q('#iss_action_form');
    if (box && box.scrollIntoView) box.scrollIntoView({ block: 'nearest' });
  }

  function renderActionForm(){
    var box = q('#iss_action_form');
    if (!box) return;
    if (S.mode !== 'action' || !S.action || !S.detail){ box.innerHTML = ''; return; }
    var a = S.action, it = S.detail, nm = actionName(a);
    var body = '';

    if (a === 'triage'){
      body = '<div class="grid2">' +
        '<div><label for="af_sev">严重程度</label><select id="af_sev">' + sevOptions(it.severity) + '</select></div>' +
        '<div><label for="af_cat">问题类别</label><select id="af_cat">' + optList(categories(), it.category) + '</select></div>' +
      '</div>';
    } else if (a === 'dispatch'){
      body = '<div class="grid2">' +
        '<div><label for="af_dept">责任部门（必填）</label><select id="af_dept">' + deptOptions(it.deptId) + '</select></div>' +
        '<div><label for="af_pos">责任岗位（必填）</label><select id="af_pos">' + posOptions(it.deptId, it.positionId) + '</select></div>' +
        '<div><label for="af_due">整改期限（必填）</label><input id="af_due" type="date" value="' + DZ.esc(it.dueDate || '') + '"></div>' +
      '</div>' +
      '<label for="af_plan">整改计划</label>' +
      '<input id="af_plan" maxlength="120" placeholder="整改计划（可选）" value="' + DZ.esc(it.plan || '') + '">';
    } else if (a === 'respond' || a === 'recheck'){
      body = '<label for="af_file">工作佐证材料名称（必填）</label>' +
        '<input id="af_file" maxlength="120" placeholder="如：整改回复单、复检记录、审批流转留痕">' +
        '<label for="af_note">佐证说明</label>' +
        '<input id="af_note" maxlength="120" placeholder="佐证说明（可选）">';
    } else if (a === 'close'){
      body = '<label for="af_result">复检结论（必填）</label>' +
        '<input id="af_result" maxlength="120" placeholder="如：已复检，判定通过" value="' + DZ.esc(it.recheckResult || '') + '">';
    }

    var commentLabel = (a === 'reject') ? '退回原因' : '办理意见';
    box.innerHTML = '<div class="dz-cite">' +
      '<div class="dz-tl-title" style="margin-bottom:8px">' + DZ.esc(nm) + '</div>' +
      body +
      '<label for="af_comment">' + DZ.esc(commentLabel) + '（可选）</label>' +
      '<input id="af_comment" maxlength="120" placeholder="' + DZ.esc(commentLabel) + '（可选）">' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
        '<button id="af_submit">' + DZ.esc(nm) + '</button>' +
        '<button class="ghost" id="af_cancel">取消</button>' +
      '</div>' +
    '</div>';

    if (a === 'dispatch'){
      var d = q('#af_dept'), ps = q('#af_pos');
      if (d && ps) d.onchange = function(){ ps.innerHTML = posOptions(d.value, ''); };
    }
    var sub = q('#af_submit');
    if (sub) sub.onclick = submitAction;
    var can = q('#af_cancel');
    if (can) can.onclick = function(){ S.mode = 'none'; S.action = null; renderActionForm(); };
  }

  async function submitAction(){
    if (S.busy) return;
    var a = S.action, nm = actionName(a);
    var body = { action: a, comment: val('#af_comment') };

    if (a === 'triage'){
      body.severity = val('#af_sev');
      body.category = val('#af_cat');
    } else if (a === 'dispatch'){
      body.deptId = val('#af_dept');
      body.positionId = val('#af_pos');
      body.dueDate = val('#af_due');
      body.plan = val('#af_plan');
      if (!body.deptId){ DZ.toast('请选择责任部门', 'bad'); return; }
      if (!body.positionId){ DZ.toast('请选择责任岗位', 'bad'); return; }
      if (!body.dueDate){ DZ.toast('请填写整改期限', 'bad'); return; }
    } else if (a === 'respond' || a === 'recheck'){
      body.fileName = val('#af_file');
      body.note = val('#af_note');
      if (!body.fileName){ DZ.toast('请填写工作佐证材料名称', 'bad'); return; }
    } else if (a === 'close'){
      body.recheckResult = val('#af_result');
      if (!body.recheckResult){ DZ.toast('请填写复检结论', 'bad'); return; }
    }

    var btn = q('#af_submit');
    S.busy = true;
    busyBtn(btn);
    setActMsg('');

    var r = await DZ.post(API.transition(S.sel), body);
    S.busy = false;

    if (!r || r.error){
      restoreBtn(btn, nm);
      var code = r && r.error && r.error.code;
      if (code === 'FORBIDDEN'){
        var fm = (r.error && r.error.message) || ('当前账号无权执行「' + nm + '」，该环节应由对应岗位办理');
        setActMsg(DZ.banner('bad', fm));
        DZ.toast('无权执行「' + nm + '」：该环节应由对应岗位办理', 'bad');
      } else {
        var m = '流转失败：' + errMsg(r);
        setActMsg(DZ.banner('bad', m));
        DZ.toast(m, 'bad');
      }
      return;
    }

    S.mode = 'none'; S.action = null;
    DZ.toast(nm + '完成，状态更新为「' + (r.statusLabel || '') + '」', 'ok');
    S.detail = null;
    await load(true);
  }

  /* ---------------- 新建待治理问题 ---------------- */
  function renderForm(){
    var box = q('#iss_form');
    if (!box) return;
    if (S.mode !== 'create'){ box.innerHTML = ''; return; }

    box.innerHTML = '<div class="card">' +
      '<h3>新建待治理问题</h3>' +
      '<div class="grid2">' +
        '<div><label for="cf_title">问题标题（必填）</label>' +
          '<input id="cf_title" maxlength="80" placeholder="简述发现的问题"></div>' +
        '<div><label for="cf_source">问题来源</label>' +
          '<select id="cf_source">' + optList(sources(), '自查发现') + '</select></div>' +
        '<div><label for="cf_cat">问题类别</label>' +
          '<select id="cf_cat">' + optList(categories(), '治理层') + '</select></div>' +
        '<div><label for="cf_sev">严重程度</label>' +
          '<select id="cf_sev">' + sevOptions('medium') + '</select></div>' +
        '<div><label for="cf_dept">责任部门</label>' +
          '<select id="cf_dept">' + deptOptions('', '暂不指定') + '</select></div>' +
        '<div><label for="cf_pos">责任岗位</label>' +
          '<select id="cf_pos"><option value="">暂不指定</option></select></div>' +
        '<div><label for="cf_due">整改期限</label><input id="cf_due" type="date"></div>' +
      '</div>' +
      '<label for="cf_plan">整改计划</label>' +
        '<input id="cf_plan" maxlength="120" placeholder="整改计划（可选）">' +
      '<label for="cf_note">备注</label>' +
        '<input id="cf_note" maxlength="120" placeholder="备注（可选）">' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
        '<button id="cf_submit">提交</button>' +
        '<button class="ghost" id="cf_cancel">取消</button>' +
      '</div>' +
    '</div>';

    var d = q('#cf_dept'), p = q('#cf_pos');
    if (d && p) d.onchange = function(){ p.innerHTML = posOptions(d.value, ''); };
    var sub = q('#cf_submit');
    if (sub) sub.onclick = submitCreate;
    var can = q('#cf_cancel');
    if (can) can.onclick = function(){ S.mode = 'none'; renderForm(); };
  }

  async function submitCreate(){
    if (S.busy) return;
    var title = val('#cf_title').trim();
    if (!title){ DZ.toast('请填写问题标题', 'bad'); return; }

    var body = {
      title: title,
      source: val('#cf_source') || '自查发现',
      category: val('#cf_cat') || '治理层',
      severity: val('#cf_sev') || 'medium',
      deptId: val('#cf_dept'),
      positionId: val('#cf_pos'),
      dueDate: val('#cf_due'),
      plan: val('#cf_plan'),
      note: val('#cf_note')
    };

    var btn = q('#cf_submit');
    S.busy = true;
    busyBtn(btn);
    setMsg('');

    var r = await DZ.post(API.create, body);
    S.busy = false;

    if (!r || r.error){
      restoreBtn(btn, '提交');
      var m = '新建失败：' + errMsg(r);
      setMsg(DZ.banner('bad', m));
      DZ.toast(m, 'bad');
      return;
    }

    S.mode = 'none';
    S.action = null;
    S.f.status = '';        // 复位状态筛选，确保新问题可见
    S.detail = null;
    S.sel = r.issueId || null;
    DZ.toast('待治理问题已创建（' + (r.issueNo || '') + '）', 'ok');
    await load(true);
  }

  /* ---------------- 注册视图装载函数 ---------------- */
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['issues'] = mount;
})();
