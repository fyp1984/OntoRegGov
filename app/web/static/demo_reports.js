/* ============================================================
   金融行业数据安全知识库和智能体平台 · 报告与看板（demo_reports.js）
   视图：id = rep，容器 #rep_root
   流程：先选自查任务 → 看完成情况与各部门完成比例 → 下钻检查项明细。
   数据来源（仅这三个接口，字段以后端真实返回为准）：
     GET /api/reports/tasks
     GET /api/reports/tasks/{taskId}/overview
     GET /api/reports/tasks/{taskId}/items
   导出：复用既有报告下载接口 /api/selfcheck/tasks/{taskId}/report/md
   依赖：demo_common.js 提供的全局 DZ 命名空间与既有 CSS 类，不引入图表库 / CDN。
   ============================================================ */
(function(){
  'use strict';

  const ROOT = '#rep_root';

  const API = {
    tasks: '/api/reports/tasks',
    overview: function(id){ return '/api/reports/tasks/' + encodeURIComponent(id) + '/overview'; },
    items: function(id, q){
      const url = '/api/reports/tasks/' + encodeURIComponent(id) + '/items';
      const p = [];
      if (q && q.lineCode) p.push('lineCode=' + encodeURIComponent(q.lineCode));
      if (q && q.status) p.push('status=' + encodeURIComponent(q.status));
      return p.length ? url + '?' + p.join('&') : url;
    },
    exportMd: function(id){ return '/api/selfcheck/tasks/' + encodeURIComponent(id) + '/report/md'; }
  };

  // 视图状态：跨重入常驻（当前步骤 / 选中任务 / 筛选与已取数）
  const S = {
    step: 1,          // 1 选任务 / 2 看板 / 3 明细
    tab: 'pick',      // 当前页签（pick / board / export），与 step 对应
    tasks: [],
    taskId: null,
    org: '', cycle: '',
    dept: '', status: '',
    overview: null,
    items: null
  };

  // 任务状态 → 徽章色（页面只展示后端 statusLabel，不暴露英文原文）
  const STATUS_KIND = { in_progress: 'warn', closed: 'ok', draft: 'unk', pending: 'warn', done: 'ok', open: 'warn' };
  // 适用性中文映射（不渲染英文值）
  const APPLY = { applicable: '适用', not_applicable: '不适用', na: '不适用', partial: '部分适用' };
  // 证据材料状态中文映射
  const EVID = { provided: '已提供', missing: '缺失', pending: '待补充' };
  // 判定着色（仅取现有 CSS 变量）
  const RESULT_COLOR = { pass: 'var(--ok)', partial: 'var(--warn)', fail: 'var(--bad)', supplement: 'var(--unk)' };
  const OPTS = [['', '全部'], ['pass', '符合'], ['partial', '部分符合'], ['fail', '不符合'], ['supplement', '需补充']];

  // 页签：与 S.step 一一对应（pick=选任务 / board=看板 / export=明细与导出）
  const TABS = [
    { key: 'pick', label: '选择任务' },
    { key: 'board', label: '任务看板' },
    { key: 'export', label: '明细与导出' }
  ];
  const TAB_STEP = { pick: 1, board: 2, export: 3 };
  const STEP_TAB = { 1: 'pick', 2: 'board', 3: 'export' };
  // 每个步骤的引导说明：按「选择任务 → 任务看板 → 明细与导出」的顺序推进
  const STEP_GUIDE = {
    1: '<b>选择任务</b>：选择一条自查任务，作为生成合规报告的对象。',
    2: '<b>任务看板</b>：查看该任务的判定分布、证据齐备率与整改情况。',
    3: '<b>明细与导出</b>：查看检查项明细，并按需导出合规报告。'
  };

  // ---------- 小工具 ----------
  function root(){ return document.querySelector(ROOT); }
  function errMsg(d){ return (d && d.error && d.error.message) || '接口请求失败'; }
  function clampPct(n){ let v = Number(n); if (!isFinite(v)) v = 0; return Math.max(0, Math.min(100, v)); }
  function pctKind(n){ const v = Number(n); if (!isFinite(v)) return ''; return v >= 80 ? 'ok' : (v >= 50 ? 'warn' : 'bad'); }
  function uniq(list){
    const seen = {}, out = [];
    list.forEach(function(x){ if (!seen[x]){ seen[x] = 1; out.push(x); } });
    return out;
  }

  // ---------- 骨架 / 挂载 ----------
  function shell(){
    return '<div id="rep_head"></div><div id="rep_tabs"></div>' +
      '<div id="rep_pane" class="dz-pane"><div id="rep_body"></div></div>';
  }
  function setBody(html){ DZ.render('#rep_body', html); }

  function mount(){
    const box = root();
    if (!box) return;
    if (!box.querySelector('#rep_body')) box.innerHTML = shell();
    bindRoot();
    if (S.step < 1 || S.step > 3) S.step = 1;
    if (!S.tasks.length) loadTasks();
    else render();
  }

  function render(){
    const head = document.getElementById('rep_head');
    if (head) head.innerHTML = toolbarHtml();
    renderTabs();
    const g = DZ.guide(STEP_GUIDE[S.step] || '');
    if (S.step === 1) setBody(g + step1Html());
    else if (S.step === 2) setBody(g + step2Html());
    else setBody(g + step3Html());
  }

  // ---------- 页签（选择任务 / 任务看板 / 明细与导出） ----------
  // 页签只承载呈现结构：切换时改变 S.step，内容仍渲染进 #rep_body 并按页签互斥。
  function renderTabs(){
    const key = STEP_TAB[S.step] || 'pick';
    S.tab = key;
    DZ.tabs('#rep_tabs', TABS, key, onTabClick);
  }
  function onTabClick(key){
    const step = TAB_STEP[key];
    if (!step || step === S.step) return;
    if (step === 1){ S.step = 1; render(); return; }
    if (!S.taskId){ S.step = 1; render(); DZ.toast('请先选择一条自查任务', 'warn'); return; }
    S.step = step;
    render();
    if (step === 2 && !S.overview) loadOverview();
    else if (step === 3 && !S.items) loadItems();
  }

  // ---------- 工具栏（文案统一：查询 / 返回任务列表 / 导出报告） ----------
  function toolbarHtml(){
    let h = '<div class="dz-toolbar">';
    h += '<button class="ghost" data-act="query" title="按当前筛选条件重新查询">查询</button>';
    if (S.step > 1) h += '<button class="ghost" data-act="back" title="返回任务列表重新选择">返回任务列表</button>';
    if (S.step === 3 && S.taskId) h += '<button class="ghost" data-act="export" title="导出自查报告">导出报告</button>';
    if (S.step > 1 && S.overview && S.overview.task){
      const t = S.overview.task;
      h += '<span class="muted" style="margin-left:auto">当前任务：' + DZ.esc(t.orgName || '—') +
        ' · ' + DZ.esc(t.cycle || '—') + (t.topic ? ' · ' + DZ.esc(t.topic) : '') + '</span>';
    }
    h += '</div>';
    return h;
  }

  // ---------- 事件绑定（仅绑容器，避免 document 级重复监听） ----------
  function bindRoot(){
    const box = root();
    if (!box || box.dataset.repBound === '1') return;
    box.dataset.repBound = '1';
    box.addEventListener('click', onRootClick);
    box.addEventListener('keydown', onRootKey);
  }
  function onRootKey(e){
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const el = e.target.closest && e.target.closest('[data-act]');
    if (!el) return;
    const tag = el.tagName;
    if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' || tag === 'SELECT') return;
    e.preventDefault();
    el.click();
  }
  function onRootClick(e){
    const el = e.target.closest && e.target.closest('[data-act]');
    if (!el) return;
    const act = el.getAttribute('data-act');
    if (act === 'query'){ onQuery(); return; }
    if (act === 'back'){ S.step = 1; S.dept = ''; S.status = ''; render(); return; }
    if (act === 'pick'){ pickTask(el.getAttribute('data-task')); return; }
    if (act === 'dept' || act === 'line'){ openLine(el.getAttribute('data-key') || ''); return; }
    if (act === 'status'){ setStatus(el.getAttribute('data-status') || ''); return; }
    if (act === 'org'){ S.org = el.getAttribute('data-org') || ''; render(); return; }
    if (act === 'cycle'){ S.cycle = el.getAttribute('data-cycle') || ''; render(); return; }
    if (act === 'export'){ exportReport(); return; }
    if (act === 'row'){ toggleRow(el); return; }
  }
  function onQuery(){
    if (S.step === 1) loadTasks();
    else if (S.step === 2) loadOverview();
    else loadItems();
  }

  // ---------- 取数 ----------
  async function loadTasks(){
    if (S.step !== 1){ S.step = 1; }
    render();
    setBody(DZ.skeleton(4));
    const d = await DZ.get(API.tasks);
    if (!d || d.error){ setBody(DZ.banner('bad', '任务清单加载失败：' + errMsg(d), loadTasks)); return; }
    S.tasks = Array.isArray(d.tasks) ? d.tasks : [];
    render();
  }

  async function loadOverview(){
    if (!S.taskId){ S.step = 1; render(); return; }
    render();
    setBody(DZ.skeleton(5));
    const d = await DZ.get(API.overview(S.taskId));
    if (!d || d.error){ setBody(DZ.banner('bad', '任务总览加载失败：' + errMsg(d), loadOverview)); return; }
    S.overview = d;
    render();
  }

  async function loadItems(){
    if (!S.taskId){ S.step = 1; render(); return; }
    render();
    setBody(DZ.skeleton(5));
    const d = await DZ.get(API.items(S.taskId, { lineCode: S.dept, status: S.status }));
    if (!d || d.error){ setBody(DZ.banner('bad', '检查项加载失败：' + errMsg(d), loadItems)); return; }
    S.items = Array.isArray(d.items) ? d.items : [];
    render();
  }

  // ---------- 交互动作 ----------
  function pickTask(taskId){
    if (!taskId) return;
    S.taskId = taskId; S.dept = ''; S.status = ''; S.overview = null;
    S.step = 2;
    render();
    loadOverview();
  }
  function openLine(key){
    S.dept = key || ''; S.status = ''; S.items = null;
    S.step = 3;
    render();
    loadItems();
  }
  function setStatus(st){
    S.status = st || ''; S.items = null;
    render();
    loadItems();
  }
  function exportReport(){
    if (!S.taskId) return;
    const a = document.createElement('a');
    a.href = API.exportMd(S.taskId);
    a.setAttribute('download', '自查报告-' + S.taskId + '.md');
    document.body.appendChild(a);
    a.click();
    a.parentNode.removeChild(a);
    DZ.toast('已开始导出报告', 'ok');
  }
  function toggleRow(tr){
    const code = tr.getAttribute('data-code') || '';
    const detail = root().querySelector('tr[data-detail="' + code + '"]');
    if (!detail) return;
    detail.hidden = !detail.hidden;
    const caret = tr.querySelector('[data-caret]');
    if (caret) caret.textContent = detail.hidden ? '▸' : '▾';
  }

  // ---------- 步骤一：任务选择 ----------
  function step1Html(){
    if (!S.tasks.length){
      return DZ.empty('暂无可查看的自查任务', '<button class="ghost" data-act="query">重新查询</button>');
    }
    const orgs = uniq(S.tasks.map(function(t){ return t.orgName; }).filter(Boolean));
    const cycles = uniq(S.tasks.map(function(t){ return t.cycle; }).filter(Boolean));
    // 组织 / 周期筛选合并为同一行，避免两行筛选条各占一行篇幅
    let chips = '';
    if (orgs.length > 1){
      chips += '<span class="muted" style="align-self:center">组织</span>' +
        orgChip('全部组织', !S.org, '') +
        orgs.map(function(o){ return orgChip(o, S.org === o, o); }).join('');
    }
    if (cycles.length > 1){
      chips += '<span class="muted" style="align-self:center;margin-left:12px">周期</span>' +
        cycleChip('全部周期', !S.cycle, '') +
        cycles.map(function(c){ return cycleChip(c, S.cycle === c, c); }).join('');
    }
    let html = chips ? '<div class="dz-chipbar">' + chips + '</div>' : '';
    const list = S.tasks.filter(function(t){
      return (!S.org || t.orgName === S.org) && (!S.cycle || t.cycle === S.cycle);
    });
    if (!list.length) return html + DZ.empty('当前筛选条件下暂无自查任务');
    return html + '<div class="grid2">' + list.map(taskCard).join('') + '</div>';
  }
  function orgChip(label, on, val){
    return '<button class="dz-chip' + (on ? ' on' : '') + '" data-act="org" data-org="' + DZ.esc(val) +
      '" title="按组织筛选">' + DZ.esc(label) + '</button>';
  }
  function cycleChip(label, on, val){
    return '<button class="dz-chip' + (on ? ' on' : '') + '" data-act="cycle" data-cycle="' + DZ.esc(val) +
      '" title="按周期筛选">' + DZ.esc(label) + '</button>';
  }
  function taskCard(t){
    const kind = STATUS_KIND[t.status] || '';
    let h = '<div class="card" data-act="pick" data-task="' + DZ.esc(t.taskId) + '" role="button" tabindex="0" style="cursor:pointer">';
    h += '<div class="row" style="justify-content:space-between">' +
      '<span class="dz-tag-soft">' + DZ.esc(t.cycle || '—') + '</span>' +
      DZ.badge(kind, t.statusLabel || '—') + '</div>';
    h += '<h3 style="margin:10px 0 4px">' + DZ.esc(t.orgName || '—') + '</h3>';
    h += '<div class="muted">' + DZ.esc(t.topic || '—') + (t.stage ? ' · ' + DZ.esc(t.stage) : '') + '</div>';
    h += '<div class="dz-metric"><span class="dz-metric-k">负责人</span><span class="dz-metric-v">' +
      DZ.esc(t.ownerName || t.owner || '—') + '</span></div>';
    h += '<div class="dz-metric"><span class="dz-metric-k">起止日期</span><span class="dz-metric-v">' +
      DZ.esc(t.startDate || '—') + ' ~ ' + DZ.esc(t.endDate || '—') + '</span></div>';
    h += '<div class="dz-metric"><span class="dz-metric-k">检查项</span><span class="dz-metric-v">' +
      DZ.number(t.itemCount) + ' 项</span></div>';
    h += '<div class="dz-metric"><span class="dz-metric-k">完成度</span><span class="dz-metric-v">' +
      DZ.number(clampPct(t.progress)) + '%</span></div>';
    h += DZ.bar(clampPct(t.progress));
    h += '<div class="row" style="margin-top:10px">' +
      DZ.resultBadge(t.verdict && t.verdict.result) + DZ.severityBadge(t.riskLevel) +
      '<span class="muted">点击查看完成情况</span></div>';
    h += '</div>';
    return h;
  }

  // ---------- 步骤二：任务总览看板 ----------
  function step2Html(){
    if (!S.overview) return DZ.skeleton(5);
    return kpiRow(S.overview) +
      '<div class="grid2">' +
        '<div class="card"><h3>自查结论</h3>' + conclusion(S.overview) + '</div>' +
        '<div class="card"><h3>判定构成</h3>' + statusChart(S.overview) + '</div>' +
      '</div>' +
      '<div class="card"><h3>各部门完成比例</h3>' + deptChart(S.overview) + '</div>';
  }
  function kpiRow(o){
    const c = o.counts || {}, t = o.task || {};
    const evReq = Number(c.evidenceRequired) || 0, evPro = Number(c.evidenceProvided) || 0;
    const evPct = evReq ? Math.round(evPro / evReq * 100) : 0;
    const row = [
      DZ.kpi('检查项总数', DZ.number(c.total), '本任务全部检查项', ''),
      DZ.kpi('完成度', DZ.number(clampPct(t.progress)) + '%', '任务整体完成进度', pctKind(t.progress)),
      DZ.kpi('符合', DZ.number(c.pass), '判定为符合', 'ok'),
      DZ.kpi('部分符合', DZ.number(c.partial), '判定为部分符合', 'warn'),
      DZ.kpi('不符合', DZ.number(c.fail), '判定为不符合', 'bad'),
      DZ.kpi('需补充', DZ.number(c.supplement), '判定为需补充', ''),
      DZ.kpi('证据齐备率', evPct + '%', '已提供 ' + DZ.number(evPro) + ' / ' + DZ.number(evReq), pctKind(evPct))
    ].join('');
    return '<div class="dz-kpi-row is-compact">' + row + '</div>';
  }
  function conclusion(o){
    const v = o.verdict || {};
    const basis = v.basis || {};
    return '<div class="dz-metric"><span class="dz-metric-k">判定结论</span><span class="dz-metric-v">' +
        DZ.resultBadge(v.result) + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">得分</span><span class="dz-metric-v">' +
        DZ.number(v.score, 1) + ' 分</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">风险等级</span><span class="dz-metric-v">' +
        DZ.severityBadge(v.riskLevel) + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">检查项总数</span><span class="dz-metric-v">' +
        DZ.number(basis.total) + ' 项</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">数据时间</span><span class="dz-metric-v">' +
        DZ.esc(DZ.date(o.computedAt)) + '</span></div>';
  }
  function statusChart(o){
    const cmap = {};
    (o.byStatus || []).forEach(function(x){ cmap[x.status] = Number(x.count) || 0; });
    const total = Number((o.counts || {}).total) || 0;
    let any = false;
    const rows = ['pass', 'partial', 'fail', 'supplement'].map(function(k){
      const n = cmap[k] || 0;
      if (n) any = true;
      const pct = total ? Math.round(n / total * 100) : 0;
      return '<div style="margin-bottom:10px">' +
        '<div class="dz-metric"><span class="dz-metric-k">' + DZ.resultBadge(k) + '</span>' +
        '<span class="dz-metric-v">' + DZ.number(n) + ' 项 · ' + pct + '%</span></div>' +
        '<div class="dz-bar"><i style="width:' + pct + '%;background:' + (RESULT_COLOR[k] || 'var(--unk)') + '"></i></div>' +
      '</div>';
    }).join('');
    return any ? rows : DZ.empty('暂无判定分布数据');
  }
  function deptChart(o){
    const list = Array.isArray(o.byDept) ? o.byDept : [];
    if (!list.length) return DZ.empty('暂无部门完成数据');
    return list.map(function(d){
      const pct = clampPct(d.progress);
      return '<div data-act="dept" data-key="' + DZ.esc(d.key) + '" role="button" tabindex="0" ' +
          'style="cursor:pointer;padding:10px 0;border-bottom:1px solid var(--line)" title="点击查看该部门检查项">' +
        '<div class="row" style="justify-content:space-between">' +
          '<span style="font-weight:600;color:var(--brand-deep)">' + DZ.esc(d.label || '—') + '</span>' +
          '<span class="muted">已完成 ' + DZ.number(d.done) + ' / ' + DZ.number(d.total) + '</span>' +
        '</div>' +
        '<div class="row" style="gap:10px;margin:6px 0">' +
          '<div style="flex:1;min-width:80px">' + DZ.bar(pct) + '</div>' +
          '<span class="muted" style="min-width:44px;text-align:right">' + DZ.number(pct) + '%</span>' +
        '</div>' +
        '<div class="row" style="gap:10px">' + distBadges(d) + DZ.severityBadge(d.riskLevel) + '</div>' +
      '</div>';
    }).join('');
  }
  function distBadges(d){
    const parts = [];
    [['pass', d.pass], ['partial', d.partial], ['fail', d.fail], ['supplement', d.supplement]].forEach(function(x){
      if (x[1]) parts.push('<span>' + DZ.resultBadge(x[0]) + ' ' + DZ.number(x[1]) + '</span>');
    });
    return parts.join('　');
  }

  // ---------- 步骤三：检查项明细 ----------
  function step3Html(){
    if (!S.items) return DZ.skeleton(5);
    const o = S.overview || {};
    const depts = Array.isArray(o.byDept) ? o.byDept : [];
    // 条线 / 判定筛选合并为同一行，避免两行筛选条各占一行篇幅
    let chips = '<span class="muted" style="align-self:center">条线</span>' +
      lineChip('全部', !S.dept, '') +
      depts.map(function(d){ return lineChip(d.label || d.key, S.dept === d.key, d.key); }).join('') +
      '<span class="muted" style="align-self:center;margin-left:12px">判定</span>' +
      OPTS.map(function(x){
        return '<button class="dz-chip' + (S.status === x[0] ? ' on' : '') + '" data-act="status" data-status="' +
          x[0] + '" title="按判定筛选">' + x[1] + '</button>';
      }).join('');
    let html = '<div class="dz-chipbar">' + chips + '</div>';
    if (!S.items.length) return html + DZ.empty('当前筛选条件下暂无检查项');
    const labelOf = deptLabelMap();
    const rows = S.items.map(function(it){ return itemRow(it, labelOf[it.lineCode]); }).join('');
    return html + '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>检查项编号</th><th>标题</th><th>条线</th><th>适用性</th><th>判定</th><th>责任人</th>' +
      '<th>证据</th><th>实际值</th><th>说明</th><th>更新时间</th><th>明细</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  }
  function lineChip(label, on, val){
    return '<button class="dz-chip' + (on ? ' on' : '') + '" data-act="line" data-key="' + DZ.esc(val) +
      '" title="按条线筛选">' + DZ.esc(label) + '</button>';
  }
  function deptLabelMap(){
    const o = S.overview || {}, m = {};
    (o.byDept || []).forEach(function(d){ if (m[d.key] == null) m[d.key] = d.label; });
    (o.sections || []).forEach(function(s){ if (m[s.lineCode] == null) m[s.lineCode] = s.lineLabel; });
    return m;
  }
  function itemRow(it, lineLabel){
    const ev = Array.isArray(it.evidence) ? it.evidence : [];
    const code = it.checkCode || '';
    let h = '<tr data-act="row" data-code="' + DZ.esc(code) + '" role="button" tabindex="0" style="cursor:pointer">';
    h += '<td><span class="dz-tag-soft">' + DZ.esc(code || '—') + '</span></td>';
    h += '<td>' + DZ.esc(it.title || '—') + '</td>';
    h += '<td>' + DZ.esc(lineLabel || '—') + '</td>';
    h += '<td>' + DZ.esc(APPLY[it.applicability] || '—') + '</td>';
    h += '<td>' + DZ.resultBadge(it.status) + '</td>';
    h += '<td>' + DZ.esc(it.ownerName || it.owner || '—') + '</td>';
    h += '<td>' + (ev.length ? ev.map(function(e){ return DZ.esc(e.name || '—'); }).join('、')
                             : '<span class="muted">证据缺失</span>') + '</td>';
    h += '<td>' + DZ.esc(it.actualValue || '—') + '</td>';
    h += '<td>' + DZ.esc(it.note || '—') + '</td>';
    h += '<td>' + DZ.esc(DZ.date(it.updatedAt)) + '</td>';
    h += '<td data-caret="1">▸</td>';
    h += '</tr>';
    const evLine = ev.length
      ? ev.map(function(e){ return DZ.esc(e.name || '—') + ' ' + DZ.badge('ok', EVID[e.status] || '已提供'); }).join('　')
      : '<span class="muted">证据缺失</span>';
    h += '<tr data-detail="' + DZ.esc(code) + '" hidden><td colspan="11">' +
      '<div class="dz-metric"><span class="dz-metric-k">证据清单</span><span class="dz-metric-v">' + evLine + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">备注</span><span class="dz-metric-v">' + DZ.esc(it.note || '无') + '</span></div>' +
    '</td></tr>';
    return h;
  }

  // ---------- 注册视图 ----------
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['rep'] = function(){ mount(); };
})();
