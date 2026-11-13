/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   视图：安全自查（id=dsc，容器 #dsc_root）
   覆盖：A1 行业档案与清单 / A2 任务列表与层级可见 / A2·A3 任务详情与单项 /
        AI 佐证匹配 / A3 任务级判定 / G3.7 责任分配 / G3.5 证据与签署（含职责分离）
   约定：仅使用 window.DZ.* 与 dz- 前缀样式；不引入任何外部库。
   ============================================================ */
(function(){
  'use strict';

  // ---------- 模块状态（视图可重入，状态常驻） ----------
  const S = {
    session: null,          // /api/auth/session
    accounts: [],           // /api/admin/users
    industries: [],         // /api/selfcheck/industries
    selIndustry: 'bank',    // 当前行业（A1）
    selLine: '',            // 当前条线（A1，空=全部）
    templatesEnv: null,     // /api/selfcheck/templates 信封
    tasks: [],              // 任务列表
    visibleAccount: '',
    filterIndustry: '',
    filterStatus: '',
    selTaskId: null,        // 当前选中任务
    detail: null,           // 任务详情
    detailError: '',        // 任务详情取数失败信息（非空则主区展示错误态+重试）
    items: [],              // 单项列表
    verdict: null,          // 任务级判定
    assignments: null,      // 责任分配（当前 + 历史）
    assignPreview: null,    // 分配预览结果
    evidence: [],           // 证据列表
    signoff: null,          // 签署记录（含 submitterAccount）
    positions: null,        // 岗位字典（覆盖用）
    nodes: null,            // 机构字典（覆盖用）
    tab: 'profile'          // 主区当前页签
  };

  const APPLICABILITY = [
    {v:'applicable', t:'适用'},
    {v:'not_applicable', t:'不适用'},
    {v:'conditional', t:'条件适用'}
  ];
  // 后端 sixDim 真实字段（勿臆造）
  const SIXDIM = [
    ['elements', '要素'], ['metrics', '度量'], ['evidence', '证据'],
    ['method', '方法'], ['interview', '访谈'], ['related', '关联']
  ];
  const DOC_LABEL = {
    jg24: '金规〔2024〕24号', jg93: '金办发〔2025〕93号',
    pboc3: '人行令〔2025〕第3号', jf8: '金发〔2026〕8号',
    jf26: '金发〔2026〕26号', pboc8: '人行令〔2026〕第8号'
  };

  const attr = s => DZ.esc(s);
  const rootEl = () => document.getElementById('dsc_root');
  // 兼容 '#id' 与 'id' 两种写法
  const $ = id => document.getElementById(String(id).replace(/^#/, ''));

  // ---------- 小工具 ----------
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
    // 回退：从行业档案里查
    const p = S.industries.filter(x => x.industry === S.selIndustry)[0];
    if (p && Array.isArray(p.lines)){
      const l = p.lines.filter(x => x.code === code)[0];
      if (l) return l.label || code;
    }
    return code || '—';
  }
  function sixDimCompleteness(sixDim){
    let covered = 0;
    SIXDIM.forEach(d => { if (Number((sixDim||{})[d[0]]) > 0) covered++; });
    return { covered: covered, total: SIXDIM.length, pct: Math.round(covered / SIXDIM.length * 100) };
  }
  function scopeText(){
    const s = S.session;
    if (!s || !s.org) return '全部数据（未绑定机构，可见全量任务）';
    const lv = s.org.level;
    const map = {L0:'本级及全辖', L1:'辖内（本级及下级）', L2:'本级及下级', L3:'本级（网点）'};
    return lv + ' ' + s.org.name + ' · ' + (map[lv] || '本级');
  }
  function industryLabel(code){
    const p = S.industries.filter(x => x.industry === code)[0];
    return p ? p.name : (code === 'bank' ? '银行业' : code === 'insurance' ? '保险业' : code);
  }
  // 后端 orgTypes 可能返回数组或 {"orgTypes":[...]}，统一取数组
  function orgTypesOf(p){
    const o = p && p.orgTypes;
    if (Array.isArray(o)) return o;
    if (o && Array.isArray(o.orgTypes)) return o.orgTypes;
    return [];
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
    const r = rootEl();
    if (!r) return;
    renderShell();
    // 会话/账号/行业 先并行拉取，随后任务与清单模板
    Promise.all([loadSession(), loadAccounts(), loadIndustries()])
      .then(() => { renderSession(); renderIndustryLeft(); return Promise.all([loadTasks(), refreshTemplates()]); })
      .then(() => { renderTasksCard(); renderMain(); })
      .catch((e) => {
        DZ.toast('初始化数据加载失败，请重试或刷新页面', 'bad');
        DZ.render('#dsc_main', DZ.banner('bad', '初始化失败：' + ((e && e.message) || '未知错误'),
          function () { init(); }));
      });
  }

  // ---------- 骨架外壳 ----------
  function renderShell(){
    const r = rootEl();
    r.innerHTML =
      '<div class="dz-split">' +
        '<div class="dz-side">' +
          '<div class="dz-sticky">' +
            '<div id="dsc_session"></div>' +
            '<div id="dsc_industry"></div>' +
            '<div id="dsc_tasks"></div>' +
          '</div>' +
        '</div>' +
        '<div class="dz-main">' +
          '<div id="dsc_tabs"></div>' +
          '<div id="dsc_main"></div>' +
        '</div>' +
      '</div>';
    // 默认骨架
    DZ.render('#dsc_session', DZ.skeleton(2));
    DZ.render('#dsc_industry', DZ.skeleton(3));
    DZ.render('#dsc_tasks', DZ.skeleton(4));
    DZ.render('#dsc_main', DZ.skeleton(5));
    bindDelegation();
  }

  // =====================================================================
  // 取数
  // =====================================================================
  async function loadSession(){
    const res = await DZ.get('/api/auth/session');
    if (res && !res.error) S.session = res;
  }
  async function loadAccounts(){
    const res = await DZ.get('/api/admin/users');
    if (res && !res.error) S.accounts = res.users || [];
  }
  async function loadIndustries(){
    const res = await DZ.get('/api/selfcheck/industries');
    if (res && !res.error) S.industries = res.industries || [];
    if (S.industries.length && !S.industries.some(x => x.industry === S.selIndustry))
      S.selIndustry = S.industries[0].industry;
  }
  async function loadTasks(){
    const r = rootEl();
    if (r) DZ.render('#dsc_tasks', DZ.skeleton(4));
    const qs = [];
    if (S.session && S.session.account) qs.push('account=' + encodeURIComponent(S.session.account));
    if (S.filterIndustry) qs.push('industry=' + encodeURIComponent(S.filterIndustry));
    if (S.filterStatus) qs.push('status=' + encodeURIComponent(S.filterStatus));
    const res = await DZ.get('/api/selfcheck/tasks' + (qs.length ? '?' + qs.join('&') : ''));
    if (res && res.error){
      DZ.render('#dsc_tasks', DZ.banner('bad', res.error.message || '任务列表加载失败', loadTasks));
      return;
    }
    S.tasks = (res && res.tasks) || [];
    S.visibleAccount = (res && res.visibleAccount) || '';
  }
  async function refreshTemplates(){
    S.templatesEnv = null;
    if (S.tab === 'profile') renderTab();
    const res = await DZ.get('/api/selfcheck/templates?industry=' + encodeURIComponent(S.selIndustry) +
                             '&line=' + encodeURIComponent(S.selLine || ''));
    S.templatesEnv = res;
    if (S.tab === 'profile') renderTab();
  }
  async function loadTaskBundle(taskId){
    S.detail = S.items = S.verdict = S.assignments = S.evidence = S.signoff = S.assignPreview = null;
    S.selTaskId = taskId;
    S.detailError = '';
    const base = '/api/selfcheck/tasks/' + encodeURIComponent(taskId);
    const [detail, items, verdict, assignments] = await Promise.all([
      DZ.get(base), DZ.get(base + '/items'), DZ.get(base + '/verdict'), DZ.get(base + '/assignments')
    ]);
    if (!detail || detail.error){
      S.detailError = (detail && detail.error && detail.error.message) || '任务详情加载失败';
      DZ.toast(S.detailError, 'bad');
      return;
    }
    S.detail = detail; S.items = (items && items.items) || [];
    S.verdict = (verdict && !verdict.error) ? verdict : null;
    S.assignments = (assignments && !assignments.error) ? assignments : null;
    await Promise.all([loadEvidence(taskId), loadSignoff(taskId)]);
  }
  async function loadEvidence(taskId){
    const res = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(taskId) + '/evidence');
    S.evidence = (res && !res.error) ? (res.evidence || []) : [];
  }
  async function loadSignoff(taskId){
    const res = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(taskId) + '/signoff');
    S.signoff = (res && !res.error) ? res : { signoffs: [], submitterAccount: null };
  }

  // =====================================================================
  // 左栏：会话 / 账号 / 可见范围
  // =====================================================================
  function renderSession(){
    const s = S.session || {};
    const opts = S.accounts.map(a =>
      '<option value="'+attr(a.account)+'"'+(a.account===s.account?' selected':'')+
      (a.status!=='active'?' disabled':'')+'>'+attr(a.displayName || a.account)+'（'+attr(a.account)+'）'+
      (a.status!=='active'?' · 停用':'')+'</option>').join('');
    DZ.render('#dsc_session',
      '<div class="card">' +
        '<h3>当前身份 · 可见范围</h3>' +
        '<label>演示账号</label>' +
        '<select id="dsc_acct" data-act="switch-account" title="切换演示账号" aria-label="切换演示账号">' + opts + '</select>' +
        '<div class="dz-metric"><span class="dz-metric-k">显示名</span><span class="dz-metric-v">'+attr(s.displayName||'—')+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">角色</span><span class="dz-metric-v">'+((s.roles||[]).map(x=>'<span class="pill">'+attr(x)+'</span>').join(' ')||'—')+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">可见范围</span><span class="dz-metric-v" style="font-weight:500">'+attr(scopeText())+'</span></div>' +
      '</div>');
  }

  // =====================================================================
  // 左栏：行业档案选择 + 条线
  // =====================================================================
  function renderIndustryLeft(){
    const indOpts = S.industries.map(p =>
      '<option value="'+attr(p.industry)+'"'+(p.industry===S.selIndustry?' selected':'')+'>'+attr(p.name)+'</option>').join('');
    const prof = S.industries.filter(p => p.industry === S.selIndustry)[0];
    const lines = (prof && prof.lines) || [];
    const chips = '<button type="button" class="dz-chip'+(S.selLine===''?' on':'')+'" data-act="sel-line" data-line="" title="显示全部条线">全部条线</button>' +
      lines.map(l => '<button type="button" class="dz-chip'+(S.selLine===l.code?' on':'')+'" data-act="sel-line" data-line="'+attr(l.code)+'" title="条线：'+attr(l.label)+'">'+attr(l.label)+'</button>').join('');
    DZ.render('#dsc_industry',
      '<div class="card">' +
        '<h3>行业档案（A1）</h3>' +
        '<label>行业</label>' +
        '<select data-act="sel-industry" title="选择行业档案" aria-label="选择行业档案">'+indOpts+'</select>' +
        '<label>条线</label>' +
        '<div class="dz-chipbar">'+chips+'</div>' +
      '</div>');
  }

  // =====================================================================
  // 左栏：任务列表
  // =====================================================================
  function renderTasksCard(){
    const indSel = '<select data-act="filter-industry" title="按行业筛选">' +
      '<option value="">全部行业</option>' +
      '<option value="bank"'+(S.filterIndustry==='bank'?' selected':'')+'>银行业</option>' +
      '<option value="insurance"'+(S.filterIndustry==='insurance'?' selected':'')+'>保险业</option></select>';
    const stChips = [['','全部'],['draft','草稿'],['in_progress','进行中'],['closed','已关闭']].map(x =>
      '<button type="button" class="dz-chip'+(S.filterStatus===x[0]?' on':'')+'" data-act="filter-status" data-status="'+x[0]+'" title="筛选状态：'+x[1]+'">'+x[1]+'</button>').join('');
    let list;
    if (!S.tasks.length){
      list = DZ.empty('当前可见范围内暂无自查任务', '<button data-act="open-new" title="新建自查任务">新建自查任务</button>');
    } else {
      list = S.tasks.map(t => {
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
    const vis = S.visibleAccount ? '（账号 '+attr(S.visibleAccount)+'）' : '';
    DZ.render('#dsc_tasks',
      '<div class="card">' +
        '<h3>自查任务（A2）</h3>' +
        '<div class="row" style="margin-bottom:8px">' + indSel +
          '<button class="ghost" data-act="refresh-tasks" title="刷新任务列表">刷新</button>' +
          '<button data-act="open-new" title="新建自查任务">新建自查任务</button>' +
        '</div>' +
        '<div class="dz-chipbar">'+stChips+'</div>' +
        '<div class="muted" style="margin-bottom:6px">按账号可见范围过滤'+vis+' · 共 '+S.tasks.length+' 个</div>' +
        '<div style="max-height:46vh;overflow:auto">'+list+'</div>' +
      '</div>');
  }

  // =====================================================================
  // 右栏主区：页签 + 内容
  // =====================================================================
  function tabsItems(){
    const base = [{key:'profile', label:'行业档案与清单'}, {key:'new', label:'新建自查任务'}];
    if (S.selTaskId){
      base.push({key:'items', label:'单项作业'});
      base.push({key:'verdict', label:'任务级判定'});
      base.push({key:'assign', label:'责任分配'});
      base.push({key:'evidence', label:'证据与签署'});
    }
    return base;
  }
  function renderMain(){
    const r = rootEl(); if (!r) return;
    const items = tabsItems();
    if (!items.some(x => x.key === S.tab)) S.tab = 'profile';
    DZ.tabs('#dsc_tabs', items, S.tab, function(k){ S.tab = k; renderTab(); });
    renderTab();
  }
  function renderTab(){
    if (S.detailError && S.tab !== 'new' && S.tab !== 'profile'){
      const box = $('#dsc_main');
      if (box){ box.innerHTML = DZ.banner('bad', '任务详情加载失败：' + S.detailError,
        function(){ reloadItems(); }); }
      return;
    }
    switch (S.tab){
      case 'new': renderNewForm(); break;
      case 'items': renderItemsTab(); break;
      case 'verdict': renderVerdictTab(); break;
      case 'assign': renderAssignTab(); break;
      case 'evidence': renderEvidenceTab(); break;
      default: renderProfileTab();
    }
  }

  // ---- 行业档案与清单（A1） ----
  function renderProfileTab(){
    const box = $('#dsc_main'); if (!box) return;
    const prof = S.industries.filter(p => p.industry === S.selIndustry)[0];
    if (!prof){
      box.innerHTML = S.industries.length ? DZ.skeleton(4)
        : DZ.empty('行业档案加载失败或为空', '<button data-act="reload-industries" title="重新加载行业档案">重新加载</button>');
      return;
    }
    const head =
      '<div class="card">' +
        '<h3>'+attr(prof.name)+'</h3>' +
        '<div class="dz-metric"><span class="dz-metric-k">机构类型</span><span class="dz-metric-v">' +
          (orgTypesOf(prof).map(x=>DZ.pill(x)).join(' ')||'—')+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">敏感数据类型</span><span class="dz-metric-v">' +
          ((prof.sensitiveTypes||[]).map(x=>DZ.pill(x)).join(' ')||'—')+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">文号侧重</span><span class="dz-metric-v">' +
          ((prof.docFocus||[]).map(x=>'<code title="'+attr(x)+'">'+attr(DOC_LABEL[x]||x)+'</code>').join(' ')||'—')+'</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">报告模板</span><span class="dz-metric-v"><code>'+attr(prof.reportTemplate||'—')+'</code></span></div>' +
      '</div>';

    let tplHtml;
    const env = S.templatesEnv;
    if (!env){
      tplHtml = '<div class="card"><h4>行业化自查清单</h4>' + DZ.skeleton(5) + '</div>';
    } else if (env.error){
      tplHtml = '<div class="card">' + DZ.banner('bad', env.error.message || '清单加载失败', refreshTemplates) + '</div>';
    } else if (!env.content){
      tplHtml = '<div class="card">' + DZ.empty('该行业暂无自查清单模板', '<button class="ghost" data-act="reload-templates" title="重新加载">重新加载</button>') + '</div>';
    } else {
      const c = env.content;
      let groups = c.groups || [];
      if (S.selLine) groups = groups.filter(g => g.line === S.selLine);
      const body = groups.length ? groups.map(g => {
        const rows = (g.items||[]).map(it => {
          const cp = sixDimCompleteness(it.sixDim);
          const six = SIXDIM.map(d => '<span class="dz-tag-soft" title="'+d[1]+'">'+d[1]+' ' + DZ.number((it.sixDim||{})[d[0]]||0) + '</span>').join(' ');
          return '<tr>' +
            '<td><code>'+attr(it.checkCode)+'</code></td>' +
            '<td>'+attr(it.title)+'</td>' +
            '<td>'+DZ.badge((it.priority==='P0'?'p0':it.priority==='P2'?'p2':'p1'), it.priority||'P1')+'</td>' +
            '<td>'+attr(it.domain||'—')+'</td>' +
            '<td style="min-width:220px">'+six+'</td>' +
            '<td style="min-width:120px">'+DZ.bar(cp.pct)+'<span class="dz-mini">'+cp.covered+'/'+cp.total+'（'+cp.pct+'%）</span></td>' +
          '</tr>';
        }).join('');
        return '<div class="card">' +
          '<h4>'+attr(g.lineLabel)+' <span class="muted">（'+attr(g.line)+' · '+((g.items||[]).length)+' 项）</span></h4>' +
          '<div class="dz-table-wrap"><table><thead><tr>' +
            '<th>检查项</th><th>标题</th><th>优先级</th><th>领域</th><th>六维摘要（要素/度量/证据/方法/访谈/关联）</th><th>完整度</th>' +
          '</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
      }).join('') : DZ.empty('该条线下暂无清单项', '<button class="ghost" data-act="sel-line" data-line="" title="显示全部条线">显示全部条线</button>');
      tplHtml =
        '<div class="card">' +
          '<h4>行业化自查清单</h4>' +
          '<div class="row" style="justify-content:space-between">' +
            '<span>'+DZ.srcBar(env, 'snapshot '+attr(c.snapshotVersion||'-'))+'</span>' +
            '<span class="muted">生成于 '+DZ.date(c.generatedAt)+' · 主文号 <code>'+attr(DOC_LABEL[c.primaryDoc]||c.primaryDoc||'—')+'</code></span>' +
          '</div>' +
        '</div>' + body;
    }
    box.innerHTML = head + tplHtml;
  }

  // ---- 新建自查任务 ----
  function renderNewForm(){
    const box = $('#dsc_main'); if (!box) return;
    const prof = S.industries.filter(p => p.industry === S.selIndustry)[0] || {orgTypes:[], lines:[]};
    const indOpts = S.industries.map(p => '<option value="'+attr(p.industry)+'"'+(p.industry===S.selIndustry?' selected':'')+'>'+attr(p.name)+'</option>').join('');
    const orgTypeOpts = orgTypesOf(prof).map(x => '<option value="'+attr(x)+'">'+attr(x)+'</option>').join('');
    const linePicks = (prof.lines||[]).map(l =>
      '<label class="pick"><input type="checkbox" data-line-pick value="'+attr(l.code)+'">' +
      '<span class="pick-name">'+attr(l.label)+'</span><span class="pick-meta">'+attr(l.code)+'</span></label>').join('');
    const acctOpts = (extra) => S.accounts.filter(a=>a.status==='active').map(a =>
      '<option value="'+attr(a.account)+'"'+(a.account===(S.session&&S.session.account)?' selected':'')+'>'+attr(a.displayName||a.account)+'（'+attr(a.account)+'）</option>').join('');
    box.innerHTML =
      '<div class="card">' +
        '<h3>新建自查任务</h3>' +
        '<div class="grid2">' +
          '<div><label>行业 *</label><select id="nt_industry" data-act="new-industry" title="选择行业">'+indOpts+'</select></div>' +
          '<div><label>机构名称 *</label><input id="nt_org" placeholder="如 华东分行"></div>' +
          '<div><label>机构类型</label><select id="nt_orgtype" title="机构类型">'+orgTypeOpts+'</select></div>' +
          '<div><label>周期</label><input id="nt_cycle" placeholder="如 2026Q4" value="2026Q4"></div>' +
          '<div><label>阶段</label><input id="nt_stage" placeholder="如 季度自查" value="季度自查"></div>' +
          '<div><label>主题</label><input id="nt_topic" placeholder="如 数据安全专项" value="数据安全专项"></div>' +
          '<div><label>负责人</label><select id="nt_owner" title="负责人">'+acctOpts(true)+'</select></div>' +
          '<div><label>协办（按住 ⌘/Ctrl 多选）</label><select id="nt_assignees" multiple size="3" title="协办人">'+acctOpts(true)+'</select></div>' +
        '</div>' +
        '<label>自查范围（条线）</label>' +
        '<div class="pick-list">'+(linePicks||'<span class="muted">该行业未定义条线</span>')+'</div>' +
        '<div class="row"><button data-act="create-task" title="创建自查任务">创建任务</button>' +
        '<button class="ghost" data-act="cancel-new" title="返回">返回</button>' +
        '<span id="nt_msg" class="muted"></span></div>' +
      '</div>';
  }

  // ---- 任务详情 + 单项作业 ----
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
        '<span class="muted">负责人：'+attr(d.owner||'—')+'</span>' +
        '<span class="muted">协办：'+((d.assignees||[]).join('、')||'—')+'</span>' +
      '</div>' +
      '<div class="row" style="gap:10px;margin-top:8px">' +
        '<span class="muted">进度</span>'+DZ.bar(d.progress)+'<span class="dz-mini">'+DZ.number(d.progress)+'%</span>' +
        '<span class="muted">｜单项 '+DZ.number(d.itemCount||0)+' 项</span>' +
        '<span class="muted">｜判定 '+DZ.resultBadge(v.result)+'</span>' +
        '<span class="muted">｜风险 '+DZ.severityBadge(v.riskLevel||d.riskLevel)+'</span>' +
      '</div>' +
      ((d.sections||[]).length ?
        '<div class="dz-table-wrap" style="margin-top:8px"><table><thead><tr><th>条线</th><th>负责人</th><th>截止</th><th>状态</th><th>进度</th></tr></thead><tbody>' +
        d.sections.map(s => '<tr><td>'+attr(s.lineLabel)+' <span class="muted">('+attr(s.lineCode)+')</span></td>' +
          '<td>'+attr(s.owner||'—')+'</td><td>'+DZ.date(s.dueDate)+'</td><td>'+DZ.statusBadge(s.status)+'</td>' +
          '<td style="min-width:110px">'+DZ.bar(s.progress)+'<span class="dz-mini">'+DZ.number(s.progress)+'%</span></td></tr>').join('') +
        '</tbody></table></div>' : '') +
    '</div>';
  }

  function renderItemsTab(){
    const box = $('#dsc_main'); if (!box) return;
    if (!S.detail){ box.innerHTML = DZ.skeleton(4); return; }
    const head = renderDetailHeader();
    if (!S.items.length){
      box.innerHTML = head + '<div class="card">' + DZ.empty('该任务暂无单项记录', '<button class="ghost" data-act="reload-items" title="重新加载">重新加载</button>') + '</div>';
      return;
    }
    const cards = S.items.map(it => itemCard(it)).join('');
    box.innerHTML = head + '<div class="card"><h4>单项作业（四录入项 · '+S.items.length+' 项）</h4>' +
      '<div class="muted">逐项录入 适用性 / 是否具备制度 / 证据 / 实际值 / 备注，可对单项发起 AI 佐证匹配。</div></div>' + cards;
  }

  function itemCard(it){
    const code = it.checkCode;
    // 注：后端 POST /items 在未回传 lineCode/status 时会读取不存在的列而报错，
    // 故此处将既有 lineCode/status 随表单一并回传（值来自后端真实返回，不伪造）。
    return '<div class="card" data-item="'+attr(code)+'" data-line="'+attr(it.lineCode||'')+'" data-status="'+attr(it.status||'')+'" style="padding:14px 16px">' +
      '<div class="row" style="justify-content:space-between">' +
        '<div class="row" style="gap:8px">' +
          '<code>'+attr(code)+'</code>' + DZ.statusBadge(it.status) +
          '<span class="pill">'+attr(lineLabelOf(it.lineCode))+'</span>' +
        '</div>' +
        '<span class="muted">更新于 '+DZ.date(it.updatedAt)+'</span>' +
      '</div>' +
      '<div class="grid2" style="margin-top:8px">' +
        '<div><label>适用性</label><select data-f="applicability" title="适用性">'+appOptions(it.applicability)+'</select></div>' +
        '<div><label>是否具备制度</label><label class="pick"><input type="checkbox" data-f="hasPolicy" '+(it.hasPolicy?'checked':'')+'>' +
          '<span class="pick-name">已具备对应制度</span></label></div>' +
        '<div><label>实际值</label><input data-f="actualValue" value="'+attr(it.actualValue||'')+'" placeholder="如 覆盖率 85%"></div>' +
        '<div><label>证据（每行一条文件/说明）</label><textarea data-f="evidence" rows="2" placeholder="每行一条">'+attr(evText(it.evidence))+'</textarea></div>' +
      '</div>' +
      '<label>备注</label><textarea data-f="note" rows="2">'+attr(it.note||'')+'</textarea>' +
      '<div class="row" style="margin-top:8px">' +
        '<button data-act="save-item" data-code="'+attr(code)+'" title="保存该单项录入">保存录入项</button>' +
        '<button class="ghost" data-act="ai-match" data-code="'+attr(code)+'" title="调用 AI 佐证匹配">AI 佐证匹配</button>' +
      '</div>' +
      '<div class="dz-aiout" data-aio="'+attr(code)+'"></div>' +
    '</div>';
  }

  function renderAiResult(res){
    const segs = (res.segments||[]).map(s =>
      '<div class="dz-cite"><div>'+attr(s.text)+'</div>' +
      '<div class="dz-cite-src"><span class="badge b-unk">'+attr((DZ.SRC_LABEL||{})[s.source]||s.source||'-')+'</span> ' +
      '命中分 '+DZ.confidence(s.score)+'</div></div>').join('');
    return '<div style="margin-top:8px">' +
      '<div class="row" style="gap:12px">' +
        '<span class="muted">置信度</span>'+DZ.confidence(res.confidence) +
        '<span class="muted">建议判定</span>'+DZ.resultBadge(res.suggestion) +
        (res.routedToHuman ? DZ.badge('warn','已转人工') : DZ.badge('ok','可自动采纳')) +
      '</div>' +
      (res.routedToHuman ? DZ.banner('warn', res.reason || '置信度不足/高风险，已转人工确认') : '') +
      segs + '</div>';
  }

  // ---- 任务级判定（A3） ----
  function renderVerdictTab(){
    const box = $('#dsc_main'); if (!box) return;
    if (!S.detail){ box.innerHTML = DZ.skeleton(4); return; }
    const head = renderDetailHeader();
    const v = S.verdict;
    if (!v){ box.innerHTML = head + '<div class="card">' + DZ.banner('bad', '判定数据加载失败', reloadVerdict) + '</div>'; return; }
    const b = v.basis || {};
    const total = b.total || 0;
    const seg = (label, cnt, resultKey) =>
      '<div class="dz-metric"><span class="dz-metric-k">'+DZ.resultBadge(resultKey)+' '+label+'</span>' +
      '<span class="dz-metric-v">'+DZ.number(cnt||0)+' 项' + (total? '（'+Math.round((cnt||0)/total*100)+'%）':'') + '</span></div>';
    box.innerHTML = head +
      '<div class="card">' +
        '<h3>任务级判定与风险分级</h3>' +
        '<div class="dz-kpi-row">' +
          DZ.kpi('综合判定', (DZ.resultBadge(v.result)).replace(/<[^>]+>/g,''), '按最差项聚合') +
          DZ.kpi('计分（符合率）', DZ.number(v.score,1) + '%', '符合项 / 总项', v.riskLevel==='high'?'bad':(v.riskLevel==='low'?'ok':'warn')) +
          DZ.kpi('风险等级', ({high:'高',medium:'中',low:'低'})[v.riskLevel]||'—', '', v.riskLevel==='high'?'bad':(v.riskLevel==='low'?'ok':'warn')) +
          DZ.kpi('任务状态', DZ.statusBadge(v.taskLevel).replace(/<[^>]+>/g,''), '计算时间 '+DZ.date(v.computedAt)) +
        '</div>' +
        '<div class="row" style="gap:12px">' +
          '<span class="muted">判定结论</span>'+DZ.resultBadge(v.result) +
          '<span class="muted">风险</span>'+DZ.severityBadge(v.riskLevel) +
        '</div>' +
        '<h4>计分依据（四态分布）</h4>' +
        seg('符合', b.pass, 'pass') + seg('部分符合', b.partial, 'partial') +
        seg('不符合', b.fail, 'fail') + seg('需补充', b.supplement, 'supplement') +
        '<div class="dz-metric"><span class="dz-metric-k">合计</span><span class="dz-metric-v">'+DZ.number(total)+' 项</span></div>' +
        '<div class="why">聚合规则：任一「不符合」→ 综合不符合；否则任一「部分符合」→ 部分符合；否则任一「需补充」→ 需补充；全部「符合」→ 符合。风险分级：不符合 ≥ 3 项 → 高风险。</div>' +
      '</div>';
  }

  // ---- 责任分配（G3.7） ----
  function renderAssignTab(){
    const box = $('#dsc_main'); if (!box) return;
    if (!S.detail){ box.innerHTML = DZ.skeleton(4); return; }
    const head = renderDetailHeader();
    const a = S.assignments;
    const cur = a && a.current;
    let curHtml;
    if (!cur){
      curHtml = DZ.empty('该任务暂无已下发批次', '<button data-act="preview-assign" title="按规则预览分配">生成分配预览</button>');
    } else {
      curHtml = '<div class="row" style="gap:12px">' +
        '<span>批次 <code>'+attr(cur.batchId)+'</code></span>' +
        '<span class="muted">规则版本 v'+attr(cur.ruleVersion)+'</span>' +
        '<span class="muted">覆盖率 '+DZ.number(cur.coverage,1)+'%</span>' +
        '<span class="muted">确认人 '+attr(cur.confirmedBy||'—')+'</span>' +
        '<span class="muted">下发于 '+DZ.date(cur.confirmedAt)+'</span></div>';
    }
    const hist = (a && a.history && a.history.length) ? '<h4>批次版本历史</h4>' +
      '<div class="dz-table-wrap"><table><thead><tr><th>批次</th><th>规则版本</th><th>覆盖率</th><th>确认人</th><th>下发时间</th></tr></thead><tbody>' +
      a.history.map(h => '<tr><td><code>'+attr(h.batchId)+'</code></td><td>v'+attr(h.ruleVersion)+'</td><td>'+DZ.number(h.coverage,1)+'%</td><td>'+attr(h.confirmedBy||'—')+'</td><td>'+DZ.date(h.confirmedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : '';

    const curMapping = (a && a.mapping && a.mapping.length) ? mappingTable(a.mapping, false) : '';
    const prev = S.assignPreview;
    let prevHtml = '';
    if (prev){
      const un = (prev.unmatched||[]).length ? (prev.unmatched||[]).map(c=>'<code>'+attr(c)+'</code>').join(' ') : '<span class="muted">无</span>';
      const cf = (prev.conflicts||[]).length ? '<ul style="margin:6px 0 0 18px">'+prev.conflicts.map(c=>'<li><code>'+attr(c.checkCode)+'</code> '+attr(c.reason)+'</li>').join('')+'</ul>' : '<span class="muted">无</span>';
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
          '<button data-act="dispatch-assign" title="确认下发分配">确认下发</button>' +
          '<span id="as_msg" class="muted"></span>' +
        '</div>' +
      '</div>';
    } else {
      prevHtml = '<div class="card"><div class="row">' +
        '<button data-act="preview-assign" title="按规则预览分配">生成分配预览</button>' +
        '<span class="muted">按阶段 / 主题 / 范围与责任规则计算覆盖率与映射</span></div></div>';
    }

    box.innerHTML = head +
      '<div class="card"><h3>责任分配（G3.7）</h3>' + curHtml + hist + '</div>' +
      prevHtml +
      (curMapping ? '<div class="card"><h4>当前映射（含 override）</h4>'+curMapping+'</div>' : '') +
      '<div id="as_override_area"></div>';
  }

  function mappingTable(mapping, allowOverride){
    if (!mapping.length) return DZ.empty('暂无映射');
    const rows = mapping.map(m =>
      '<tr data-map="'+attr(m.checkCode)+'">' +
        '<td><code>'+attr(m.checkCode)+'</code></td>' +
        '<td>'+attr(m.title||'')+'</td>' +
        '<td>'+attr(m.deptName||m.deptId||'—')+'</td>' +
        '<td>'+attr(m.positionName||m.positionId||'—')+'</td>' +
        '<td>'+attr(m.roleId||'—')+'</td>' +
        '<td>'+DZ.badge(m.source==='override'?'warn':'ok', m.source==='override'?'手工覆盖':'规则')+'</td>' +
        (allowOverride ? '<td><button class="ghost" data-act="override-open" data-code="'+attr(m.checkCode)+'" title="手工覆盖该检查项责任">覆盖</button></td>' : '') +
      '</tr>').join('');
    return '<div class="dz-table-wrap"><table><thead><tr><th>检查项</th><th>标题</th><th>部门</th><th>岗位</th><th>角色</th><th>来源</th>' +
      (allowOverride?'<th>操作</th>':'') + '</tr></thead><tbody>'+rows+'</tbody></table></div>';
  }

  // ---- 证据与签署（G3.5） ----
  function renderEvidenceTab(){
    const box = $('#dsc_main'); if (!box) return;
    if (!S.detail){ box.innerHTML = DZ.skeleton(4); return; }
    const head = renderDetailHeader();

    // 证据登记表单
    const codeOpts = S.items.map(it => '<option value="'+attr(it.checkCode)+'">'+attr(it.checkCode)+' · '+attr(lineLabelOf(it.lineCode))+'</option>').join('');
    const acctOpts = S.accounts.filter(a=>a.status==='active').map(a =>
      '<option value="'+attr(a.account)+'"'+(a.account===(S.session&&S.session.account)?' selected':'')+'>'+attr(a.displayName||a.account)+'（'+attr(a.account)+'）</option>').join('');
    const evRows = S.evidence.length ? '<div class="dz-table-wrap"><table><thead><tr><th>检查项</th><th>文件</th><th>大小</th><th>哈希</th><th>上传人</th><th>时间</th></tr></thead><tbody>' +
      S.evidence.map(e => '<tr><td><code>'+attr(e.checkCode||'—')+'</code></td>' +
        '<td><span class="dz-file-name">'+attr(e.fileName)+'</span><div class="dz-file-meta">'+attr(e.storageRef||'')+'</div></td>' +
        '<td>'+sizeText(e.size)+'</td><td><code title="'+attr(e.fileHash)+'">'+attr(String(e.fileHash||'').slice(0,12))+'…</code></td>' +
        '<td>'+attr(e.uploadedBy||'—')+'</td><td>'+DZ.date(e.uploadedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : DZ.empty('暂无证据登记');

    // 签署
    const so = S.signoff || { signoffs: [], submitterAccount: null };
    const signRows = (so.signoffs||[]).length ? '<div class="dz-table-wrap"><table><thead><tr><th>签署人</th><th>角色</th><th>决定</th><th>意见</th><th>时间</th></tr></thead><tbody>' +
      so.signoffs.map(s => '<tr><td>'+attr(s.signerName||s.signer)+(s.signer?' <span class="muted">('+attr(s.signer)+')</span>':'')+'</td>' +
        '<td>'+attr(s.role||'—')+'</td>' +
        '<td>'+(s.decision==='reject'?DZ.badge('bad','驳回'):DZ.badge('ok','通过'))+'</td>' +
        '<td>'+attr(s.comment||'—')+'</td><td>'+DZ.date(s.signedAt)+'</td></tr>').join('') +
      '</tbody></table></div>' : DZ.empty('暂无签署记录');
    const isSelf = so.submitterAccount && S.session && so.submitterAccount === S.session.account;

    box.innerHTML = head +
      '<div class="card"><h3>证据登记（G3.5）</h3>' +
        '<div class="muted">演示：仅登记元数据 + 哈希，不落真实文件。</div>' +
        '<div class="grid2">' +
          '<div><label>检查项</label><select id="ev_code" title="关联检查项">'+(codeOpts||'<option value="">（无单项）</option>')+'</select></div>' +
          '<div><label>文件名 *</label><input id="ev_name" placeholder="如 访问控制日志截图.png"></div>' +
          '<div><label>大小（字节）</label><input id="ev_size" type="number" placeholder="如 88421" value="88421"></div>' +
          '<div><label>哈希（可留空自动生成）</label><input id="ev_hash" placeholder="留空则按文件内容自动生成"></div>' +
          '<div><label>上传人</label><select id="ev_by" title="上传人">'+acctOpts+'</select></div>' +
        '</div>' +
        '<div class="row" style="margin-top:10px"><button data-act="add-evidence" title="登记证据元数据">登记证据</button><span id="ev_msg" class="muted"></span></div>' +
        '<h4>证据列表（'+S.evidence.length+'）</h4>'+evRows +
      '</div>' +
      '<div class="card"><h3>签署与复核（职责分离演示）</h3>' +
        '<div class="muted">提交人（经办）：<code>'+attr(so.submitterAccount||'—')+'</code>。职责分离：签署账号不得与提交人相同，否则后端返回 403。</div>' +
        (isSelf ? DZ.banner('warn', '当前账号即为提交人，直接签署将触发职责分离拦截；请切换到非提交人账号（如 李复核）后再签署。') : '') +
        '<div class="grid2" style="margin-top:8px">' +
          '<div><label>签署账号</label><select id="so_account" title="签署账号">'+acctOpts+'</select></div>' +
          '<div><label>角色</label><input id="so_role" placeholder="如 l1_review（L1 复核）" value="'+(isSelf?'':'l1_review')+'"></div>' +
          '<div><label>决定</label><select id="so_decision" title="签署决定"><option value="approve">通过</option><option value="reject">驳回</option></select></div>' +
          '<div><label>意见</label><input id="so_comment" placeholder="如 复核通过，同意闭环"></div>' +
        '</div>' +
        '<div id="so_msg" style="margin-top:10px"></div>' +
        '<div class="row" style="margin-top:8px"><button data-act="signoff" title="提交签署">提交签署</button></div>' +
        '<h4>签署记录</h4>'+signRows +
      '</div>';
  }

  // =====================================================================
  // 交互（事件委托）
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
      if (act === 'sel-line'){ onSelLine(t.getAttribute('data-line')); }
      else if (act === 'open-task'){ onOpenTask(t.getAttribute('data-id')); }
      else if (act === 'refresh-tasks'){ loadTasks().then(renderTasksCard); }
      else if (act === 'open-new'){ S.tab = 'new'; renderMain(); }
      else if (act === 'cancel-new'){ S.tab = 'profile'; renderMain(); }
      else if (act === 'create-task'){ onCreateTask(t); }
      else if (act === 'save-item'){ onSaveItem(t.getAttribute('data-code'), t); }
      else if (act === 'ai-match'){ onAiMatch(t.getAttribute('data-code'), t); }
      else if (act === 'reload-items'){ reloadItems(); }
      else if (act === 'reload-templates'){ refreshTemplates(); }
      else if (act === 'reload-industries'){ loadIndustries().then(function(){ renderSession(); renderIndustryLeft(); refreshTemplates(); }); }
      else if (act === 'filter-status'){ onFilterStatus(t.getAttribute('data-status')); }
      else if (act === 'preview-assign'){ onPreviewAssign(t); }
      else if (act === 'dispatch-assign'){ onDispatchAssign(t); }
      else if (act === 'override-open'){ onOverrideOpen(t.getAttribute('data-code')); }
      else if (act === 'override-submit'){ onOverrideSubmit(t.getAttribute('data-code'), t); }
      else if (act === 'override-cancel'){ const a = $('#as_override_area'); if (a) a.innerHTML=''; }
      else if (act === 'add-evidence'){ onAddEvidence(t); }
      else if (act === 'signoff'){ onSignoff(t); }
    });

    // 键盘可达：任务卡 Enter / Space 打开
    r.addEventListener('keydown', function(e){
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const t = e.target.closest('[data-act="open-task"]');
      if (t){ e.preventDefault(); onOpenTask(t.getAttribute('data-id')); }
    });

    // 下拉开变化
    r.addEventListener('change', function(e){
      const t = e.target.closest('[data-act]');
      if (!t) return;
      const act = t.getAttribute('data-act');
      if (act === 'switch-account'){ onSwitchAccount(t.value); }
      else if (act === 'sel-industry'){ S.selIndustry = t.value; S.selLine=''; renderIndustryLeft(); refreshTemplates(); }
      else if (act === 'filter-industry'){ S.filterIndustry = t.value; loadTasks().then(renderTasksCard); }
      else if (act === 'new-industry'){ S.selIndustry = t.value; renderNewForm(); }
    });
  }

  function onSelLine(line){
    S.selLine = line || '';
    renderIndustryLeft();
    refreshTemplates();
  }
  function onFilterStatus(st){
    S.filterStatus = st || '';
    loadTasks().then(renderTasksCard);
  }
  async function onSwitchAccount(account){
    const sel = $('dsc_acct');
    if (sel) sel.disabled = true;
    const res = await DZ.post('/api/auth/login', { account: account });
    if (sel) sel.disabled = false;
    if (res && res.error){ DZ.toast(res.error.message || '切换账号失败', 'bad'); return; }
    DZ.toast('已切换为 ' + ((res.session && res.session.displayName) || account), 'ok');
    S.session = res.session;
    S.selTaskId = null; S.detail = null; S.tab = 'profile';
    renderSession();
    await loadTasks();
    renderTasksCard();
    renderMain();
  }
  async function onOpenTask(id){
    if (!id) return;
    S.selTaskId = id; S.tab = 'items'; S.detail = null; S.items = [];
    renderTasksCard();
    const r = rootEl();
    // 详情骨架
    DZ.render('#dsc_main', DZ.skeleton(6));
    await loadTaskBundle(id);
    if (S.selTaskId !== id) return;
    renderMain();
  }
  async function reloadItems(){
    if (!S.selTaskId) return;
    DZ.render('#dsc_main', DZ.skeleton(5));
    await loadTaskBundle(S.selTaskId);
    renderTab();
  }
  async function reloadVerdict(){
    const res = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/verdict');
    S.verdict = (res && !res.error) ? res : null;
    renderTab();
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
      scope: { lines: scopeLines },
      stage: ($('nt_stage')||{}).value || '季度自查',
      topic: ($('nt_topic')||{}).value || '数据安全专项',
      owner: ($('nt_owner')||{}).value || (S.session && S.session.account),
      assignees: assignees
    };
    setBtnBusy(btn, true, '创建中…');
    const res = await DZ.post('/api/selfcheck/tasks', body);
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '创建失败'; DZ.toast(res.error.message || '创建失败', 'bad'); return; }
    DZ.toast('任务已创建', 'ok');
    S.filterIndustry = ''; S.filterStatus = '';
    await loadTasks();
    renderTasksCard();
    if (res && res.taskId){ onOpenTask(res.taskId); }
  }

  // ---- 单项保存 ----
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
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/items', body);
    setBtnBusy(btn, false);
    if (res && res.error){ DZ.toast(res.error.message || '保存失败', 'bad'); return; }
    DZ.toast('已保存录入项 ' + code, 'ok');
    await loadTaskBundle(S.selTaskId);
    renderTab();
  }

  // ---- AI 佐证匹配 ----
  async function onAiMatch(code, btn){
    setBtnBusy(btn, true, '匹配中…');
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) +
                              '/items/' + encodeURIComponent(code) + '/ai-match', {});
    setBtnBusy(btn, false);
    const out = document.querySelector('#dsc_root [data-aio="' + code + '"]');
    if (!out) return;
    if (res && res.error){ out.innerHTML = DZ.banner('bad', res.error.message || 'AI 匹配失败', function(){ onAiMatch(code, btn); }); return; }
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
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/assignments/preview', body);
    setBtnBusy(btn, false);
    if (res && res.error){ DZ.toast(res.error.message || '预览失败', 'bad'); return; }
    S.assignPreview = res;
    renderTab();
  }
  async function onDispatchAssign(btn){
    const msg = $('as_msg');
    setBtnBusy(btn, true, '下发中…');
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/assignments/dispatch',
      { confirmedBy: (S.session && S.session.account) || '' });
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '下发失败'; DZ.toast(res.error.message || '下发失败', 'bad'); return; }
    DZ.toast('分配已下发：' + res.batchId, 'ok');
    S.assignPreview = null;
    // 重新载入当前映射
    const a = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/assignments');
    S.assignments = (a && !a.error) ? a : S.assignments;
    renderTab();
  }
  async function ensureDicts(){
    if (!S.positions){
      const p = await DZ.get('/api/admin/org-positions');
      S.positions = (p && !p.error) ? (p.positions || []) : [];
    }
    if (!S.nodes){
      const n = await DZ.get('/api/admin/org-nodes');
      if (n && !n.error && n.tree){
        const flat = [];
        (function walk(list){ (list||[]).forEach(x => { flat.push({ id:x.node_id, name:x.name, level:x.level }); walk(x.children); }); })(n.tree);
        S.nodes = flat;
      } else S.nodes = [];
    }
  }
  async function onOverrideOpen(code){
    const area = $('#as_override_area'); if (!area) return;
    area.innerHTML = '<div class="card">' + DZ.skeleton(3) + '</div>';
    await ensureDicts();
    const deptOpts = (S.nodes||[]).map(n => '<option value="'+attr(n.id)+'">'+attr(n.name)+'（'+attr(n.level)+'）</option>').join('');
    const posOpts = (S.positions||[]).map(p => '<option value="'+attr(p.positionId)+'">'+attr(p.name)+' · '+attr(p.orgNodeName||'')+'</option>').join('');
    area.innerHTML =
      '<div class="card" data-ov="'+attr(code)+'">' +
        '<h4>手工覆盖责任 · 检查项 <code>'+attr(code)+'</code></h4>' +
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
    const res = await DZ.patch('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) +
                               '/assignments/' + encodeURIComponent(code), body);
    setBtnBusy(btn, false);
    if (res && res.error){
      const a = $('#as_override_area');
      if (a) a.innerHTML = DZ.banner('bad', res.error.message || '覆盖失败（需先下发分配批次）', function(){ onOverrideSubmit(code, btn); });
      DZ.toast(res.error.message || '覆盖失败', 'bad');
      return;
    }
    DZ.toast('已覆盖 ' + code, 'ok');
    const a = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/assignments');
    S.assignments = (a && !a.error) ? a : S.assignments;
    renderTab();
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
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/evidence', body);
    setBtnBusy(btn, false);
    if (res && res.error){ if (msg) msg.textContent = res.error.message || '登记失败'; DZ.toast(res.error.message || '登记失败', 'bad'); return; }
    DZ.toast('证据已登记', 'ok');
    await loadEvidence(S.selTaskId);
    renderTab();
  }

  // ---- 签署（职责分离） ----
  async function onSignoff(btn){
    const msg = $('so_msg');
    const body = {
      account: ($('so_account')||{}).value || (S.session && S.session.account),
      role: (($('so_role')||{}).value || '').trim(),
      decision: ($('so_decision')||{}).value || 'approve',
      comment: (($('so_comment')||{}).value || '').trim()
    };
    setBtnBusy(btn, true, '签署中…');
    const res = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(S.selTaskId) + '/signoff', body);
    setBtnBusy(btn, false);
    if (res && res.error){
      const isSod = res.error.code === 'FORBIDDEN';
      if (msg){
        msg.innerHTML = DZ.banner('bad',
          (res.error.message || '职责分离校验不通过：经办与复核不得为同一账号') +
          (isSod ? ' 请在上方「演示账号」处切换为非提交人账号（如 李复核 lifh）后重试。' : ''));
      }
      DZ.toast(isSod ? '职责分离校验不通过，请换账号签署' : (res.error.message || '签署失败'), 'bad');
      return;
    }
    DZ.toast('签署成功：' + (res.signoffId || ''), 'ok');
    await loadSignoff(S.selTaskId);
    renderTab();
  }

  // =====================================================================
  // 注册视图
  // =====================================================================
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['dsc'] = function(){ init(); };
})();
