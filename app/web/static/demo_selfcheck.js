/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   视图：安全自查（id=dsc，容器 #dsc_root）
   信息架构：
     顶层三个 Tab —— 自查任务清单与历史 / 新建自查任务 / 新建自查行业档案；
     任务详情内再分子页签 —— 检查项明细 / 任务级判定 / 责任分配 / 证据与签署。
     切换 Tab 只渲染当前内容，未激活内容不渲染。
   能力保留：行业档案与清单 / 任务列表与层级可见 / 任务详情与检查项 /
            AI 佐证匹配 / 任务级判定 / 责任分配 / 证据与签署。
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
    orgPositions: '/api/admin/org-positions',
    orgNodes:     '/api/admin/org-nodes'
  };

  // ---------- 顶层 Tab 与详情子页签 ----------
  const TABS = [
    { key:'tasks',   label:'自查任务清单与历史' },
    { key:'create',  label:'新建自查任务' },
    { key:'profile', label:'新建自查行业档案' }
  ];
  const SUB_TABS = [
    { key:'items',    label:'检查项明细' },
    { key:'verdict',  label:'任务级判定' },
    { key:'assign',   label:'责任分配' },
    { key:'evidence', label:'证据与签署' }
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
  const STATUS_FILTERS = [['', '全部'], ['draft', '草稿'], ['in_progress', '进行中'], ['closed', '已关闭']];

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
    filterStatus:'',
    filterCycle:'',
    filterLine:'',
    keyword:'',
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
    tab:'tasks',
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

  // =====================================================================
  // 入口
  // =====================================================================
  function init(){
    if (!rootEl()) return;
    renderShell();
    renderTabs();
    renderPane();
    Promise.all([loadSession(), loadAccounts(), loadRoles(), loadIndustries(), loadTasks()])
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
  function renderPane(){
    const box = $('#dsc_pane');
    if (!box) return;
    box.className = 'dz-pane';
    if (S.tab === 'create') renderCreatePane(box);
    else if (S.tab === 'profile') renderProfilePane(box);
    else renderTasksPane(box);
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
  async function loadTasks(){
    const list = $('#dsc_tasklist');
    if (list) list.innerHTML = DZ.skeleton(4);
    const qs = [];
    if (S.session && S.session.account) qs.push('account=' + encodeURIComponent(S.session.account));
    if (S.filterIndustry) qs.push('industry=' + encodeURIComponent(S.filterIndustry));
    if (S.filterStatus) qs.push('status=' + encodeURIComponent(S.filterStatus));
    const res = await DZ.get(API.tasks + (qs.length ? '?' + qs.join('&') : ''));
    if (res && res.error){
      if (list) list.innerHTML = DZ.banner('bad', res.error.message || '任务列表加载失败', loadTasks);
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
  // Tab 1：自查任务清单与历史
  // =====================================================================
  function renderTasksPane(box){
    const indOpts = '<option value="">全部行业</option>' + (S.industries||[]).map(function(p){
      return '<option value="'+attr(p.industry)+'"'+(S.filterIndustry===p.industry?' selected':'')+'>'+attr(p.name)+'</option>';
    }).join('');
    const lineSel = '<select data-act="filter-line" title="按条线筛选">' +
      '<option value="">全部条线</option>' + lineOptions().map(function(l){
        return '<option value="'+attr(l.code)+'"'+(S.filterLine===l.code?' selected':'')+'>'+attr(l.label)+'</option>';
      }).join('') + '</select>';
    const stChips = STATUS_FILTERS.map(function(x){
      return '<button type="button" class="dz-chip'+(S.filterStatus===x[0]?' on':'')+'" data-act="filter-status" ' +
        'data-status="'+x[0]+'" title="筛选状态：'+x[1]+'">'+x[1]+'</button>';
    }).join('');

    box.innerHTML =
      '<div class="card">' +
        '<div class="dz-toolbar">' +
          '<select data-act="filter-industry" title="按行业筛选">' + indOpts + '</select>' +
          lineSel +
          '<select data-act="filter-cycle" title="按周期筛选">' + cycleOptions() + '</select>' +
          '<input id="dsc_kw" data-act="filter-kw" value="'+attr(S.keyword)+'" title="关键词检索" ' +
            'placeholder="检索机构 / 主题 / 阶段 / 负责人">' +
          '<button class="ghost" data-act="query-tasks" title="重新查询任务列表">查询</button>' +
        '</div>' +
        '<div class="dz-chipbar">' + stChips + '</div>' +
      '</div>' +
      '<div class="dz-split">' +
        '<div class="dz-side"><div class="dz-sticky"><div class="card">' +
          '<h3>任务列表与历史</h3>' +
          '<div id="dsc_taskcount" class="muted"></div>' +
          '<div id="dsc_tasklist" style="max-height:56vh;overflow:auto"></div>' +
          '<div class="row" style="margin-top:10px">' +
            '<button data-act="goto-create" title="新建自查任务">新建自查任务</button>' +
          '</div>' +
        '</div></div></div>' +
        '<div class="dz-main" id="dsc_detail"></div>' +
      '</div>';
    renderTaskList();
    renderDetail();
  }

  function visibleTasks(){
    const kw = (S.keyword || '').trim().toLowerCase();
    return (S.tasks||[]).filter(function(t){
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

  function renderTaskList(){
    const list = $('#dsc_tasklist');
    if (!list) return;
    const rows = visibleTasks();
    const count = $('#dsc_taskcount');
    if (count) count.textContent = '共 ' + rows.length + ' 个任务';
    if (!rows.length){
      list.innerHTML = DZ.empty('当前筛选条件下暂无自查任务',
        '<button data-act="goto-create" title="新建自查任务">新建自查任务</button>');
      return;
    }
    list.innerHTML = rows.map(function(t){
      const on = t.taskId === S.selTaskId;
      return '<div class="pick" data-act="open-task" data-id="'+attr(t.taskId)+'" role="button" tabindex="0" ' +
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

  function renderDetail(){
    const box = $('#dsc_detail');
    if (!box) return;
    if (!S.selTaskId){ box.innerHTML = DZ.empty('请从左侧选择一条自查任务查看明细'); return; }
    if (S.detailError){
      box.innerHTML = DZ.banner('bad', '任务明细加载失败：' + S.detailError, function(){ reloadDetail(); });
      return;
    }
    if (!S.detail){ box.innerHTML = DZ.skeleton(6); return; }
    box.innerHTML = '<div id="dsc_subtabs"></div><div id="dsc_subpane" class="dz-pane"></div>';
    renderSubtabs();
    renderSub();
  }

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
        '<div class="dz-kpi-row">' +
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
  // Tab 2：新建自查任务
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
        ? DZ.banner('ok', '任务已创建，可前往任务清单查看') +
          '<div class="row" style="margin-bottom:12px"><button data-act="goto-tasks" title="前往任务清单">前往任务清单</button></div>'
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
          '<button class="ghost" data-act="goto-tasks" title="返回任务清单">返回任务清单</button>' +
          '<span id="nt_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
  }

  // =====================================================================
  // Tab 3：新建自查行业档案
  // 主功能＝创建行业档案；下方为现有档案清单（只读参考）与所选档案的行业化清单。
  // =====================================================================
  function renderProfilePane(box){
    box.innerHTML = industryCreateCard() + industryListCard() + industryDetailCard();
  }

  // 3.1 新建表单
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

  // 3.2 现有档案清单（只读参考 + 切换查看清单）
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

  // 3.3 所选档案详情 + 行业化自查清单
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
        '<label>条线</label>' +
        '<div class="dz-chipbar">' + chips + '</div>' +
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
      if (act === 'sel-line') onSelLine(t.getAttribute('data-line'));
      else if (act === 'create-industry-profile') onCreateIndustryProfile(t);
      else if (act === 'pick-profile') onPickProfile(t.getAttribute('data-industry'));
      else if (act === 'open-task') onOpenTask(t.getAttribute('data-id'));
      else if (act === 'goto-create'){ S.tab = 'create'; renderTabs(); renderPane(); }
      else if (act === 'goto-tasks') onGotoTasks();
      else if (act === 'query-tasks') onQueryTasks(t);
      else if (act === 'filter-status') onFilterStatus(t.getAttribute('data-status'));
      else if (act === 'create-task') onCreateTask(t);
      else if (act === 'save-item') onSaveItem(t.getAttribute('data-code'), t);
      else if (act === 'ai-match') onAiMatch(t.getAttribute('data-code'), t);
      else if (act === 'reload-items') reloadDetail();
      else if (act === 'reload-templates') onReloadTemplates(t);
      else if (act === 'reload-industries') onReloadIndustries(t);
      else if (act === 'preview-assign') onPreviewAssign(t);
      else if (act === 'dispatch-assign') onDispatchAssign(t);
      else if (act === 'override-open') onOverrideOpen(t.getAttribute('data-code'));
      else if (act === 'override-submit') onOverrideSubmit(t.getAttribute('data-code'), t);
      else if (act === 'override-cancel'){ const a = $('#as_override_area'); if (a) a.innerHTML = ''; }
      else if (act === 'add-evidence') onAddEvidence(t);
      else if (act === 'signoff') onSignoff(t);
    });

    // 键盘可达：任务卡 Enter / Space 打开
    r.addEventListener('keydown', function(e){
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const t = e.target.closest('[data-act="open-task"]');
      if (t){ e.preventDefault(); onOpenTask(t.getAttribute('data-id')); }
    });

    // 下拉 / 输入变化
    r.addEventListener('change', function(e){
      const t = e.target.closest('[data-act]');
      if (!t) return;
      const act = t.getAttribute('data-act');
      if (act === 'filter-industry'){ S.filterIndustry = t.value; loadTasks().then(function(){ if (S.tab === 'tasks') renderPane(); }); }
      else if (act === 'filter-cycle'){ S.filterCycle = t.value; renderTaskList(); }
      else if (act === 'filter-line') onFilterLine(t.value);
      else if (act === 'filter-kw'){ S.keyword = t.value; renderTaskList(); }
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
  function onFilterStatus(st){
    S.filterStatus = st || '';
    loadTasks().then(function(){ if (S.tab === 'tasks') renderPane(); });
  }
  function onQueryTasks(btn){
    setBtnBusy(btn, true, '查询中…');
    loadTasks().then(function(){
      setBtnBusy(btn, false);
      if (S.tab === 'tasks') renderPane();
    });
  }
  function onFilterLine(code){
    S.filterLine = code || '';
    if (!S.filterLine){ renderTaskList(); return; }
    const list = $('#dsc_tasklist');
    if (list) list.innerHTML = DZ.skeleton(4);
    ensureScopes().then(function(){ if (S.tab === 'tasks') renderTaskList(); });
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
    }).then(function(){ setBtnBusy(btn, false); if (S.tab === 'profile') renderPane(); });
  }
  function onGotoTasks(){
    const id = S.createdTaskId;
    S.tab = 'tasks';
    renderTabs();
    renderPane();
    if (id){
      S.createdTaskId = null;
      onOpenTask(id);
    }
  }
  async function onOpenTask(id){
    if (!id) return;
    S.selTaskId = id; S.sub = 'items';
    renderTaskList();
    renderDetail();
    await loadTaskBundle(id);
    if (S.selTaskId !== id) return;
    renderDetail();
  }
  async function reloadDetail(){
    if (!S.selTaskId) return;
    DZ.render('#dsc_detail', DZ.skeleton(6));
    await loadTaskBundle(S.selTaskId);
    renderDetail();
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
    S.filterIndustry = ''; S.filterStatus = ''; S.filterCycle = ''; S.filterLine = ''; S.keyword = '';
    DZ.toast('任务已创建，可前往任务清单查看', 'ok');
    renderPane();
    loadTasks();
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

  // =====================================================================
  // 注册视图
  // =====================================================================
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['dsc'] = function(){ init(); };
})();
