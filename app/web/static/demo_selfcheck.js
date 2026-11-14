/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   视图：合规自查（id=dsc，容器 #dsc_root）
   信息架构（按任务里程碑排序，一个页签只做一件事）：
     ① 行业档案        —— 新建行业档案 + 现有档案与行业化自查清单
     ② 新建自查任务    —— 任务创建表单
     ③ 执行自查        —— 进行中任务台账；下钻进入执行工作台
                          （检查项明细 / 责任分配 / 证据与签署 / 任务级判定）
     ④ 复查复检        —— 问题登记 / 整改任务 / 发起复检 / 复检前后差异比对
     ⑤ 历史审计        —— 已闭环任务的历史结论与报告导出（只读审计追溯）
   能力保留：行业档案与清单 / 任务创建 / 任务明细与检查项 / AI 佐证匹配 /
            任务级判定 / 责任分配 / 证据与签署 / 问题-整改-复检链路 / 报告导出；
            原「合规自查 · 智能体检查」入口收敛为执行自查内的「智能预检」动作
            （复用既有页面与后端服务，不删除）。
   约定：仅使用 window.DZ.* 与既有 dz- 前缀样式；不引入任何外部库。
   ============================================================ */
(function(){
  'use strict';

  // ---------- 接口清单（唯一权威，勿臆造） ----------
  const API = {
    session:     '/api/auth/session',
    users:       '/api/admin/users',
    roles:       '/api/admin/roles',
    industries:  '/api/selfcheck/industries',
    templates:   function(industry, line){
      return '/api/selfcheck/templates?industry=' + encodeURIComponent(industry) +
             '&line=' + encodeURIComponent(line || '');
    },
    tasks:        '/api/selfcheck/tasks',
    task:         function(id){ return '/api/selfcheck/tasks/' + encodeURIComponent(id); },
    items:        function(id){ return API.task(id) + '/items'; },
    aiMatch:      function(id, code){ return API.task(id) + '/items/' + encodeURIComponent(code) + '/ai-match'; },
    verdict:      function(id){ return API.task(id) + '/verdict'; },
    assignments:  function(id){ return API.task(id) + '/assignments'; },
    assignPreview:  function(id){ return API.task(id) + '/assignments/preview'; },
    assignDispatch: function(id){ return API.task(id) + '/assignments/dispatch'; },
    assignOverride: function(id, code){ return API.task(id) + '/assignments/' + encodeURIComponent(code); },
    evidence:     function(id){ return API.task(id) + '/evidence'; },
    signoff:      function(id){ return API.task(id) + '/signoff'; },
    // 复查复检 / 报告 / 进度（复用既有后端服务，端点不做改动）
    findings:       function(id){ return API.task(id) + '/findings'; },
    remediations:   function(id){ return API.task(id) + '/remediations'; },
    remediation:    function(rid){ return '/api/selfcheck/remediations/' + encodeURIComponent(rid); },
    recheck:        function(id){ return API.task(id) + '/recheck'; },
    recheckDiff:    function(id){ return API.task(id) + '/recheck/diff'; },
    report:         function(id){ return API.task(id) + '/report'; },
    reportMd:       function(id){ return API.task(id) + '/report/md'; },
    progress:       '/api/selfcheck/progress',
    orgPositions: '/api/admin/org-positions',
    orgNodes:     '/api/admin/org-nodes'
  };

  // ---------- 顶层 Tab（按工作任务流程排序） ----------
  const TABS = [
    { key:'profile', label:'行业档案' },
    { key:'create',  label:'新建自查任务' },
    { key:'run',     label:'执行自查' },
    { key:'recheck', label:'复查复检' },
    { key:'history', label:'历史审计' }
  ];
  // 执行工作台子页签（录入 → 分配 → 举证 → 判定）
  const SUB_TABS = [
    { key:'items',    label:'检查项明细' },
    { key:'assign',   label:'责任分配' },
    { key:'evidence', label:'证据与签署' },
    { key:'verdict',  label:'任务级判定' }
  ];

  // ---------- 常量（字段以后端真实返回为准） ----------
  const APPLICABILITY = [
    { v:'applicable', t:'适用' },
    { v:'not_applicable', t:'不适用' },
    { v:'conditional', t:'条件适用' }
  ];
  const SIXDIM = [
    ['elements', '要素'], ['metrics', '度量'], ['evidence', '证据'],
    ['method', '方法'], ['interview', '访谈'], ['related', '关联']
  ];
  const DOC_LABEL = {
    jg24:'金规〔2024〕24号', jg93:'金办发〔2025〕93号',
    pboc3:'人行令〔2025〕第3号', jf8:'金发〔2026〕8号',
    jf26:'金发〔2026〕26号', pboc8:'人行令〔2026〕第8号'
  };
  // 检查项所属领域（后端枚举 → 中文）
  const DOMAIN_LABEL = { gov:'治理域', tech:'科技域', cross:'跨域' };
  // 行业编码（后端枚举 → 中文）
  const INDUSTRY_LABEL = { bank:'银行', insurance:'保险' };
  // 业务条线编码（后端枚举 → 中文，用于清单/明细中条线名的兜底展示）
  const LINE_LABEL = {
    acct:'账户与支付', credit:'信贷', creditref:'征信', wealth:'理财',
    interbank:'同业', openbank:'开放银行',
    underwrite:'投保', uwreview:'核保', claim:'理赔', preserve:'保全',
    actuary:'精算', reinsure:'再保', agent:'中介'
  };
  // 问题严重度 / 问题状态 / 整改状态（后端枚举 → 中文）
  const SEVERITY = [['high','高'],['medium','中'],['low','低']];
  const FINDING_STATUS = [['open','待处理'],['assigned','已分派'],['remediating','整改中'],
                          ['recheck','待复检'],['passed','已通过'],['closed','已关闭']];
  const FINDING_TONE = { open:'bad', assigned:'warn', remediating:'warn',
                         recheck:'warn', passed:'ok', closed:'ok' };
  const REM_STATUS = [['open','待处理'],['assigned','已分派'],['in_progress','整改中'],['done','已完成']];

  // ---------- 模块状态（视图可重入，状态常驻） ----------
  const S = {
    session:null,
    accounts:[],
    roles:{},
    industries:[],
    selIndustry:'bank',
    selLine:'',
    templatesEnv:null,
    templatesKey:'',
    tasks:[],
    scopeCache:{},        // taskId -> 条线编码数组（条线筛选时按需拉取）
    filterIndustry:'',
    filterCycle:'',
    filterLine:'',
    keyword:'',
    // 执行自查（run）状态
    selTaskId:null,
    detail:null,
    detailError:'',
    items:[],
    verdict:null,
    assignments:null,
    assignPreview:null,
    evidence:[],
    signoff:null,
    positions:null,
    nodes:null,
    // 复查复检（recheck）状态
    reTaskId:null,
    reFindings:null,
    reItems:[],
    reDiff:null,
    reDiffError:'',
    reError:'',
    reForm:null,
    // 历史审计（history）状态
    histTaskId:null,
    histReport:null,
    histError:'',
    // 全局进度看板
    progress:null,
    // 顶层页签
    tab:'run',
    sub:'items',
    createdTaskId:null
  };

  // ---------- 小工具 ----------
  const attr = s => DZ.esc(s);
  const rootEl = () => document.getElementById('dsc_root');
  const $ = id => document.getElementById(String(id).replace(/^#/, ''));

  function appText(v){
    const m = APPLICABILITY.filter(x => x.v === v)[0];
    return m ? m.t : (v || '—');
  }
  function appOptions(cur){
    return APPLICABILITY.map(a => '<option value="'+a.v+'"'+(a.v===cur?' selected':'')+'>'+a.t+'</option>').join('');
  }
  function evList(ev){
    if (Array.isArray(ev)) return ev.map(x => (x && typeof x === 'object') ? (x.name || x.fileName || '') : String(x)).filter(Boolean);
    if (typeof ev === 'string' && ev) return [ev];
    return [];
  }
  function evText(ev){ return evList(ev).join('\n'); }
  function sizeText(n){
    const v = Number(n);
    if (!isFinite(v) || v <= 0) return '—';
    if (v < 1024) return v + ' B';
    if (v < 1024*1024) return (v/1024).toFixed(1) + ' KB';
    return (v/1024/1024).toFixed(2) + ' MB';
  }
  function lineLabelOf(code){
    if (S.detail && Array.isArray(S.detail.sections)){
      const s = S.detail.sections.filter(x => x.lineCode === code)[0];
      if (s) return s.lineLabel || code;
    }
    const p = industryProfile();
    if (p && Array.isArray(p.lines)){
      const l = p.lines.filter(x => x.code === code)[0];
      if (l) return l.label || code;
    }
    return LINE_LABEL[code] || code || '—';
  }
  function sixDimCoverage(sixDim){
    let covered = 0;
    SIXDIM.forEach(d => { if (Number((sixDim||{})[d[0]]) > 0) covered++; });
    return { covered: covered, total: SIXDIM.length, pct: Math.round(covered / SIXDIM.length * 100) };
  }
  function industryProfile(){
    return (S.industries||[]).filter(x => x.industry === S.selIndustry)[0] || null;
  }
  function industryLabel(code){
    const p = (S.industries||[]).filter(x => x.industry === code)[0];
    return p ? p.name : (code === 'bank' ? '银行业' : code === 'insurance' ? '保险业' : code);
  }
  // 后端 orgTypes 可能返回数组或 {"orgTypes":[...]}，统一取数组
  function orgTypesOf(p){
    const o = p && p.orgTypes;
    if (Array.isArray(o)) return o;
    if (o && Array.isArray(o.orgTypes)) return o.orgTypes;
    return [];
  }
  function acctName(account){
    if (!account) return '—';
    const u = (S.accounts||[]).filter(x => x.account === account)[0];
    return u ? (u.displayName || u.account) : account;
  }
  function roleName(roleId){
    if (!roleId) return '—';
    return S.roles[roleId] || '—';
  }
  function taskById(id){ return (S.tasks||[]).filter(t => t.taskId === id)[0] || null; }
  function sevText(v){ const m = SEVERITY.filter(x => x[0] === v)[0]; return m ? m[1] : (v || '—'); }
  function sevOptions(cur){
    return SEVERITY.map(x => '<option value="'+x[0]+'"'+(x[0]===cur?' selected':'')+'>'+x[1]+'</option>').join('');
  }
  function findingStatusText(v){ const m = FINDING_STATUS.filter(x => x[0] === v)[0]; return m ? m[1] : (v || '—'); }
  function remStatusOptions(cur){
    return REM_STATUS.map(x => '<option value="'+x[0]+'"'+(x[0]===cur?' selected':'')+'>'+x[1]+'</option>').join('');
  }
  function lineOptions(){
    const out = [];
    (S.industries||[]).forEach(function(p){
      (p.lines||[]).forEach(function(l){ if (!out.some(x => x.code === l.code)) out.push({ code:l.code, label:l.label }); });
    });
    return out;
  }
  function cycleOptions(){
    const cycles = [];
    (S.tasks||[]).forEach(function(t){ if (t.cycle && cycles.indexOf(t.cycle) < 0) cycles.push(t.cycle); });
    cycles.sort();
    return '<option value="">全部周期</option>' + cycles.map(function(c){
      return '<option value="'+attr(c)+'"'+(S.filterCycle===c?' selected':'')+'>'+attr(c)+'</option>';
    }).join('');
  }
  function setBtnBusy(btn, busy, busyText){
    if (!btn) return;
    if (busy){ btn.dataset._old = btn.textContent; btn.disabled = true; btn.textContent = busyText || '处理中…'; }
    else { btn.disabled = false; if (btn.dataset._old != null) btn.textContent = btn.dataset._old; }
  }
  function backRow(act, label){
    return '<div class="row" style="margin-bottom:10px;gap:10px">' +
      '<button class="ghost" data-act="'+act+'" title="返回任务列表">← 返回任务列表</button>' +
      '<span class="muted">'+attr(label)+'</span></div>';
  }

  // =====================================================================
  // 入口
  // =====================================================================
  function init(){
    if (!rootEl()) return;
    renderShell();
    renderTabs();
    renderPane();
    Promise.all([loadSession(), loadAccounts(), loadRoles(), loadIndustries(), loadTasks(), loadProgress()])
      .then(function(){ return refreshTemplates(); })
      .then(function(){ renderTabs(); renderPane(); })
      .catch(function(e){
        DZ.toast('初始化数据加载失败，请重试或重新进入本页', 'bad');
        DZ.render('#dsc_pane', DZ.banner('bad', '初始化失败：' + ((e && e.message) || '未知错误'), function(){ init(); }));
      });
  }

  function renderShell(){
    const r = rootEl();
    if (!r) return;
    r.innerHTML =
      '<div id="dsc_tabs"></div>' +
      '<div id="dsc_pane" class="dz-pane"></div>';
    bindDelegation();
  }

  function renderTabs(){
    DZ.tabs('#dsc_tabs', TABS, S.tab, function(key){ switchTab(key); });
  }
  function switchTab(key){
    S.tab = key;
    renderTabs();
    renderPane();
  }
  // 各页签的引导说明：一句话讲清本页签要做什么、按什么顺序做
  const PANE_GUIDE = {
    profile: '<b>行业档案</b>：先建行业档案，确定机构类型、业务条线、敏感数据类型与依据文号侧重，作为行业化自查清单的生成基准。',
    create:  '<b>新建自查任务</b>：填写机构、周期、阶段与依据文件，勾选自查条线后创建任务，再前往「执行自查」。',
    run:     '<b>执行自查</b>：选择任务进入工作台，依次完成 检查项明细 → 责任分配 → 证据与签署 → 任务级判定。',
    recheck: '<b>复查复检</b>：对已提交任务登记问题、创建整改任务、发起复检，并比对复检前后差异。',
    history: '<b>历史审计</b>：查看已闭环任务的历史结论与报告，供审计追溯；进行中的任务请到「执行自查」。'
  };
  function renderPane(){
    const box = $('#dsc_pane');
    if (!box) return;
    box.className = 'dz-pane';
    if (S.tab === 'profile')      renderProfilePane(box);
    else if (S.tab === 'create')  renderCreatePane(box);
    else if (S.tab === 'recheck') renderRecheckPane(box);
    else if (S.tab === 'history') renderHistoryPane(box);
    else                          renderRunPane(box);
    box.insertAdjacentHTML('afterbegin', DZ.guide(PANE_GUIDE[S.tab] || ''));
  }

  // =====================================================================
  // 取数
  // =====================================================================
  async function loadSession(){
    const res = await DZ.get(API.session);
    if (res && !res.error) S.session = res;
  }
  async function loadAccounts(){
    const res = await DZ.get(API.users);
    if (res && !res.error) S.accounts = res.users || [];
  }
  async function loadRoles(){
    const res = await DZ.get(API.roles);
    if (res && !res.error){
      (res.roles || []).forEach(function(r){ S.roles[r.roleId] = r.name; });
    }
  }
  async function loadIndustries(){
    const res = await DZ.get(API.industries);
    if (res && !res.error) S.industries = res.industries || [];
    if (S.industries.length && !S.industries.some(x => x.industry === S.selIndustry))
      S.selIndustry = S.industries[0].industry;
  }
  async function loadProgress(){
    const res = await DZ.get(API.progress);
    if (res && !res.error) S.progress = res;
  }
  async function loadTasks(){
    const qs = [];
    if (S.session && S.session.account) qs.push('account=' + encodeURIComponent(S.session.account));
    if (S.filterIndustry) qs.push('industry=' + encodeURIComponent(S.filterIndustry));
    const res = await DZ.get(API.tasks + (qs.length ? '?' + qs.join('&') : ''));
    if (res && res.error){
      DZ.toast(res.error.message || '任务列表加载失败', 'bad');
      return;
    }
    S.tasks = (res && res.tasks) || [];
    S.scopeCache = {};
  }
  async function refreshTemplates(){
    const key = S.selIndustry + '|' + S.selLine;
    if (S.templatesKey === key && S.templatesEnv && !S.templatesEnv.error) return;
    S.templatesEnv = null;
    S.templatesKey = key;
    if (S.tab === 'profile') renderPane();
    S.templatesEnv = await DZ.get(API.templates(S.selIndustry, S.selLine));
    if (S.tab === 'profile') renderPane();
  }
  async function loadTaskBundle(taskId){
    S.detail = S.items = S.verdict = S.assignments = S.evidence = S.signoff = S.assignPreview = null;
    S.selTaskId = taskId;
    S.detailError = '';
    const [detail, items, verdict, assignments] = await Promise.all([
      DZ.get(API.task(taskId)), DZ.get(API.items(taskId)),
      DZ.get(API.verdict(taskId)), DZ.get(API.assignments(taskId))
    ]);
    if (!detail || detail.error){
      S.detailError = (detail && detail.error && detail.error.message) || '任务明细加载失败';
      DZ.toast(S.detailError, 'bad');
      return;
    }
    S.detail = detail; S.items = (items && items.items) || [];
    S.verdict = (verdict && !verdict.error) ? verdict : null;
    S.assignments = (assignments && !assignments.error) ? assignments : null;
    await Promise.all([loadEvidence(taskId), loadSignoff(taskId)]);
  }
  async function loadEvidence(taskId){
    const res = await DZ.get(API.evidence(taskId));
    S.evidence = (res && !res.error) ? (res.evidence || []) : [];
  }
  async function loadSignoff(taskId){
    const res = await DZ.get(API.signoff(taskId));
    S.signoff = (res && !res.error) ? res : { signoffs: [], submitterAccount: null };
  }
  // 条线筛选：任务列表接口不含条线字段，按需拉取任务明细中的自查范围
  async function ensureScopes(){
    const ids = (S.tasks||[]).map(t => t.taskId).filter(id => !S.scopeCache[id]);
    await Promise.all(ids.map(async function(id){
      const d = await DZ.get(API.task(id), { delay:false });
      const lines = (d && !d.error && d.scope && Array.isArray(d.scope.lines)) ? d.scope.lines : [];
      S.scopeCache[id] = lines;
    }));
  }

  // =====================================================================
  // 通用：任务筛选栏 + 任务列表（执行自查 / 复查复检 / 历史审计共用）
  // =====================================================================
  // 任务筛选行：扁平单行（行业 / 条线 / 周期 + 关键词），不再用卡片外壳占位
  function taskFilterBar(){
    const indOpts = '<option value="">全部行业</option>' + (S.industries||[]).map(function(p){
      return '<option value="'+attr(p.industry)+'"'+(S.filterIndustry===p.industry?' selected':'')+'>'+attr(p.name)+'</option>';
    }).join('');
    const lineSel = '<select data-act="filter-line" title="按条线筛选">' +
      '<option value="">全部条线</option>' + lineOptions().map(function(l){
        return '<option value="'+attr(l.code)+'"'+(S.filterLine===l.code?' selected':'')+'>'+attr(l.label)+'</option>';
      }).join('') + '</select>';
    const dirty = S.filterIndustry || S.filterLine || S.filterCycle || S.keyword;
    return DZ.filterBar([
      { label: '行业', html: '<select data-act="filter-industry" title="按行业筛选">' + indOpts + '</select>' },
      { label: '条线', html: lineSel },
      { label: '周期', html: '<select data-act="filter-cycle" title="按周期筛选">' + cycleOptions() + '</select>' },
      { html: '<input id="dsc_kw" data-act="filter-kw" value="'+attr(S.keyword)+'" title="关键词检索" ' +
          'placeholder="检索机构 / 主题 / 阶段 / 负责人">' }
    ], {
      aria: '自查任务筛选',
      end: dirty ? '<button class="ghost" data-act="filter-reset" title="清除全部筛选条件" ' +
        'aria-label="重置筛选">重置</button>' : ''
    });
  }

  function scopeFilter(t, scope){
    if (scope === 'history') return t.status === 'closed';
    if (scope === 'recheck') return t.status === 'in_progress' || t.status === 'closed';
    return t.status !== 'closed';        // run：草稿 + 进行中
  }
  function visibleTasks(scope){
    const kw = (S.keyword || '').trim().toLowerCase();
    return (S.tasks||[]).filter(function(t){
      if (!scopeFilter(t, scope)) return false;
      if (S.filterCycle && t.cycle !== S.filterCycle) return false;
      if (S.filterLine){
        const lines = S.scopeCache[t.taskId];
        if (!Array.isArray(lines) || lines.indexOf(S.filterLine) < 0) return false;
      }
      if (!kw) return true;
      const hay = [t.orgName, t.cycle, t.stage, t.topic, acctName(t.owner)].join(' ').toLowerCase();
      return hay.indexOf(kw) >= 0;
    });
  }
  function currentListTarget(){
    if (S.tab === 'history') return ['dsc_histlist', 'history'];
    if (S.tab === 'recheck') return ['dsc_relist', 'recheck'];
    return ['dsc_tasklist', 'run'];
  }
  function rerenderList(){
    const t = currentListTarget();
    renderTaskList(t[0], t[1]);
  }
  // 筛选条件变化后原地重刷筛选行（事件走根容器委托，无需重新绑定）
  // 目的：条件"有/无"变化时即时显示或收起「重置」，不整页重绘、不打断列表滚动
  function refreshFilterBar(){
    const box = $('#dsc_pane');
    if (!box) return;
    const bar = box.querySelector('.dz-filterbar');
    if (!bar) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = taskFilterBar();
    bar.parentNode.replaceChild(tmp.firstChild, bar);
  }
  function scopeAct(scope){
    if (scope === 'history') return 'hist-open';
    if (scope === 'recheck') return 're-open';
    return 'open-task';
  }
  function scopeSelId(scope){
    if (scope === 'history') return S.histTaskId;
    if (scope === 'recheck') return S.reTaskId;
    return S.selTaskId;
  }
  function renderTaskList(targetId, scope){
    const list = $(targetId);
    if (!list) return;
    const rows = visibleTasks(scope);
    const count = $('#dsc_taskcount');
    if (count) count.textContent = '共 ' + rows.length + ' 个任务';
    if (!rows.length){
      const emptyText = scope === 'history' ? '当前筛选条件下暂无已闭环的自查历史'
        : (scope === 'recheck' ? '当前筛选条件下暂无可复检任务' : '当前筛选条件下暂无自查任务');
      list.innerHTML = DZ.empty(emptyText,
        '<button data-act="goto-create" title="新建自查任务">新建自查任务</button>');
      return;
    }
    const act = scopeAct(scope);
    const selId = scopeSelId(scope);
    list.innerHTML = rows.map(function(t){
      const on = t.taskId === selId;
      return '<div class="pick" data-act="'+act+'" data-id="'+attr(t.taskId)+'" role="button" tabindex="0" ' +
        'title="查看任务：'+attr(t.orgName)+' '+attr(t.cycle)+'" aria-label="查看任务 '+attr(t.orgName)+'" ' +
        'style="align-items:flex-start;'+(on?'border-color:var(--brand);background:var(--brand-soft)':'')+'">' +
        '<div style="flex:1;min-width:0">' +
          '<div class="pick-name" style="font-weight:600">'+attr(t.orgName)+' · '+attr(t.cycle)+'</div>' +
          '<div class="muted" style="white-space:normal">'+attr(industryLabel(t.industry))+' · '+attr(t.stage)+' · '+attr(t.topic)+'</div>' +
          '<div class="row" style="gap:6px;margin-top:4px">' +
            DZ.statusBadge(t.status) + DZ.severityBadge(t.riskLevel) +
            DZ.bar(t.progress) + '<span class="dz-mini">'+DZ.number(t.progress)+'%</span>' +
          '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  // =====================================================================
  // Tab ③：执行自查（进行中任务台账 → 下钻进入执行工作台）
  // =====================================================================
  function renderRunPane(box){
    if (S.selTaskId){
      if (S.detailError){
        box.innerHTML = backRow('run-back', '执行自查') +
          DZ.banner('bad', '任务明细加载失败：' + S.detailError, reloadDetail);
        return;
      }
      if (!S.detail){ box.innerHTML = backRow('run-back', '执行自查') + DZ.skeleton(6); return; }
      box.innerHTML = backRow('run-back', '执行自查 · 任务工作台') +
        '<div id="dsc_subtabs"></div><div id="dsc_subpane" class="dz-pane"></div>';
      renderSubtabs();
      renderSub();
      return;
    }
    box.innerHTML = taskFilterBar() + smartPrecheckCard() +
      '<div class="card">' +
        '<div class="row" style="justify-content:space-between">' +
          '<h3>进行中的自查任务</h3>' +
          '<span class="row" style="gap:8px">' +
            '<span id="dsc_taskcount" class="muted"></span>' +
            '<button class="ghost" data-act="query-tasks" title="重新查询任务列表">查询</button>' +
            '<button data-act="goto-create" title="新建自查任务">新建自查任务</button>' +
          '</span>' +
        '</div>' +
        '<p class="muted">选择一条任务进入执行工作台，逐项登记检查项、分配责任、归集证据并形成任务级判定。</p>' +
        '<div id="dsc_tasklist" style="max-height:58vh;overflow:auto"></div>' +
      '</div>';
    renderTaskList('#dsc_tasklist', 'run');
  }

  // 原「合规自查 · 智能体检查」入口收敛为执行自查内的智能预检动作（保留原页面与后端服务）
  // 呈现为扁平信息条：一行放标题、说明与动作，不再单独占一张卡片
  function smartPrecheckCard(){
    return '<div class="dz-strip">' +
      '<b>智能预检</b>' +
      '<span class="muted">选择一份监管合规文件与被检查文件目录，由智能体依据该文件全部检查项逐项智能研判。</span>' +
      '<button class="ghost" data-act="open-precheck" title="打开智能预检">打开智能预检</button>' +
    '</div>';
  }

  // ---- 执行工作台：子页签 ----
  function renderSubtabs(){
    if (!SUB_TABS.some(x => x.key === S.sub)) S.sub = 'items';
    DZ.tabs('#dsc_subtabs', SUB_TABS, S.sub, function(k){ S.sub = k; renderSubtabs(); renderSub(); });
  }

  function renderSub(){
    const box = $('#dsc_subpane');
    if (!box) return;
    box.innerHTML = renderDetailHeader() + subBody();
  }

  function renderDetailHeader(){
    const d = S.detail;
    const v = d.verdict || {};
    return '<div class="card">' +
      '<div class="row" style="justify-content:space-between">' +
        '<h3 style="margin:0">'+attr(d.orgName)+' · '+attr(d.cycle)+'</h3>' +
        '<span>'+DZ.statusBadge(d.status)+' '+DZ.severityBadge(d.riskLevel)+'</span>' +
      '</div>' +
      '<div class="row" style="gap:14px;margin-top:6px">' +
        '<span class="muted">行业：'+attr(industryLabel(d.industry))+'</span>' +
        '<span class="muted">阶段：'+attr(d.stage)+'</span>' +
        '<span class="muted">主题：'+attr(d.topic)+'</span>' +
        '<span class="muted">负责人：'+attr(acctName(d.owner))+'</span>' +
        '<span class="muted">协办：'+((d.assignees||[]).map(acctName).join('、')||'—')+'</span>' +
      '</div>' +
      '<div class="row" style="gap:10px;margin-top:8px">' +
        '<span class="muted">完成度</span>'+DZ.bar(d.progress)+'<span class="dz-mini">'+DZ.number(d.progress)+'%</span>' +
        '<span class="muted">｜检查项 '+DZ.number(d.itemCount||0)+' 项</span>' +
        '<span class="muted">｜判定 '+DZ.resultBadge(v.result)+'</span>' +
        '<span class="muted">｜风险 '+DZ.severityBadge(v.riskLevel||d.riskLevel)+'</span>' +
      '</div>' +
      ((d.sections||[]).length ?
        '<div class="dz-table-wrap" style="margin-top:8px"><table><thead><tr><th>条线</th><th>负责人</th><th>截止</th><th>状态</th><th>完成度</th></tr></thead><tbody>' +
        d.sections.map(s => '<tr><td>'+attr(s.lineLabel)+'</td>' +
          '<td>'+attr(acctName(s.owner))+'</td><td>'+DZ.date(s.dueDate)+'</td><td>'+DZ.statusBadge(s.status)+'</td>' +
          '<td style="min-width:110px">'+DZ.bar(s.progress)+'<span class="dz-mini">'+DZ.number(s.progress)+'%</span></td></tr>').join('') +
        '</tbody></table></div>' : '') +
    '</div>';
  }

  function subBody(){
    switch (S.sub){
      case 'verdict':  return verdictBody();
      case 'assign':   return assignBody();
      case 'evidence': return evidenceBody();
      default:         return itemsBody();
    }
  }

  // ---- 子页签：检查项明细 ----
  function itemsBody(){
    if (!S.items.length){
      return '<div class="card">' + DZ.empty('该任务暂无检查项记录',
        '<button class="ghost" data-act="reload-items" title="重新加载检查项明细">重新加载</button>') + '</div>';
    }
    return '<div class="card"><h3>检查项明细（共 '+S.items.length+' 项）</h3></div>' +
      S.items.map(itemCard).join('');
  }

  function itemCard(it){
    const code = it.checkCode;
    // 后端 POST /items 在未回传 lineCode/status 时会读取不存在的列而报错，
    // 故此处将既有 lineCode/status 随表单一并回传（值来自后端真实返回，不伪造）。
    return '<div class="card" data-item="'+attr(code)+'" data-line="'+attr(it.lineCode||'')+'" data-status="'+attr(it.status||'')+'" style="padding:14px 16px">' +
      '<div class="row" style="justify-content:space-between">' +
        '<div class="row" style="gap:8px">' +
          '<span class="dz-tag-soft">'+attr(code)+'</span>' + DZ.statusBadge(it.status) +
          '<span class="pill">'+attr(lineLabelOf(it.lineCode))+'</span>' +
        '</div>' +
        '<span class="muted">更新于 '+DZ.date(it.updatedAt)+'</span>' +
      '</div>' +
      '<div class="grid2" style="margin-top:8px">' +
        '<div><label>适用性</label><select data-f="applicability" title="适用性">'+appOptions(it.applicability)+'</select></div>' +
        '<div><label>是否具备制度</label><label class="pick"><input type="checkbox" data-f="hasPolicy" '+(it.hasPolicy?'checked':'')+'>' +
          '<span class="pick-name">已具备对应制度</span></label></div>' +
        '<div><label>实际值</label><input data-f="actualValue" value="'+attr(it.actualValue||'')+'" placeholder="如 覆盖率 85%"></div>' +
        '<div><label>证据（每行一条文件或说明）</label><textarea data-f="evidence" rows="2" placeholder="每行一条">'+attr(evText(it.evidence))+'</textarea></div>' +
      '</div>' +
      '<label>备注</label><textarea data-f="note" rows="2">'+attr(it.note||'')+'</textarea>' +
      '<div class="row" style="margin-top:8px">' +
        '<button data-act="save-item" data-code="'+attr(code)+'" title="保存该检查项录入">保存录入项</button>' +
        '<button class="ghost" data-act="ai-match" data-code="'+attr(code)+'" title="调用 AI 佐证匹配">AI 佐证匹配</button>' +
      '</div>' +
      '<div class="dz-aiout" data-aio="'+attr(code)+'"></div>' +
    '</div>';
  }

  function renderAiResult(res){
    const segs = (res.segments||[]).map(s =>
      '<div class="dz-cite"><div>'+attr(s.text)+'</div>' +
      '<div class="dz-cite-src"><span class="badge b-unk">'+attr((DZ.SRC_LABEL||{})[s.source]||s.source||'—')+'</span> ' +
      '命中分 '+DZ.confidence(s.score)+'</div></div>').join('');
    return '<div style="margin-top:8px">' +
      '<div class="row" style="gap:12px">' +
        '<span class="muted">置信度</span>'+DZ.confidence(res.confidence) +
        '<span class="muted">建议判定</span>'+DZ.resultBadge(res.suggestion) +
        (res.routedToHuman ? DZ.badge('warn','已转人工') : DZ.badge('ok','可自动采纳')) +
      '</div>' +
      (res.routedToHuman ? DZ.banner('warn', res.reason || '置信度不足或属高风险，已转人工确认') : '') +
      segs + '</div>';
  }

  // ---- 子页签：任务级判定 ----
  function verdictBody(){
    const v = S.verdict;
    if (!v){
      return '<div class="card">' + DZ.banner('bad', '判定数据加载失败', reloadVerdict) + '</div>';
    }
    const b = v.basis || {};
    const total = b.total || 0;
    const seg = (label, cnt, resultKey) =>
      '<div class="dz-metric"><span class="dz-metric-k">'+DZ.resultBadge(resultKey)+' '+label+'</span>' +
      '<span class="dz-metric-v">'+DZ.number(cnt||0)+' 项' + (total ? '（'+Math.round((cnt||0)/total*100)+'%）' : '') + '</span></div>';
    return '<div class="card">' +
        '<h3>任务级判定与风险分级</h3>' +
        '<div class="dz-kpi-row is-compact">' +
          DZ.kpi('综合判定', DZ.resultBadge(v.result).replace(/<[^>]+>/g,''), '', v.riskLevel==='high'?'bad':(v.riskLevel==='low'?'ok':'warn')) +
          DZ.kpi('计分（符合率）', DZ.number(v.score,1) + '%', '符合项 / 总项', v.riskLevel==='high'?'bad':(v.riskLevel==='low'?'ok':'warn')) +
          DZ.kpi('风险等级', ({high:'高',medium:'中',low:'低'})[v.riskLevel]||'—', '', v.riskLevel==='high'?'bad':(v.riskLevel==='low'?'ok':'warn')) +
          DZ.kpi('任务状态', DZ.statusBadge(v.taskLevel).replace(/<[^>]+>/g,''), '统计时间 '+DZ.date(v.computedAt)) +
        '</div>' +
        '<h4>计分依据</h4>' +
        seg('符合', b.pass, 'pass') + seg('部分符合', b.partial, 'partial') +
        seg('不符合', b.fail, 'fail') + seg('需补充', b.supplement, 'supplement') +
        '<div class="dz-metric"><span class="dz-metric-k">合计</span><span class="dz-metric-v">'+DZ.number(total)+' 项</span></div>' +
      '</div>';
  }

  // ---- 子页签：责任分配 ----
  function assignBody(){
    const a = S.assignments;
    const cur = a && a.current;
    let curHtml;
    if (!cur){
      curHtml = DZ.empty('该任务暂无已下发批次',
        '<button data-act="preview-assign" title="按规则生成分配预览">生成分配预览</button>');
    } else {
      curHtml = '<div class="row" style="gap:12px">' +
        '<span class="muted">规则版本 '+attr(cur.ruleVersion)+'</span>' +
        '<span class="muted">覆盖率 '+DZ.number(cur.coverage,1)+'%</span>' +
        '<span class="muted">确认人 '+attr(acctName(cur.confirmedBy))+'</span>' +
        '<span class="muted">下发于 '+DZ.date(cur.confirmedAt)+'</span></div>';
    }
    const hist = (a && a.history && a.history.length > 1) ? '<h4>下发记录</h4>' +
      '<div class="dz-table-wrap"><table><thead><tr><th>序号</th><th>规则版本</th><th>覆盖率</th><th>确认人</th><th>下发时间</th></tr></thead><tbody>' +
      a.history.map((h, i) => '<tr><td>第 '+DZ.number(a.history.length - i)+' 批</td><td>'+attr(h.ruleVersion)+'</td>' +
        '<td>'+DZ.number(h.coverage,1)+'%</td><td>'+attr(acctName(h.confirmedBy))+'</td><td>'+DZ.date(h.confirmedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : '';

    const curMapping = (a && a.mapping && a.mapping.length) ? mappingTable(a.mapping, false) : '';
    const prev = S.assignPreview;
    let prevHtml;
    if (prev){
      const un = (prev.unmatched||[]).length ? (prev.unmatched||[]).map(c=>'<span class="dz-tag-soft">'+attr(c)+'</span>').join(' ') : '<span class="muted">无</span>';
      const cf = (prev.conflicts||[]).length ? '<ul style="margin:6px 0 0 18px">'+prev.conflicts.map(c=>'<li><span class="dz-tag-soft">'+attr(c.checkCode)+'</span> '+attr(c.reason)+'</li>').join('')+'</ul>' : '<span class="muted">无</span>';
      prevHtml = '<div class="card">' +
        '<h4>分配预览结果</h4>' +
        '<div class="row" style="gap:14px">' +
          '<span>覆盖率 '+DZ.number(prev.coverage,1)+'%</span>'+DZ.bar(prev.coverage) +
          '<span class="muted">匹配 '+DZ.number(prev.matchedCount)+' 项</span>' +
        '</div>' +
        '<div class="dz-metric"><span class="dz-metric-k">未匹配清单</span><span class="dz-metric-v" style="font-weight:500">'+un+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">冲突清单</span><span class="dz-metric-v" style="font-weight:500">'+cf+'</span></div>' +
        mappingTable(prev.mapping||[], true) +
        '<div class="row" style="margin-top:10px">' +
          '<button data-act="dispatch-assign" title="确认下发责任分配">确认下发</button>' +
          '<span id="as_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
    } else {
      prevHtml = '<div class="card"><div class="row">' +
        '<button data-act="preview-assign" title="按规则生成分配预览">生成分配预览</button></div></div>';
    }

    return '<div class="card"><h3>责任分配</h3>' + curHtml + hist + '</div>' +
      prevHtml +
      (curMapping ? '<div class="card"><h4>当前责任映射</h4>'+curMapping+'</div>' : '') +
      '<div id="as_override_area"></div>';
  }

  function mappingTable(mapping, allowOverride){
    if (!mapping.length) return DZ.empty('暂无责任映射');
    const rows = mapping.map(m =>
      '<tr data-map="'+attr(m.checkCode)+'">' +
        '<td><span class="dz-tag-soft">'+attr(m.checkCode)+'</span></td>' +
        '<td>'+attr(m.title||'')+'</td>' +
        '<td>'+attr(m.deptName||m.deptId||'—')+'</td>' +
        '<td>'+attr(m.positionName||m.positionId||'—')+'</td>' +
        '<td>'+attr(roleName(m.roleId))+'</td>' +
        '<td>'+DZ.badge(m.source==='override'?'warn':'ok', m.source==='override'?'人工覆盖':'按规则')+'</td>' +
        (allowOverride ? '<td><button class="ghost" data-act="override-open" data-code="'+attr(m.checkCode)+'" title="人工覆盖该检查项责任">覆盖</button></td>' : '') +
      '</tr>').join('');
    return '<div class="dz-table-wrap"><table><thead><tr><th>检查项</th><th>标题</th><th>部门</th><th>岗位</th><th>角色</th><th>来源</th>' +
      (allowOverride?'<th>操作</th>':'') + '</tr></thead><tbody>'+rows+'</tbody></table></div>';
  }

  // ---- 子页签：证据与签署 ----
  function evidenceBody(){
    const codeOpts = S.items.map(it => '<option value="'+attr(it.checkCode)+'">'+attr(it.checkCode)+' · '+attr(lineLabelOf(it.lineCode))+'</option>').join('');
    const acctOpts = activeAcctOptions();
    const evRows = S.evidence.length ? '<div class="dz-table-wrap"><table><thead><tr><th>检查项</th><th>文件</th><th>大小</th><th>文件指纹</th><th>上传人</th><th>时间</th></tr></thead><tbody>' +
      S.evidence.map(e => '<tr><td><span class="dz-tag-soft">'+attr(e.checkCode||'—')+'</span></td>' +
        '<td><span class="dz-file-name">'+attr(e.fileName)+'</span><div class="dz-file-meta">'+attr(e.storageRef||'')+'</div></td>' +
        '<td>'+sizeText(e.size)+'</td><td><code title="'+attr(e.fileHash)+'">'+attr(String(e.fileHash||'').slice(0,12))+'…</code></td>' +
        '<td>'+attr(acctName(e.uploadedBy))+'</td><td>'+DZ.date(e.uploadedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : DZ.empty('暂无证据登记');

    const so = S.signoff || { signoffs: [], submitterAccount: null };
    const signRows = (so.signoffs||[]).length ? '<div class="dz-table-wrap"><table><thead><tr><th>签署人</th><th>角色</th><th>决定</th><th>意见</th><th>时间</th></tr></thead><tbody>' +
      so.signoffs.map(s => '<tr><td>'+attr(s.signerName||acctName(s.signer))+'</td>' +
        '<td>'+attr(roleName(s.role))+'</td>' +
        '<td>'+(s.decision==='reject'?DZ.badge('bad','驳回'):DZ.badge('ok','通过'))+'</td>' +
        '<td>'+attr(s.comment||'—')+'</td><td>'+DZ.date(s.signedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : DZ.empty('暂无签署记录');
    const isSubmitter = !!(so.submitterAccount && S.session && so.submitterAccount === S.session.account);
    const roleOpts = Object.keys(S.roles).map(function(k){
      return '<option value="'+attr(k)+'">'+attr(S.roles[k])+'</option>';
    }).join('');

    return '<div class="card"><h3>证据登记</h3>' +
        '<div class="grid2">' +
          '<div><label>检查项</label><select id="ev_code" title="关联检查项">'+(codeOpts||'<option value="">（无检查项）</option>')+'</select></div>' +
          '<div><label>文件名 *</label><input id="ev_name" placeholder="如 访问控制日志截图.png"></div>' +
          '<div><label>大小（字节）</label><input id="ev_size" type="number" placeholder="如 88421" value="88421"></div>' +
          '<div><label>文件指纹（可留空自动生成）</label><input id="ev_hash" placeholder="留空则按文件内容自动生成"></div>' +
          '<div><label>上传人</label><select id="ev_by" title="上传人">'+acctOpts+'</select></div>' +
        '</div>' +
        '<div class="row" style="margin-top:10px"><button data-act="add-evidence" title="登记证据元数据">登记证据</button><span id="ev_msg" class="muted"></span></div>' +
        '<h4>证据列表（'+S.evidence.length+'）</h4>'+evRows +
      '</div>' +
      '<div class="card"><h3>签署与复核</h3>' +
        '<div class="muted">提交人（经办）：'+attr(acctName(so.submitterAccount))+'</div>' +
        (isSubmitter ? DZ.banner('warn', '当前账号即为提交人，直接签署将被拦截；请切换到非提交人账号后再签署。') : '') +
        '<div class="grid2" style="margin-top:8px">' +
          '<div><label>签署账号</label><select id="so_account" title="签署账号">'+acctOpts+'</select></div>' +
          '<div><label>角色</label><select id="so_role" title="签署角色">'+(roleOpts||'<option value="">—</option>')+'</select></div>' +
          '<div><label>决定</label><select id="so_decision" title="签署决定"><option value="approve">通过</option><option value="reject">驳回</option></select></div>' +
          '<div><label>意见</label><input id="so_comment" placeholder="如 复核通过，同意闭环"></div>' +
        '</div>' +
        '<div class="row" style="margin-top:8px"><button data-act="signoff" title="提交签署">提交签署</button></div>' +
        '<div id="so_msg" style="margin-top:10px"></div>' +
        '<h4>签署记录</h4>'+signRows +
      '</div>';
  }

  function activeAcctOptions(){
    const cur = (S.session && S.session.account) || '';
    const opts = (S.accounts||[]).filter(a => a.status === 'active').map(a =>
      '<option value="'+attr(a.account)+'"'+(a.account===cur?' selected':'')+'>'+attr(a.displayName||a.account)+'</option>').join('');
    return opts || '<option value="">—</option>';
  }

  // =====================================================================
  // Tab ②：新建自查任务
  // =====================================================================
  function renderCreatePane(box){
    const prof = industryProfile() || { orgTypes:[], lines:[], docFocus:[] };
    const indOpts = (S.industries||[]).map(p =>
      '<option value="'+attr(p.industry)+'"'+(p.industry===S.selIndustry?' selected':'')+'>'+attr(p.name)+'</option>').join('');
    const orgTypeOpts = orgTypesOf(prof).map(x => '<option value="'+attr(x)+'">'+attr(x)+'</option>').join('');
    const docOpts = (prof.docFocus||[]).map(x => '<option value="'+attr(x)+'">'+attr(DOC_LABEL[x]||x)+'</option>').join('');
    const linePicks = (prof.lines||[]).map(l =>
      '<label class="pick"><input type="checkbox" data-line-pick value="'+attr(l.code)+'">' +
      '<span class="pick-name">'+attr(l.label)+'</span></label>').join('');

    box.innerHTML =
      (S.createdTaskId
        ? DZ.banner('ok', '任务已创建，可前往「执行自查」查看') +
          '<div class="row" style="margin-bottom:12px"><button data-act="goto-tasks" title="前往执行自查">前往执行自查</button></div>'
        : '') +
      '<div class="card">' +
        '<h3>新建自查任务</h3>' +
        '<div class="grid2">' +
          '<div><label>行业 *</label><select id="nt_industry" data-act="create-industry" title="选择行业">'+indOpts+'</select></div>' +
          '<div><label>机构名称 *</label><input id="nt_org" placeholder="如 华东分行"></div>' +
          '<div><label>机构类型</label><select id="nt_orgtype" title="机构类型">'+(orgTypeOpts||'<option value="">—</option>')+'</select></div>' +
          '<div><label>周期</label><input id="nt_cycle" placeholder="如 2026Q4" value="2026Q4"></div>' +
          '<div><label>阶段</label><input id="nt_stage" placeholder="如 季度自查" value="季度自查"></div>' +
          '<div><label>主题</label><input id="nt_topic" placeholder="如 数据安全专项" value="数据安全专项"></div>' +
          '<div><label>依据文件</label><select id="nt_doc" title="依据文件">'+(docOpts||'<option value="">—</option>')+'</select></div>' +
          '<div><label>负责人</label><select id="nt_owner" title="负责人">'+activeAcctOptions()+'</select></div>' +
          '<div><label>起止日期</label><div class="row"><input id="nt_start" type="date" title="开始日期"><input id="nt_end" type="date" title="结束日期"></div></div>' +
          '<div><label>协办（按住 ⌘/Ctrl 多选）</label><select id="nt_assignees" multiple size="3" title="协办人">'+activeAcctOptions()+'</select></div>' +
        '</div>' +
        '<label>自查范围（条线）</label>' +
        '<div class="pick-list">'+(linePicks||'<span class="muted">该行业未定义条线</span>')+'</div>' +
        '<div class="row">' +
          '<button data-act="create-task" title="创建自查任务">创建任务</button>' +
          '<button class="ghost" data-act="goto-tasks" title="前往执行自查">前往执行自查</button>' +
          '<span id="nt_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
  }

  // =====================================================================
  // Tab ①：行业档案
  // 主功能＝创建行业档案；下方为现有档案清单（只读参考）与所选档案的行业化清单。
  // =====================================================================
  function renderProfilePane(box){
    box.innerHTML = industryCreateCard() + industryListCard() + industryDetailCard();
  }

  // 1.1 新建表单
  function industryCreateCard(){
    return '<div class="card">' +
        '<h3>新建自查行业档案</h3>' +
        '<p class="muted">行业档案决定该行业的机构类型、业务条线、敏感数据类型与依据文号侧重，是生成行业化自查清单的基准。</p>' +
        '<div class="grid2">' +
          '<div><label>行业代码 *</label><input id="ip_code" placeholder="英文字母小写（唯一编码）" autocomplete="off"></div>' +
          '<div><label>行业名称 *</label><input id="ip_name" placeholder="如 信托" autocomplete="off"></div>' +
          '<div><label>机构类型（以 / 分隔）</label><input id="ip_orgtypes" placeholder="如 总公司/分公司/专营机构"></div>' +
          '<div><label>敏感数据类型（以 / 分隔）</label><input id="ip_sens" placeholder="如 客户身份信息/账户信息/交易流水"></div>' +
          '<div><label>文号侧重（以 / 分隔）</label><input id="ip_docs" placeholder="按文号简称填写，多个以 / 分隔"></div>' +
          '<div><label>报告模板</label><input id="ip_tpl" value="标准自查报告模板"></div>' +
        '</div>' +
        '<label>条线（每行一条，格式：编码|名称）</label>' +
        '<textarea id="ip_lines" rows="4" placeholder="每行一条，格式：条线编码|条线名称"></textarea>' +
        '<div class="row" style="margin-top:8px">' +
          '<button data-act="create-industry-profile" title="创建行业档案">创建行业档案</button>' +
          '<span id="ip_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
  }

  // 1.2 现有档案清单（只读参考 + 切换查看清单）
  function industryListCard(){
    const list = S.industries || [];
    const rows = list.map(function(p){
      const on = p.industry === S.selIndustry;
      return '<tr' + (on ? ' class="on"' : '') + '>' +
        '<td>' + (on ? '<b>' + attr(p.name) + '</b>' : attr(p.name)) + '</td>' +
        '<td><span class="dz-tag-soft">' + attr(INDUSTRY_LABEL[p.industry] || p.industry) + '</span></td>' +
        '<td>' + (orgTypesOf(p).map(x => DZ.pill(x)).join(' ') || '—') + '</td>' +
        '<td>' + DZ.number((p.lines || []).length) + '</td>' +
        '<td>' + ((p.docFocus || []).map(x => '<span class="dz-tag-soft">' + attr(DOC_LABEL[x] || x) + '</span>').join(' ') || '—') + '</td>' +
        '<td><button class="ghost" data-act="pick-profile" data-industry="' + attr(p.industry) + '" ' +
          'title="查看该行业清单" aria-label="查看 ' + attr(p.name) + ' 清单">查看清单</button></td>' +
      '</tr>';
    }).join('');
    return '<div class="card">' +
        '<div class="row" style="justify-content:space-between">' +
          '<h3>现有行业档案（' + DZ.number(list.length) + '）</h3>' +
          '<button class="ghost" data-act="reload-industries" title="重新查询行业档案">查询</button>' +
        '</div>' +
        '<div class="dz-table-wrap"><table><thead><tr>' +
          '<th>行业名称</th><th>行业代码</th><th>机构类型</th><th>条线数</th><th>文号侧重</th><th>操作</th>' +
        '</tr></thead><tbody>' +
          (rows || '<tr><td colspan="6" class="muted">暂无行业档案，请在上方创建</td></tr>') +
        '</tbody></table></div>' +
      '</div>';
  }

  // 1.3 所选档案详情 + 行业化自查清单
  function industryDetailCard(){
    const prof = industryProfile();
    if (!prof){
      return '<div class="card">' + DZ.empty('尚未选择行业档案', '') + '</div>';
    }
    const lines = prof.lines || [];
    const chips = '<button type="button" class="dz-chip' + (S.selLine === '' ? ' on' : '') +
        '" data-act="sel-line" data-line="" title="显示全部条线">全部条线</button>' +
      lines.map(l => '<button type="button" class="dz-chip' + (S.selLine === l.code ? ' on' : '') +
        '" data-act="sel-line" data-line="' + attr(l.code) + '" title="条线：' + attr(l.label) + '">' +
        attr(l.label) + '</button>').join('');
    return '<div class="card">' +
        '<h3>' + attr(prof.name) + '</h3>' +
        '<div class="dz-metric"><span class="dz-metric-k">机构类型</span><span class="dz-metric-v">' +
          (orgTypesOf(prof).map(x => DZ.pill(x)).join(' ') || '—') + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">敏感数据类型</span><span class="dz-metric-v">' +
          ((prof.sensitiveTypes || []).map(x => DZ.pill(x)).join(' ') || '—') + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">文号侧重</span><span class="dz-metric-v">' +
          ((prof.docFocus || []).map(x => '<span class="dz-tag-soft">' + attr(DOC_LABEL[x] || x) + '</span>').join(' ') || '—') + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">报告模板</span><span class="dz-metric-v">' + DZ.pill(prof.reportTemplate || '—') + '</span></div>' +
        '<div class="dz-chipbar"><span class="dz-chipgroup-label">条线</span>' + chips + '</div>' +
      '</div>' + templatesCard();
  }

  function templatesCard(){
    const env = S.templatesEnv;
    if (!env) return '<div class="card"><h3>行业化自查清单</h3>' + DZ.skeleton(5) + '</div>';
    if (env.error){
      return '<div class="card"><h3>行业化自查清单</h3>' +
        DZ.banner('bad', env.error.message || '清单加载失败', refreshTemplates) + '</div>';
    }
    if (!env.content){
      return '<div class="card"><h3>行业化自查清单</h3>' +
        DZ.empty('该行业暂无自查清单模板',
          '<button class="ghost" data-act="reload-templates" title="重新加载清单">重新加载</button>') + '</div>';
    }
    const c = env.content;
    let groups = c.groups || [];
    if (S.selLine) groups = groups.filter(g => g.line === S.selLine);
    const body = groups.length ? groups.map(g => {
      const rows = (g.items||[]).map(it => {
        const cp = sixDimCoverage(it.sixDim);
        const six = SIXDIM.map(d => '<span class="dz-tag-soft" title="'+d[1]+'">'+d[1]+' ' + DZ.number((it.sixDim||{})[d[0]]||0) + '</span>').join(' ');
        return '<tr>' +
          '<td><span class="dz-tag-soft">'+attr(it.checkCode)+'</span></td>' +
          '<td>'+attr(it.title)+'</td>' +
          '<td>'+DZ.badge((it.priority==='P0'?'p0':it.priority==='P2'?'p2':'p1'), it.priority||'P1')+'</td>' +
          '<td>'+attr(it.domain ? (DOMAIN_LABEL[it.domain]||it.domain) : '—')+'</td>' +
          '<td style="min-width:220px">'+six+'</td>' +
          '<td style="min-width:120px">'+DZ.bar(cp.pct)+'<span class="dz-mini">'+cp.covered+'/'+cp.total+'（'+cp.pct+'%）</span></td>' +
        '</tr>';
      }).join('');
      return '<div class="card">' +
        '<h4>'+attr(g.lineLabel)+' <span class="muted">（'+((g.items||[]).length)+' 项）</span></h4>' +
        '<div class="dz-table-wrap"><table><thead><tr>' +
          '<th>检查项</th><th>标题</th><th>优先级</th><th>领域</th><th>维度摘要（要素/度量/证据/方法/访谈/关联）</th><th>完整度</th>' +
        '</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
    }).join('') : DZ.empty('该条线下暂无清单项',
      '<button class="ghost" data-act="sel-line" data-line="" title="显示全部条线">显示全部条线</button>');
    return '<div class="card">' +
        '<h3>行业化自查清单</h3>' +
        '<div class="row" style="justify-content:space-between">' +
          '<span>'+DZ.srcBar(env)+'</span>' +
          '<span class="muted">'+DZ.pill('版本 '+(c.snapshotVersion||'—'))+' 生成于 '+DZ.date(c.generatedAt)+
            ' · 主文号 '+attr(DOC_LABEL[c.primaryDoc]||c.primaryDoc||'—')+'</span>' +
        '</div>' +
      '</div>' + body;
  }

  // =====================================================================
  // Tab ④：复查复检（问题 → 整改 → 发起复检 → 差异比对）
  // =====================================================================
  function renderRecheckPane(box){
    if (!S.reTaskId){
      box.innerHTML = taskFilterBar() +
        '<div class="card">' +
          '<div class="row" style="justify-content:space-between">' +
            '<h3>待复查复检的任务</h3>' +
            '<span class="row" style="gap:8px">' +
              '<span id="dsc_taskcount" class="muted"></span>' +
              '<button class="ghost" data-act="query-tasks" title="重新查询任务列表">查询</button>' +
            '</span>' +
          '</div>' +
          '<p class="muted">选择任务后，可登记问题、创建整改任务、发起复检，并查看复检前后差异比对。</p>' +
          '<div id="dsc_relist" style="max-height:56vh;overflow:auto"></div>' +
        '</div>';
      renderTaskList('#dsc_relist', 'recheck');
      return;
    }
    if (S.reFindings === null && !S.reError){
      box.innerHTML = backRow('re-back', '复查复检') + DZ.skeleton(6);
      return;
    }
    box.innerHTML = backRow('re-back', '复查复检') + recheckDetailHtml();
  }

  function recheckDetailHtml(){
    const t = taskById(S.reTaskId);
    const head = t ? '<div class="card">' +
      '<div class="row" style="justify-content:space-between">' +
        '<h3 style="margin:0">'+attr(t.orgName)+' · '+attr(t.cycle)+'</h3>' +
        '<button data-act="run-recheck" title="依据整改情况发起复检">发起复检</button>' +
      '</div>' +
      '<div class="row" style="gap:14px;margin-top:6px">' +
        '<span>'+DZ.statusBadge(t.status)+' '+DZ.severityBadge(t.riskLevel)+'</span>' +
        '<span class="muted">行业：'+attr(industryLabel(t.industry))+'</span>' +
        '<span class="muted">主题：'+attr(t.topic)+'</span>' +
        '<span class="muted">负责人：'+attr(acctName(t.owner))+'</span>' +
      '</div>' +
      '<div class="row" style="gap:10px;margin-top:8px"><span class="muted">完成度</span>' +
        DZ.bar(t.progress)+'<span class="dz-mini">'+DZ.number(t.progress)+'%</span></div>' +
      '</div>' : '';
    return head +
      (S.reError ? DZ.banner('bad', '问题清单加载失败：' + S.reError, function(){ onOpenRecheck(S.reTaskId); }) : '') +
      findingsCard() + remediationsCard() + recheckCard();
  }

  function findingsCard(){
    const arr = S.reFindings || [];
    const rows = arr.map(function(f){
      return '<tr>' +
        '<td><span class="dz-tag-soft">'+attr(f.findingId)+'</span></td>' +
        '<td><span class="dz-tag-soft">'+attr(f.checkCode||'—')+'</span></td>' +
        '<td>'+DZ.severityBadge(f.severity)+'</td>' +
        '<td>'+attr(f.problem)+'</td>' +
        '<td>'+attr(f.rootCause||'—')+'</td>' +
        '<td>'+DZ.badge(FINDING_TONE[f.status]||'unk', findingStatusText(f.status))+'</td>' +
        '<td>'+attr(acctName(f.owner))+'</td>' +
        '<td>'+DZ.date(f.dueDate)+'</td>' +
        '<td><button class="ghost" data-act="new-remediation" data-fid="'+attr(f.findingId)+'" title="为该问题创建整改任务">创建整改</button></td>' +
      '</tr>';
    }).join('');
    return '<div class="card">' +
      '<div class="row" style="justify-content:space-between">' +
        '<h3>问题清单（'+DZ.number(arr.length)+'）</h3>' +
        '<button data-act="new-finding" title="登记一个新问题">登记问题</button>' +
      '</div>' +
      (S.reForm && S.reForm.kind === 'finding' ? reFormHtml() : '') +
      (arr.length ? '<div class="dz-table-wrap"><table><thead><tr>' +
        '<th>问题编号</th><th>检查项</th><th>严重度</th><th>问题描述</th><th>根因</th><th>状态</th><th>责任人</th><th>期限</th><th>操作</th>' +
        '</tr></thead><tbody>'+rows+'</tbody></table></div>'
       : DZ.empty('该任务暂无登记问题',
           '<button data-act="new-finding" title="登记一个新问题">登记问题</button>')) +
    '</div>';
  }

  function remediationsCard(){
    const arr = S.reFindings || [];
    const flat = [];
    arr.forEach(f => (f.remediations||[]).forEach(r => flat.push({ f: f, r: r })));
    const rows = flat.map(function(x){
      const r = x.r;
      return '<tr>' +
        '<td><span class="dz-tag-soft">'+attr(r.remediationId)+'</span></td>' +
        '<td><span class="dz-tag-soft">'+attr(x.f.findingId)+'</span> '+attr(x.f.problem)+'</td>' +
        '<td>'+attr(r.measures||'—')+'</td>' +
        '<td>'+attr(acctName(r.owner))+'</td>' +
        '<td>'+DZ.date(r.dueDate)+'</td>' +
        '<td>'+(REM_STATUS.some(m=>m[0]===r.status) ? DZ.badge(r.status==='done'?'ok':(r.status==='open'?'warn':'warn'), (REM_STATUS.filter(m=>m[0]===r.status)[0]||[])[1]||r.status) : DZ.badge('unk', r.status||'—'))+'</td>' +
        '<td class="muted">'+attr(r.evidenceRef||'—')+'</td>' +
        '<td><button class="ghost" data-act="edit-remediation" data-rid="'+attr(r.remediationId)+'" ' +
          'data-status="'+attr(r.status||'')+'" data-ev="'+attr(r.evidenceRef||'')+'" title="更新整改任务状态与证据">更新</button></td>' +
      '</tr>';
    }).join('');
    return '<div class="card">' +
      '<div class="row" style="justify-content:space-between">' +
        '<h3>整改任务（'+DZ.number(flat.length)+'）</h3>' +
        '<span class="muted">从问题清单的「创建整改」发起</span>' +
      '</div>' +
      (S.reForm && (S.reForm.kind === 'remediation' || S.reForm.kind === 'update') ? reFormHtml() : '') +
      (flat.length ? '<div class="dz-table-wrap"><table><thead><tr>' +
        '<th>整改编号</th><th>对应问题</th><th>整改措施</th><th>责任人</th><th>期限</th><th>状态</th><th>证据引用</th><th>操作</th>' +
        '</tr></thead><tbody>'+rows+'</tbody></table></div>'
       : DZ.empty('暂无整改任务')) +
    '</div>';
  }

  function reFormHtml(){
    const f = S.reForm;
    if (!f) return '';
    if (f.kind === 'finding'){
      const codeOpts = (S.reItems||[]).map(it => '<option value="'+attr(it.checkCode)+'">'+attr(it.checkCode)+' · '+attr(lineLabelOf(it.lineCode))+'</option>').join('');
      return '<div class="card" style="background:var(--brand-soft)">' +
        '<h4>登记问题</h4>' +
        '<div class="grid2">' +
          '<div><label>检查项 *</label><select id="nf_code" title="关联检查项">'+(codeOpts||'<option value="">（无检查项）</option>')+'</select></div>' +
          '<div><label>严重度</label><select id="nf_sev" title="严重度">'+sevOptions('medium')+'</select></div>' +
          '<div><label>责任人</label><select id="nf_owner" title="责任人">'+activeAcctOptions()+'</select></div>' +
          '<div><label>整改期限</label><input id="nf_due" type="date" title="整改期限"></div>' +
        '</div>' +
        '<label>问题描述 *</label><textarea id="nf_problem" rows="2" placeholder="如 敏感数据操作日志记录要素不完整"></textarea>' +
        '<label>根因分析</label><input id="nf_root" placeholder="如 日志采集组件未覆盖全部敏感数据操作">' +
        '<div class="row" style="margin-top:8px"><button data-act="submit-finding" title="登记问题">登记问题</button>' +
          '<button class="ghost" data-act="re-cancel" title="取消">取消</button><span id="re_msg" class="muted"></span></div>' +
      '</div>';
    }
    if (f.kind === 'remediation'){
      return '<div class="card" style="background:var(--brand-soft)">' +
        '<h4>创建整改任务 · 问题 <span class="dz-tag-soft">'+attr(f.fid)+'</span></h4>' +
        '<div class="grid2">' +
          '<div><label>整改责任人</label><select id="nr_owner" title="整改责任人">'+activeAcctOptions()+'</select></div>' +
          '<div><label>整改期限</label><input id="nr_due" type="date" title="整改期限"></div>' +
        '</div>' +
        '<label>整改措施 *</label><textarea id="nr_measures" rows="2" placeholder="如 扩展日志采集组件覆盖范围，补齐操作主体/客体/时间/结果四要素。"></textarea>' +
        '<div class="row" style="margin-top:8px"><button data-act="submit-remediation" title="创建整改任务">创建整改任务</button>' +
          '<button class="ghost" data-act="re-cancel" title="取消">取消</button><span id="re_msg" class="muted"></span></div>' +
      '</div>';
    }
    if (f.kind === 'update'){
      return '<div class="card" style="background:var(--brand-soft)">' +
        '<h4>更新整改任务 · <span class="dz-tag-soft">'+attr(f.rid)+'</span></h4>' +
        '<div class="grid2">' +
          '<div><label>状态</label><select id="nr_status" title="整改状态">'+remStatusOptions(f.status)+'</select></div>' +
          '<div><label>证据引用</label><input id="nr_ev" value="'+attr(f.evidenceRef||'')+'" placeholder="如 demo://evidence/rem-3.md"></div>' +
        '</div>' +
        '<div class="row" style="margin-top:8px"><button data-act="submit-remediation-update" data-rid="'+attr(f.rid)+'" title="保存整改任务">保存</button>' +
          '<button class="ghost" data-act="re-cancel" title="取消">取消</button><span id="re_msg" class="muted"></span></div>' +
      '</div>';
    }
    return '';
  }

  function recheckCard(){
    if (S.reDiffError && !S.reDiff){
      return '<div class="card"><h3>复检与差异比对</h3>' +
        DZ.banner('warn', S.reDiffError) +
        '<div class="row" style="margin-top:8px"><button data-act="run-recheck" title="发起复检">发起复检</button></div></div>';
    }
    const d = S.reDiff;
    if (!d) return '<div class="card"><h3>复检与差异比对</h3>' + DZ.skeleton(4) + '</div>';
    const tl = d.taskLevel || {};
    const b = tl.before || {}, a = tl.after || {}, dl = tl.delta || {};
    const items = d.items || [];
    const changed = items.filter(x => x.changed);
    const deltaTxt = (Number(dl.pass) > 0 ? '+' : '') + DZ.number(dl.pass, 1) + '%';
    return '<div class="card"><h3>复检与差异比对</h3>' +
      '<div class="dz-kpi-row is-compact">' +
        DZ.kpi('初检符合率', DZ.number(b.pass,1)+'%', '不符合 '+DZ.number(b.fail||0)+' 项', 'bad') +
        DZ.kpi('复检符合率', DZ.number(a.pass,1)+'%', '不符合 '+DZ.number(a.fail||0)+' 项', 'ok') +
        DZ.kpi('符合率变化', deltaTxt, '复检 − 初检', (Number(dl.pass) >= 0 ? 'ok' : 'bad')) +
        DZ.kpi('发生变化检查项', DZ.number(changed.length)+' 项', '共 '+DZ.number(items.length)+' 项') +
      '</div>' +
      '<div class="row" style="gap:14px;margin:8px 0">' +
        '<span class="muted">初检运行 '+attr(d.beforeRun)+'</span>' +
        '<span class="muted">复检运行 '+attr(d.afterRun)+'</span>' +
        '<button class="ghost" data-act="run-recheck" title="重新发起复检">发起复检</button>' +
      '</div>' +
      (changed.length ? '<div class="dz-table-wrap"><table><thead><tr><th>检查项</th><th>初检</th><th>复检</th><th>变化</th></tr></thead><tbody>' +
        changed.map(x => '<tr><td><span class="dz-tag-soft">'+attr(x.checkCode)+'</span></td>' +
          '<td>'+DZ.resultBadge(x.before)+'</td><td>'+DZ.resultBadge(x.after)+'</td>' +
          '<td>'+DZ.badge('ok','已改善')+'</td></tr>').join('') +
        '</tbody></table></div>' : DZ.empty('复检前后检查项结果无变化')) +
    '</div>';
  }

  // =====================================================================
  // Tab ⑤：历史审计（已闭环任务 → 历史结论与报告，只读）
  // =====================================================================
  function renderHistoryPane(box){
    if (S.histTaskId){
      if (S.histError){
        box.innerHTML = backRow('hist-back', '历史审计') +
          DZ.banner('bad', '历史明细加载失败：' + S.histError, reloadHistory);
        return;
      }
      if (S.histReport === null){ box.innerHTML = backRow('hist-back', '历史审计') + DZ.skeleton(6); return; }
      box.innerHTML = backRow('hist-back', '历史审计') + historyDetailHtml();
      return;
    }
    box.innerHTML = progressKpiHtml() +
      '<div class="card">' +
        '<div class="row" style="justify-content:space-between">' +
          '<h3>已闭环自查历史</h3>' +
          '<span class="row" style="gap:8px">' +
            '<span id="dsc_taskcount" class="muted"></span>' +
            '<button class="ghost" data-act="query-tasks" title="重新查询任务列表">查询</button>' +
          '</span>' +
        '</div>' +
        '<p class="muted">仅展示已闭环任务的历史结论与报告，供审计追溯；进行中的任务请到「执行自查」。</p>' +
        '<div id="dsc_histlist" style="max-height:56vh;overflow:auto"></div>' +
      '</div>';
    renderTaskList('#dsc_histlist', 'history');
  }

  function progressKpiHtml(){
    const p = S.progress;
    if (!p) return '<div class="card"><h3>自查总体看板</h3>' + DZ.skeleton(2) + '</div>';
    const k = p.kpis || {};
    return '<div class="card"><h3>自查总体看板</h3><div class="dz-kpi-row is-compact">' +
      DZ.kpi('自查任务总数', DZ.number(k.tasks||0), '含草稿 / 进行中 / 已闭环') +
      DZ.kpi('进行中', DZ.number(k.inProgress||0), '草稿 '+DZ.number(k.draft||0)+' 项', 'warn') +
      DZ.kpi('已闭环', DZ.number(k.closed||0), '已完成复核归档', 'ok') +
      DZ.kpi('平均完成度', DZ.number(k.avgProgress,1)+'%') +
    '</div></div>';
  }

  function historyDetailHtml(){
    const rep = S.histReport || {};
    const m = rep.meta || {}, s = rep.summary || {}, five = rep.five || {};
    const items = rep.items || [];
    const itemRows = items.map(it => '<tr>' +
      '<td><span class="dz-tag-soft">'+attr(it.checkCode)+'</span></td>' +
      '<td>'+DZ.resultBadge(it.result)+'</td>' +
      '<td>'+(it.evidenceComplete?DZ.badge('ok','齐备'):DZ.badge('warn','缺口'))+'</td>' +
      '<td>'+(it.contentAdequate?DZ.badge('ok','完备'):DZ.badge('warn','待补'))+'</td>' +
      '<td class="muted">'+attr(it.remediation||'—')+'</td>' +
    '</tr>').join('');
    return '<div class="card">' +
      '<div class="row" style="justify-content:space-between">' +
        '<h3 style="margin:0">'+attr(m.orgName)+' · '+attr(m.cycle)+'</h3>' +
        '<button class="ghost" data-act="export-report" data-id="'+attr(m.taskId)+'" title="导出 Markdown 报告">导出报告（MD）</button>' +
      '</div>' +
      '<div class="row" style="gap:14px;margin-top:6px">' +
        '<span class="muted">行业：'+attr(industryLabel(m.industry))+'</span>' +
        '<span class="muted">生成时间：'+DZ.date(m.generatedAt)+'</span>' +
        '<span class="muted">数据标识：'+attr(m.dataLabel||'—')+'</span>' +
        '<span class="muted">模板：'+attr(m.template||'—')+'</span>' +
      '</div>' +
      '<div class="dz-kpi-row is-compact" style="margin-top:8px">' +
        DZ.kpi('结论判定', DZ.resultBadge(s.verdict).replace(/<[^>]+>/g,''), '', s.riskLevel==='high'?'bad':(s.riskLevel==='low'?'ok':'warn')) +
        DZ.kpi('得分（符合率）', DZ.number(s.score,1)+'%', '符合 '+DZ.number(s.pass)+' / '+DZ.number(s.total)+' 项') +
        DZ.kpi('风险等级', sevText(s.riskLevel), '', s.riskLevel==='high'?'bad':(s.riskLevel==='low'?'ok':'warn')) +
        DZ.kpi('检查项合计', DZ.number(s.total)+' 项') +
      '</div>' +
    '</div>' +
    listCard('一、问题清单', (five.problems||[]).map(p => '<li><span class="dz-tag-soft">'+attr(p.code)+'</span> '+attr(p.text)+'</li>')) +
    tableCard('二、依据条款', ['监管要求','判定口径'], (five.bases||[]).map(b => '<tr><td>'+attr(b.requirement)+'</td><td>'+attr(b.criterion)+'</td></tr>')) +
    tableCard('三、责任归属', ['环节','发起','审批','复核','问责'], (five.ownership||[]).map(o => '<tr>' +
      '<td>'+attr(o.title)+' <span class="dz-tag-soft">'+attr(o.code)+'</span></td>' +
      '<td>'+attr(o.initiator)+'</td><td>'+attr(o.approver)+'</td><td>'+attr(o.reviewer)+'</td><td>'+attr(o.accountable)+'</td></tr>')) +
    listCard('四、证据缺口', (five.evidenceGaps||[]).map(g => '<li><span class="dz-tag-soft">'+attr(g.code)+'</span> '+attr(g.text)+'</li>')) +
    listCard('五、下一步建议', (five.nextSteps||[]).map(n => '<li><b>'+attr(n.priority)+'</b>：'+attr(n.text)+'</li>')) +
    (five.note ? '<div class="card"><div class="muted">'+attr(five.note)+'</div></div>' : '') +
    '<div class="card"><h3>附：逐条检查项明细（'+DZ.number(items.length)+'）</h3>' +
      (items.length ? '<div class="dz-table-wrap"><table><thead><tr>' +
        '<th>检查项</th><th>结论</th><th>证据完整</th><th>内容完备</th><th>整改说明</th>' +
        '</tr></thead><tbody>'+itemRows+'</tbody></table></div>' : DZ.empty('无检查项明细')) +
    '</div>';
  }

  function listCard(title, lis){
    return '<div class="card"><h3>'+attr(title)+'</h3>' +
      (lis && lis.length ? '<ul style="margin:6px 0 0 18px">'+lis.join('')+'</ul>' : DZ.empty('无')) + '</div>';
  }
  function tableCard(title, heads, rows){
    return '<div class="card"><h3>'+attr(title)+'</h3>' +
      (rows && rows.length ? '<div class="dz-table-wrap"><table><thead><tr>' +
        heads.map(h => '<th>'+attr(h)+'</th>').join('') + '</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>'
       : DZ.empty('无')) + '</div>';
  }

  // =====================================================================
  // 交互（事件委托，绑定一次）
  // =====================================================================
  let bound = false;
  function bindDelegation(){
    const r = rootEl();
    if (!r || bound) return;
    bound = true;

    r.addEventListener('click', function(e){
      const t = e.target.closest('[data-act]');
      if (!t) return;
      const act = t.getAttribute('data-act');
      // 行业档案
      if (act === 'sel-line') onSelLine(t.getAttribute('data-line'));
      else if (act === 'create-industry-profile') onCreateIndustryProfile(t);
      else if (act === 'pick-profile') onPickProfile(t.getAttribute('data-industry'));
      else if (act === 'reload-templates') onReloadTemplates(t);
      else if (act === 'reload-industries') onReloadIndustries(t);
      // 新建任务
      else if (act === 'create-task') onCreateTask(t);
      else if (act === 'goto-create'){ S.tab = 'create'; renderTabs(); renderPane(); }
      else if (act === 'goto-tasks') onGotoTasks();
      // 执行自查
      else if (act === 'open-task') onOpenTask(t.getAttribute('data-id'));
      else if (act === 'run-back') onRunBack();
      else if (act === 'query-tasks') onQueryTasks(t);
      else if (act === 'filter-reset') onResetFilters();
      else if (act === 'open-precheck') openPrecheck();
      else if (act === 'save-item') onSaveItem(t.getAttribute('data-code'), t);
      else if (act === 'ai-match') onAiMatch(t.getAttribute('data-code'), t);
      else if (act === 'reload-items') reloadDetail();
      else if (act === 'preview-assign') onPreviewAssign(t);
      else if (act === 'dispatch-assign') onDispatchAssign(t);
      else if (act === 'override-open') onOverrideOpen(t.getAttribute('data-code'));
      else if (act === 'override-submit') onOverrideSubmit(t.getAttribute('data-code'), t);
      else if (act === 'override-cancel'){ const a = $('#as_override_area'); if (a) a.innerHTML = ''; }
      else if (act === 'add-evidence') onAddEvidence(t);
      else if (act === 'signoff') onSignoff(t);
      // 复查复检
      else if (act === 're-open') onOpenRecheck(t.getAttribute('data-id'));
      else if (act === 're-back') onReBack();
      else if (act === 'run-recheck') onRunRecheck(t);
      else if (act === 'new-finding'){ S.reForm = { kind:'finding' }; renderPane(); }
      else if (act === 'new-remediation'){ S.reForm = { kind:'remediation', fid:t.getAttribute('data-fid') }; renderPane(); }
      else if (act === 'edit-remediation'){
        S.reForm = { kind:'update', rid:t.getAttribute('data-rid'),
                     status:t.getAttribute('data-status'), evidenceRef:t.getAttribute('data-ev') };
        renderPane();
      }
      else if (act === 're-cancel'){ S.reForm = null; renderPane(); }
      else if (act === 'submit-finding') onSubmitFinding(t);
      else if (act === 'submit-remediation') onSubmitRemediation(t);
      else if (act === 'submit-remediation-update') onSubmitRemediationUpdate(t);
      // 历史审计
      else if (act === 'hist-open') onOpenHistory(t.getAttribute('data-id'));
      else if (act === 'hist-back') onHistBack();
      else if (act === 'export-report') onExportReport(t.getAttribute('data-id'));
    });

    // 键盘可达：任务卡 Enter / Space 打开
    r.addEventListener('keydown', function(e){
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const t = e.target.closest('[data-act]');
      if (!t) return;
      const act = t.getAttribute('data-act');
      if (act === 'open-task' || act === 'hist-open' || act === 're-open'){
        e.preventDefault();
        const id = t.getAttribute('data-id');
        if (act === 'open-task') onOpenTask(id);
        else if (act === 'hist-open') onOpenHistory(id);
        else onOpenRecheck(id);
      }
    });

    // 下拉 / 输入变化
    r.addEventListener('change', function(e){
      const t = e.target.closest('[data-act]');
      if (!t) return;
      const act = t.getAttribute('data-act');
      if (act === 'filter-industry'){ S.filterIndustry = t.value; loadTasks().then(function(){ renderPane(); }); }
      else if (act === 'filter-cycle'){ S.filterCycle = t.value; rerenderList(); refreshFilterBar(); }
      else if (act === 'filter-line'){ onFilterLine(t.value); refreshFilterBar(); }
      else if (act === 'filter-kw'){ S.keyword = t.value; rerenderList(); refreshFilterBar(); }
      else if (act === 'create-industry'){ S.selIndustry = t.value; S.selLine = ''; renderCreatePane($('#dsc_pane')); }
    });
  }

  function onSelLine(line){
    S.selLine = line || '';
    refreshTemplates();
  }
  function onPickProfile(code){
    if (!code) return;
    S.selIndustry = code;
    S.selLine = '';
    S.templatesKey = '';
    renderPane();
    refreshTemplates();
  }
  async function onCreateIndustryProfile(btn){
    const msg = $('ip_msg');
    const code = (($('ip_code') || {}).value || '').trim();
    const name = (($('ip_name') || {}).value || '').trim();
    if (!code || !name){
      if (msg) msg.textContent = '行业代码与行业名称为必填';
      DZ.toast('请填写行业代码与行业名称', 'warn');
      return;
    }
    const split = v => (v || '').split(/[/、,，\s]+/).map(x => x.trim()).filter(Boolean);
    const lines = (($('ip_lines') || {}).value || '').split('\n')
      .map(x => x.trim()).filter(Boolean).map(function(one){
        const p = one.split('|');
        return { code: (p[0] || '').trim(), label: (p[1] || p[0] || '').trim() };
      }).filter(x => x.code);
    const body = {
      industry: code, name: name,
      orgTypes: split(($('ip_orgtypes') || {}).value),
      sensitiveTypes: split(($('ip_sens') || {}).value),
      docFocus: split(($('ip_docs') || {}).value),
      reportTemplate: (($('ip_tpl') || {}).value || '').trim() || '标准自查报告模板',
      lines: lines
    };
    setBtnBusy(btn, true, '创建中…');
    const res = await DZ.post(API.industries, body);
    setBtnBusy(btn, false);
    if (res && res.error){
      if (msg) msg.textContent = res.error.message || '创建失败';
      DZ.toast(res.error.message || '创建失败', 'bad');
      return;
    }
    DZ.toast('行业档案已创建', 'ok');
    S.selIndustry = (res && res.industry) || code;
    S.selLine = ''; S.templatesKey = '';
    await loadIndustries();
    await refreshTemplates();
    renderPane();
  }
  function onQueryTasks(btn){
    setBtnBusy(btn, true, '查询中…');
    loadTasks().then(function(){
      setBtnBusy(btn, false);
      renderPane();
    });
  }

  // 清除筛选条件后重查：行业口径变化需重新拉取任务，其余为本地过滤
  function onResetFilters(){
    S.filterIndustry = '';
    S.filterLine = '';
    S.filterCycle = '';
    S.keyword = '';
    loadTasks().then(function(){ renderPane(); });
  }
  function onFilterLine(code){
    S.filterLine = code || '';
    if (!S.filterLine){ rerenderList(); return; }
    const target = currentListTarget();
    const list = $(target[0]);
    if (list) list.innerHTML = DZ.skeleton(4);
    ensureScopes().then(function(){ rerenderList(); });
  }
  function onReloadTemplates(btn){
    setBtnBusy(btn, true, '加载中…');
    S.templatesKey = '';
    refreshTemplates().then(function(){ setBtnBusy(btn, false); });
  }
  function onReloadIndustries(btn){
    setBtnBusy(btn, true, '查询中…');
    loadIndustries().then(function(){
      S.templatesKey = '';
      return refreshTemplates();
    }).then(function(){ setBtnBusy(btn, false); renderPane(); });
  }
  function onGotoTasks(){
    const id = S.createdTaskId;
    S.tab = 'run';
    if (id) S.selTaskId = id;
    renderTabs();
    renderPane();
    if (id){
      S.createdTaskId = null;
      onOpenTask(id);
    }
  }
  function openPrecheck(){
    if (typeof window.showView === 'function') window.showView('selfcheck');
    else DZ.toast('智能预检入口不可用', 'bad');
  }

  // ---- 执行自查：任务工作台 ----
  async function onOpenTask(id){
    if (!id) return;
    S.selTaskId = id; S.sub = 'items';
    S.detail = null; S.detailError = '';
    renderPane();
    await loadTaskBundle(id);
    if (S.selTaskId !== id) return;
    renderPane();
  }
  function onRunBack(){
    S.selTaskId = null; S.detail = null; S.detailError = '';
    renderPane();
  }
  async function reloadDetail(){
    if (!S.selTaskId) return;
    const box = $('#dsc_pane');
    if (box) box.innerHTML = DZ.skeleton(6);
    await loadTaskBundle(S.selTaskId);
    renderPane();
  }
  async function reloadVerdict(){
    const res = await DZ.get(API.verdict(S.selTaskId));
    S.verdict = (res && !res.error) ? res : null;
    renderSub();
  }

  // ---- 新建任务 ----
  async function onCreateTask(btn){
    const msg = $('nt_msg');
    const industry = ($('nt_industry')||{}).value || S.selIndustry;
    const orgName = (($('nt_org')||{}).value || '').trim();
    if (!orgName){ if (msg) msg.textContent = '请填写机构名称'; DZ.toast('机构名称为必填', 'warn'); return; }
    const scopeLines = Array.prototype.slice.call(document.querySelectorAll('[data-line-pick]:checked')).map(x => x.value);
    const assignees = ($('nt_assignees') && $('nt_assignees').selectedOptions)
      ? Array.prototype.slice.call($('nt_assignees').selectedOptions).map(o => o.value) : [];
    const body = {
      industry: industry,
      orgName: orgName,
      orgType: ($('nt_orgtype')||{}).value || '',
      cycle: ($('nt_cycle')||{}).value || '2026Q4',
      stage: ($('nt_stage')||{}).value || '季度自查',
      topic: ($('nt_topic')||{}).value || '数据安全专项',
      docFocus: ($('nt_doc')||{}).value || '',
      startDate: ($('nt_start')||{}).value || '',
      endDate: ($('nt_end')||{}).value || '',
      scope: { lines: scopeLines },
      owner: ($('nt_owner')||{}).value || (S.session && S.session.account),
      assignees: assignees
    };
    setBtnBusy(btn, true, '创建中…');
    const res = await DZ.post(API.tasks, body);
    setBtnBusy(btn, false);
    if (res && res.error){
      if (msg) msg.textContent = res.error.message || '创建失败';
      DZ.toast(res.error.message || '创建失败', 'bad');
      return;
    }
    S.createdTaskId = res && res.taskId ? res.taskId : null;
    S.filterIndustry = ''; S.filterCycle = ''; S.filterLine = ''; S.keyword = '';
    DZ.toast('任务已创建，可前往「执行自查」查看', 'ok');
    renderPane();
    loadTasks().then(function(){ if (S.tab === 'run') renderPane(); });
  }

  // ---- 检查项保存 ----
  function itemCardOf(code){
    const cards = document.querySelectorAll('#dsc_root [data-item]');
    for (let i=0;i<cards.length;i++){ if (cards[i].getAttribute('data-item') === code) return cards[i]; }
    return null;
  }
  async function onSaveItem(code, btn){
    const card = itemCardOf(code);
    if (!card) return;
    const q = f => card.querySelector('[data-f="'+f+'"]');
    const evidence = (q('evidence').value || '').split('\n').map(x=>x.trim()).filter(Boolean).map(n => ({ name: n, status: 'provided' }));
    const body = {
      checkCode: code,
      lineCode: card.getAttribute('data-line') || '',
      status: card.getAttribute('data-status') || 'supplement',
      applicability: q('applicability').value,
      hasPolicy: q('hasPolicy').checked,
      evidence: evidence,
      actualValue: q('actualValue').value,
      note: q('note').value,
      actor: (S.session && S.session.account) || ''
    };
    setBtnBusy(btn, true, '保存中…');
    const res = await DZ.post(API.items(S.selTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){ DZ.toast(res.error.message || '保存失败', 'bad'); return; }
    DZ.toast('已保存检查项 ' + code, 'ok');
    await loadTaskBundle(S.selTaskId);
    renderSub();
  }

  // ---- AI 佐证匹配 ----
  async function onAiMatch(code, btn){
    setBtnBusy(btn, true, '匹配中…');
    const res = await DZ.post(API.aiMatch(S.selTaskId, code), {});
    setBtnBusy(btn, false);
    const out = document.querySelector('#dsc_root [data-aio="' + code + '"]');
    if (!out) return;
    if (res && res.error){
      out.innerHTML = DZ.banner('bad', res.error.message || '佐证匹配失败', function(){ onAiMatch(code, btn); });
      return;
    }
    out.innerHTML = renderAiResult(res);
  }

  // ---- 责任分配 ----
  async function onPreviewAssign(btn){
    setBtnBusy(btn, true, '计算中…');
    const body = {
      stage: S.detail && S.detail.stage,
      topic: S.detail && S.detail.topic,
      scope: (S.detail && S.detail.scope) || {}
    };
    const res = await DZ.post(API.assignPreview(S.selTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){ DZ.toast(res.error.message || '预览失败', 'bad'); return; }
    S.assignPreview = res;
    renderSub();
  }
  async function onDispatchAssign(btn){
    const msg = $('as_msg');
    setBtnBusy(btn, true, '下发中…');
    const res = await DZ.post(API.assignDispatch(S.selTaskId),
      { confirmedBy: (S.session && S.session.account) || '' });
    setBtnBusy(btn, false);
    if (res && res.error){
      if (msg) msg.textContent = res.error.message || '下发失败';
      DZ.toast(res.error.message || '下发失败', 'bad');
      return;
    }
    DZ.toast('责任分配已下发', 'ok');
    S.assignPreview = null;
    const a = await DZ.get(API.assignments(S.selTaskId));
    S.assignments = (a && !a.error) ? a : S.assignments;
    renderSub();
  }
  async function ensureDicts(){
    if (!S.positions){
      const p = await DZ.get(API.orgPositions);
      S.positions = (p && !p.error) ? (p.positions || []) : [];
    }
    if (!S.nodes){
      const n = await DZ.get(API.orgNodes);
      if (n && !n.error && n.tree){
        const flat = [];
        (function walk(list){ (list||[]).forEach(x => { flat.push({ id:x.node_id, name:x.name, level:x.level }); walk(x.children); }); })(n.tree);
        S.nodes = flat;
      } else S.nodes = [];
    }
  }
  async function onOverrideOpen(code){
    const area = $('#as_override_area');
    if (!area) return;
    area.innerHTML = '<div class="card">' + DZ.skeleton(3) + '</div>';
    await ensureDicts();
    const deptOpts = (S.nodes||[]).map(n => '<option value="'+attr(n.id)+'">'+attr(n.name)+'</option>').join('');
    const posOpts = (S.positions||[]).map(p => '<option value="'+attr(p.positionId)+'">'+attr(p.name)+' · '+attr(p.orgNodeName||'')+'</option>').join('');
    area.innerHTML =
      '<div class="card" data-ov="'+attr(code)+'">' +
        '<h4>人工覆盖责任 · 检查项 <span class="dz-tag-soft">'+attr(code)+'</span></h4>' +
        '<div class="grid2">' +
          '<div><label>目标部门</label><select id="ov_dept" title="目标部门">'+(deptOpts||'<option value="">—</option>')+'</select></div>' +
          '<div><label>目标岗位</label><select id="ov_pos" title="目标岗位">'+(posOpts||'<option value="">—</option>')+'</select></div>' +
        '</div>' +
        '<label>覆盖原因 *</label><input id="ov_reason" placeholder="如 该条线归口部门调整">' +
        '<div class="row" style="margin-top:8px">' +
          '<button data-act="override-submit" data-code="'+attr(code)+'" title="提交覆盖">提交覆盖</button>' +
          '<button class="ghost" data-act="override-cancel" title="取消">取消</button>' +
          '<span id="ov_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
  }
  async function onOverrideSubmit(code, btn){
    const msg = $('ov_msg');
    const reason = ($('ov_reason')||{}).value || '';
    if (!reason.trim()){ if (msg) msg.textContent = '请填写覆盖原因'; DZ.toast('覆盖原因为必填', 'warn'); return; }
    const body = {
      targetDeptId: ($('ov_dept')||{}).value || null,
      targetPositionId: ($('ov_pos')||{}).value || null,
      reason: reason,
      actor: (S.session && S.session.account) || ''
    };
    setBtnBusy(btn, true, '提交中…');
    const res = await DZ.patch(API.assignOverride(S.selTaskId, code), body);
    setBtnBusy(btn, false);
    if (res && res.error){
      const a = $('#as_override_area');
      if (a) a.innerHTML = DZ.banner('bad', res.error.message || '覆盖失败：需先下发分配批次', function(){ onOverrideSubmit(code, btn); });
      DZ.toast(res.error.message || '覆盖失败', 'bad');
      return;
    }
    DZ.toast('已覆盖检查项 ' + code, 'ok');
    const a = await DZ.get(API.assignments(S.selTaskId));
    S.assignments = (a && !a.error) ? a : S.assignments;
    renderSub();
  }

  // ---- 证据登记 ----
  async function onAddEvidence(btn){
    const msg = $('ev_msg');
    const name = (($('ev_name')||{}).value || '').trim();
    if (!name){ if (msg) msg.textContent = '请填写文件名'; DZ.toast('文件名为必填', 'warn'); return; }
    const body = {
      checkCode: ($('ev_code')||{}).value || null,
      fileName: name,
      size: Number(($('ev_size')||{}).value || 0) || 0,
      contentHash: (($('ev_hash')||{}).value || '').trim() || undefined,
      uploadedBy: ($('ev_by')||{}).value || (S.session && S.session.account)
    };
    setBtnBusy(btn, true, '登记中…');
    const res = await DZ.post(API.evidence(S.selTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){
      if (msg) msg.textContent = res.error.message || '登记失败';
      DZ.toast(res.error.message || '登记失败', 'bad');
      return;
    }
    DZ.toast('证据已登记', 'ok');
    await loadEvidence(S.selTaskId);
    renderSub();
  }

  // ---- 签署 ----
  async function onSignoff(btn){
    const msg = $('so_msg');
    const body = {
      account: ($('so_account')||{}).value || (S.session && S.session.account),
      role: ($('so_role')||{}).value || '',
      decision: ($('so_decision')||{}).value || 'approve',
      comment: (($('so_comment')||{}).value || '').trim()
    };
    setBtnBusy(btn, true, '签署中…');
    const res = await DZ.post(API.signoff(S.selTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){
      const isSeparation = res.error.code === 'FORBIDDEN';
      if (msg){
        msg.innerHTML = DZ.banner('bad',
          (res.error.message || '职责分离校验不通过：经办与复核不得为同一账号') +
          (isSeparation ? ' 请在签署账号处切换到非提交人账号后重试。' : ''));
      }
      DZ.toast(isSeparation ? '职责分离校验不通过，请更换签署账号' : (res.error.message || '签署失败'), 'bad');
      return;
    }
    DZ.toast('签署成功', 'ok');
    await loadSignoff(S.selTaskId);
    renderSub();
  }

  // ---- 复查复检 ----
  async function onOpenRecheck(id){
    if (!id) return;
    S.reTaskId = id; S.reFindings = null; S.reItems = []; S.reDiff = null;
    S.reDiffError = ''; S.reError = ''; S.reForm = null;
    renderPane();
    await loadRecheckBundle(id);
    if (S.reTaskId !== id) return;
    renderPane();
  }
  async function loadRecheckBundle(id){
    const [f, it, d] = await Promise.all([
      DZ.get(API.findings(id)), DZ.get(API.items(id)), DZ.get(API.recheckDiff(id))
    ]);
    S.reFindings = (f && !f.error) ? (f.findings || []) : [];
    S.reError = (f && f.error) ? (f.error.message || '问题清单加载失败') : '';
    S.reItems = (it && !it.error) ? (it.items || []) : [];
    S.reDiff = (d && !d.error) ? d : null;
    S.reDiffError = (d && d.error) ? (d.error.message || '') : '';
  }
  function onReBack(){
    S.reTaskId = null; S.reFindings = null; S.reDiff = null;
    S.reDiffError = ''; S.reError = ''; S.reForm = null;
    renderPane();
  }
  async function onRunRecheck(btn){
    if (!S.reTaskId) return;
    setBtnBusy(btn, true, '复检中…');
    const res = await DZ.post(API.recheck(S.reTaskId), {});
    setBtnBusy(btn, false);
    if (res && res.error){ DZ.toast(res.error.message || '复检失败', 'bad'); return; }
    DZ.toast('复检已完成，正在刷新差异比对', 'ok');
    const d = await DZ.get(API.recheckDiff(S.reTaskId));
    S.reDiff = (d && !d.error) ? d : null;
    S.reDiffError = (d && d.error) ? (d.error.message || '') : '';
    renderPane();
  }
  async function onSubmitFinding(btn){
    const msg = $('re_msg');
    const code = ($('nf_code')||{}).value || '';
    const problem = (($('nf_problem')||{}).value || '').trim();
    if (!code || !problem){ if (msg) msg.textContent = '检查项与问题描述为必填'; DZ.toast('请填写检查项与问题描述', 'warn'); return; }
    const body = {
      checkCode: code,
      severity: ($('nf_sev')||{}).value || 'medium',
      problem: problem,
      rootCause: (($('nf_root')||{}).value || '').trim() || null,
      owner: ($('nf_owner')||{}).value || (S.session && S.session.account),
      dueDate: ($('nf_due')||{}).value || null,
      actor: (S.session && S.session.account) || ''
    };
    setBtnBusy(btn, true, '登记中…');
    const res = await DZ.post(API.findings(S.reTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '登记失败'; DZ.toast(res.error.message || '登记失败', 'bad'); return; }
    DZ.toast('问题已登记', 'ok');
    S.reForm = null;
    await loadRecheckBundle(S.reTaskId);
    renderPane();
  }
  async function onSubmitRemediation(btn){
    const msg = $('re_msg');
    const fid = S.reForm && S.reForm.fid;
    const measures = (($('nr_measures')||{}).value || '').trim();
    if (!fid || !measures){ if (msg) msg.textContent = '整改措施为必填'; DZ.toast('请填写整改措施', 'warn'); return; }
    const body = {
      findingId: fid,
      owner: ($('nr_owner')||{}).value || (S.session && S.session.account),
      dueDate: ($('nr_due')||{}).value || null,
      measures: measures,
      actor: (S.session && S.session.account) || ''
    };
    setBtnBusy(btn, true, '创建中…');
    const res = await DZ.post(API.remediations(S.reTaskId), body);
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '创建失败'; DZ.toast(res.error.message || '创建失败', 'bad'); return; }
    DZ.toast('整改任务已创建', 'ok');
    S.reForm = null;
    await loadRecheckBundle(S.reTaskId);
    renderPane();
  }
  async function onSubmitRemediationUpdate(btn){
    const msg = $('re_msg');
    const rid = btn.getAttribute('data-rid') || (S.reForm && S.reForm.rid);
    if (!rid) return;
    const body = {
      status: ($('nr_status')||{}).value || '',
      evidenceRef: (($('nr_ev')||{}).value || '').trim() || null,
      actor: (S.session && S.session.account) || ''
    };
    setBtnBusy(btn, true, '保存中…');
    const res = await DZ.patch(API.remediation(rid), body);
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '保存失败'; DZ.toast(res.error.message || '保存失败', 'bad'); return; }
    DZ.toast('整改任务已更新', 'ok');
    S.reForm = null;
    await loadRecheckBundle(S.reTaskId);
    renderPane();
  }

  // ---- 历史审计 ----
  async function onOpenHistory(id){
    if (!id) return;
    S.histTaskId = id; S.histReport = null; S.histError = '';
    renderPane();
    await loadHistoryBundle(id);
    if (S.histTaskId !== id) return;
    renderPane();
  }
  async function loadHistoryBundle(id){
    const res = await DZ.get(API.report(id));
    if (res && res.error){ S.histError = res.error.message || '报告加载失败'; S.histReport = null; return; }
    S.histReport = res;
  }
  function onHistBack(){
    S.histTaskId = null; S.histReport = null; S.histError = '';
    renderPane();
  }
  async function reloadHistory(){
    if (!S.histTaskId) return;
    const box = $('#dsc_pane');
    if (box) box.innerHTML = DZ.skeleton(6);
    await loadHistoryBundle(S.histTaskId);
    renderPane();
  }
  function onExportReport(id){
    if (!id) return;
    window.open(API.reportMd(id), '_blank');
  }

  // =====================================================================
  // 注册视图
  // =====================================================================
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['dsc'] = function(){ init(); };
})();
