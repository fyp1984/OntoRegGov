/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo（demo_reports.js）
   视图：报告与看板（id = rep，容器 #rep_root）
   依赖：demo_common.js 提供的全局 DZ 命名空间；styles.css / demo.css 现有样式。
   仅调用契约 §5.8 的三个接口，字段严格以后端真实返回为准：
     GET /api/selfcheck/progress
     GET /api/selfcheck/tasks/{id}/report?fmt=json
     GET /api/selfcheck/tasks/{id}/report/md
   不引入任何图表库 / CDN，条形与趋势均为纯 CSS / 内联样式实现。
   ============================================================ */
(function(){
  'use strict';

  const ROOT = '#rep_root';

  // ---------- 接口清单（唯一权威，勿臆造） ----------
  const API = {
    progress: '/api/selfcheck/progress',
    report: function(id){ return '/api/selfcheck/tasks/' + encodeURIComponent(id) + '/report?fmt=json'; },
    reportMd: function(id){ return '/api/selfcheck/tasks/' + encodeURIComponent(id) + '/report/md'; }
  };

  // 视图状态（跨重入保留当前选中任务与当前页签）
  const state = { tasks: [], selectedTaskId: null, tab: 'overview' };

  // 页签定义：把原先纵向堆叠的 6 个板块按"看态势 / 看任务报告"两类互斥呈现，避免单页拥挤。
  const TABS = [
    { key: 'overview', label: '态势总览' },
    { key: 'tasks',    label: '任务与报告' }
  ];

  // ---------- 小工具 ----------
  function root(){ return document.querySelector(ROOT); }
  function errMsg(d){ return (d && d.error && d.error.message) || '接口请求失败'; }
  function round1(n){ const v = Number(n); if (!isFinite(v)) return 0; return Math.round(v * 10) / 10; }
  function clampPct(n){ let v = Number(n); if (!isFinite(v)) v = 0; return Math.max(0, Math.min(100, v)); }

  // 优先级徽章：P0/P1/P2 → 现有 .b-p0/.b-p1/.b-p2
  function priorityBadge(p){
    const k = String(p || '').toLowerCase();
    const kind = (k === 'p0' || k === 'p1' || k === 'p2') ? k : 'p2';
    return DZ.badge(kind, p || '—');
  }
  // 布尔徽章：同时给出文字，状态不只靠颜色
  function boolBadge(v, yes, no){ return DZ.badge(v ? 'ok' : 'bad', v ? (yes || '是') : (no || '否')); }

  // 自绘彩色条形：结构复用 .dz-bar，颜色仅取现有 CSS 变量
  function colorBar(percent, colorVar){
    const v = clampPct(percent);
    return '<div class="dz-bar"><i style="width:' + v + '%;background:' + colorVar + '"></i></div>';
  }

  // 结果四态 / 风险等级 → 现有变量色
  const RESULT_COLOR = { pass:'var(--ok)', partial:'var(--warn)', fail:'var(--bad)', supplement:'var(--unk)' };
  const RISK_COLOR   = { high:'var(--bad)', medium:'var(--warn)', low:'var(--unk)' };
  const VERDICT = { pass:['ok','符合'], partial:['warn','部分符合'], fail:['bad','不符合'], supplement:['unk','需补充'] };
  const RISK_TEXT = { high:'高', medium:'中', low:'低' };

  function verdictText(v){ return (VERDICT[v] || ['unk', v || '—'])[1]; }
  function verdictKind(v){ return (VERDICT[v] || ['unk',''])[0]; }
  function riskText(r){ return RISK_TEXT[r] || (r || '—'); }
  function riskKind(r){ return r === 'high' ? 'bad' : (r === 'medium' ? 'warn' : (r === 'low' ? 'unk' : '')); }
  function scoreKind(s){ const v = Number(s); if (!isFinite(v)) return ''; return v >= 80 ? 'ok' : (v >= 60 ? 'warn' : 'bad'); }

  // ---------- 视图骨架（先渲染骨架屏，避免空白） ----------
  function shell(){
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="rep_refresh" title="重新拉取看板数据" aria-label="刷新看板数据">刷新看板</button>' +
      '</div>' +
      '<div id="rep_tabs"></div>' +
      // 页签一：态势总览（KPI + 条线 / 风险 / 结论分布 + 整改趋势）
      '<div class="dz-pane" data-pane="overview">' +
        '<div id="rep_kpis">' + DZ.skeleton(2) + '</div>' +
        '<div class="grid2">' +
          '<div class="card"><h3>条线进度分布</h3><div id="rep_byline">' + DZ.skeleton(3) + '</div></div>' +
          '<div class="card"><h3>风险等级分布</h3><div id="rep_byrisk">' + DZ.skeleton(2) + '</div>' +
            '<h4>四态结论分布</h4><div id="rep_byresult">' + DZ.skeleton(2) + '</div></div>' +
        '</div>' +
        '<div class="card"><h3>整改趋势</h3><div id="rep_trend">' + DZ.skeleton(2) + '</div></div>' +
      '</div>' +
      // 页签二：任务与报告（任务列表 + 选中任务的行业版报告）
      '<div class="dz-pane" data-pane="tasks" hidden>' +
        '<div class="card"><h3>自查任务</h3><div id="rep_tasks" class="dz-table-wrap">' + DZ.skeleton(3) + '</div></div>' +
        '<div class="card"><h3>行业版报告</h3><div id="rep_report">' + DZ.skeleton(4) + '</div></div>' +
      '</div>';
  }

  // ---------- 页签渲染与切换 ----------
  function renderTabs(){
    const items = TABS.map(function(t){
      const it = { key: t.key, label: t.label };
      if (t.key === 'tasks' && state.tasks.length) it.count = state.tasks.length;
      return it;
    });
    DZ.tabs('#rep_tabs', items, state.tab, function(key){ switchTab(key); });
  }

  function switchTab(key){
    state.tab = key;
    const box = root();
    if (!box) return;
    box.querySelectorAll('.dz-pane').forEach(function(p){ p.hidden = (p.getAttribute('data-pane') !== key); });
    renderTabs();
    // 切到"任务与报告"且尚未选任务时，默认选第一个，避免右侧空白
    if (key === 'tasks' && !state.selectedTaskId && state.tasks.length){
      selectTask(state.tasks[0].taskId, true);
    }
  }

  // ---------- 挂载 ----------
  function mount(){
    const box = root();
    if (!box) return;
    box.innerHTML = shell();
    switchTab(state.tab);
    DZ.on('#rep_refresh', 'click', function(){ mount(); });
    loadProgress();
  }

  // ---------- 看板：拉取进度 ----------
  async function loadProgress(){
    const data = await DZ.get(API.progress);

    if (!data || data.error){
      const msg = errMsg(data);
      DZ.render('#rep_kpis', DZ.banner('bad', '看板数据加载失败：' + msg, loadProgress));
      DZ.render('#rep_byline', DZ.empty('条线分布暂不可用'));
      DZ.render('#rep_byrisk', DZ.empty('风险分布暂不可用'));
      DZ.render('#rep_byresult', DZ.empty('结论分布暂不可用'));
      DZ.render('#rep_trend', DZ.empty('趋势数据暂不可用'));
      DZ.render('#rep_tasks', DZ.empty('任务列表暂不可用'));
      DZ.render('#rep_report', DZ.empty('选择任务后可查看行业版报告'));
      return;
    }

    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    state.tasks = tasks;

    renderKpis(data.kpis || {}, Array.isArray(data.byResult) ? data.byResult : []);
    renderByLine(Array.isArray(data.byLine) ? data.byLine : []);
    renderByRisk(Array.isArray(data.byRisk) ? data.byRisk : []);
    renderByResult(Array.isArray(data.byResult) ? data.byResult : []);
    renderTrend(Array.isArray(data.trend) ? data.trend : []);
    renderTasks(tasks);
    renderTabs();

    // 默认选中第一个任务；若已选任务仍存在则保留
    let sel = state.selectedTaskId;
    if (!sel || !tasks.some(function(t){ return t.taskId === sel; })){
      sel = tasks.length ? tasks[0].taskId : null;
    }
    if (sel){ selectTask(sel, false); }
    else { DZ.render('#rep_report', DZ.empty('暂无可生成报告的自查任务')); }
  }

  // ---------- KPI（严格使用后端 kpis 字段 + 由 byResult 派生的合规率） ----------
  function renderKpis(kpis, byResult){
    let pass = 0, total = 0;
    byResult.forEach(function(r){
      total += Number(r.count) || 0;
      if (r.result === 'pass') pass += Number(r.count) || 0;
    });
    const compliance = total ? round1(pass / total * 100) : 0;

    const row = [
      DZ.kpi('自查任务', DZ.number(kpis.tasks), '任务总数', ''),
      DZ.kpi('进行中', DZ.number(kpis.inProgress), '任务总数中的进行中', 'warn'),
      DZ.kpi('已闭环', DZ.number(kpis.closed), '任务总数中的已闭环', 'ok'),
      DZ.kpi('草稿', DZ.number(kpis.draft), '任务总数中的草稿', ''),
      DZ.kpi('平均进度', DZ.number(kpis.avgProgress) + '%', '全部任务的平均完成度', ''),
      DZ.kpi('合规率', compliance + '%', '符合 ' + DZ.number(pass) + ' / 合计 ' + DZ.number(total), scoreKind(compliance))
    ].join('');
    DZ.render('#rep_kpis', '<div class="dz-kpi-row">' + row + '</div>');
  }

  // ---------- 条线进度分布（纯 CSS 条形） ----------
  function renderByLine(list){
    if (!list.length){ DZ.render('#rep_byline', DZ.empty('暂无条线进度数据')); return; }
    const html = list.map(function(x){
      const p = round1(clampPct(x.progress));
      return '<div style="margin-bottom:12px">' +
        '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(x.line || '—') + '</span>' +
        '<span class="dz-metric-v">' + p + '%</span></div>' + DZ.bar(p) + '</div>';
    }).join('');
    DZ.render('#rep_byline', html);
  }

  // ---------- 风险等级分布（按风险着色） ----------
  function renderByRisk(list){
    if (!list.length){ DZ.render('#rep_byrisk', DZ.empty('暂无风险分布数据')); return; }
    const total = list.reduce(function(s, x){ return s + (Number(x.count) || 0); }, 0) || 1;
    const html = list.map(function(x){
      const p = round1((Number(x.count) || 0) / total * 100);
      return '<div style="margin-bottom:12px" title="风险等级：' + DZ.esc(riskText(x.risk)) + '，共 ' + DZ.number(x.count) + ' 个任务">' +
        '<div class="dz-metric"><span class="dz-metric-k">' + DZ.severityBadge(x.risk) + '</span>' +
        '<span class="dz-metric-v">' + DZ.number(x.count) + ' 个 · ' + p + '%</span></div>' +
        colorBar(p, RISK_COLOR[x.risk] || 'var(--unk)') + '</div>';
    }).join('');
    DZ.render('#rep_byrisk', html);
  }

  // ---------- 四态结论分布（按结论着色） ----------
  function renderByResult(list){
    if (!list.length){ DZ.render('#rep_byresult', DZ.empty('暂无结论分布数据')); return; }
    const total = list.reduce(function(s, x){ return s + (Number(x.count) || 0); }, 0) || 1;
    const html = list.map(function(x){
      const p = round1((Number(x.count) || 0) / total * 100);
      return '<div style="margin-bottom:12px" title="结论：' + DZ.esc(verdictText(x.result)) + '，共 ' + DZ.number(x.count) + ' 条">' +
        '<div class="dz-metric"><span class="dz-metric-k">' + DZ.resultBadge(x.result) + '</span>' +
        '<span class="dz-metric-v">' + DZ.number(x.count) + ' 条 · ' + p + '%</span></div>' +
        colorBar(p, RESULT_COLOR[x.result] || 'var(--unk)') + '</div>';
    }).join('');
    DZ.render('#rep_byresult', html);
  }

  // ---------- 整改趋势（纯内联样式柱状时序，标注"演示数据"） ----------
  function renderTrend(list){
    if (!list.length){ DZ.render('#rep_trend', DZ.empty('暂无趋势数据')); return; }
    const maxTotal = Math.max.apply(null, list.map(function(x){ return Number(x.total) || 0; }).concat([1]));
    const cols = list.map(function(x){
      const total = Number(x.total) || 0;
      const closed = Number(x.closed) || 0;
      const hTotal = Math.max(4, Math.round(total / maxTotal * 110));
      const hClosed = closed > 0 ? Math.max(4, Math.round(closed / maxTotal * 110)) : 0;
      return '<div style="flex:1;min-width:56px;text-align:center" title="' + DZ.esc(x.cycle) +
          '：任务总数 ' + total + '，已闭环 ' + closed + '">' +
        '<div style="display:flex;gap:4px;align-items:flex-end;justify-content:center;height:120px">' +
          '<div aria-label="' + DZ.esc(x.cycle) + ' 任务总数 ' + total + '" style="width:16px;height:' + hTotal +
            'px;background:var(--brand-bg);border:1px solid var(--brand-border);border-radius:4px 4px 0 0"></div>' +
          '<div aria-label="' + DZ.esc(x.cycle) + ' 已闭环 ' + closed + '" style="width:16px;height:' + hClosed +
            'px;background:var(--brand);border-radius:4px 4px 0 0"></div>' +
        '</div>' +
        '<div class="dz-mini">' + DZ.esc(x.cycle) + '</div>' +
        '<div class="dz-mini">' + closed + '/' + total + '</div>' +
      '</div>';
    }).join('');
    const legend = '<div class="dz-legend">' +
      '<span title="该周期自查任务总数"><b style="background:var(--brand-bg);border:1px solid var(--brand-border)"></b>任务总数</span>' +
      '<span title="该周期已闭环任务数"><b style="background:var(--brand)"></b>已闭环</span>' +
      '<span class="muted">演示数据</span></div>';
    DZ.render('#rep_trend', legend +
      '<div style="display:flex;gap:16px;align-items:flex-end;overflow:auto;padding-top:6px">' + cols + '</div>');
  }

  // ---------- 任务表（点行或按钮 → 查看报告） ----------
  function renderTasks(tasks){
    if (!tasks.length){
      DZ.render('#rep_tasks', DZ.empty('暂无自查任务',
        '<button class="ghost" id="rep_goto_dsc" title="前往安全自查" aria-label="前往安全自查">前往安全自查</button>'));
      DZ.on('#rep_goto_dsc', 'click', function(){ if (typeof window.showView === 'function') window.showView('dsc'); });
      return;
    }
    const rows = tasks.map(function(t){
      const sel = t.taskId === state.selectedTaskId;
      const name = (t.cycle || '—') + (t.topic ? ' · ' + t.topic : '');
      return '<tr data-task-id="' + DZ.esc(t.taskId) + '" role="button" tabindex="0" ' +
          'title="点击查看该任务的行业版报告" aria-label="查看 ' + DZ.esc(t.orgName || '') + ' 的报告"' +
          (sel ? ' style="background:var(--brand-soft)"' : '') + '>' +
        '<td>' + DZ.esc(name) + '</td>' +
        '<td>' + DZ.esc(t.orgName || '—') + '</td>' +
        '<td style="min-width:140px">' +
          '<div class="dz-mini" style="margin-bottom:4px">' + round1(clampPct(t.progress)) + '%</div>' +
          DZ.bar(clampPct(t.progress)) + '</td>' +
        '<td>' + DZ.severityBadge(t.riskLevel) + '</td>' +
        '<td>' + DZ.statusBadge(t.status) + '</td>' +
        '<td><div class="row">' +
          '<button class="ghost dz-report-btn" data-task-id="' + DZ.esc(t.taskId) + '" ' +
            'title="查看行业版报告" aria-label="查看 ' + DZ.esc(t.orgName || '') + ' 的报告">查看报告</button>' +
          (sel ? DZ.pill('已选') : '') +
        '</div></td></tr>';
    }).join('');
    DZ.render('#rep_tasks',
      '<table><thead><tr><th>名称</th><th>机构</th><th>进度</th><th>风险</th><th>状态</th><th>操作</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>');

    // 行点击
    DZ.on('#rep_tasks tbody tr', 'click', function(){
      selectTask(this.getAttribute('data-task-id'), true);
    });
    // 键盘可达：Enter / Space 触发
    DZ.on('#rep_tasks tbody tr', 'keydown', function(e){
      if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); selectTask(this.getAttribute('data-task-id'), true); }
    });
    // 按钮点击（阻止冒泡，避免与行点击重复触发）
    DZ.on('#rep_tasks .dz-report-btn', 'click', function(e){
      e.stopPropagation();
      selectTask(this.getAttribute('data-task-id'), true);
    });
  }

  // ---------- 选择任务并加载报告 ----------
  async function selectTask(taskId, refreshTable){
    if (!taskId) return;
    state.selectedTaskId = taskId;
    if (refreshTable) renderTasks(state.tasks);
    await loadReport(taskId);
  }

  async function loadReport(taskId){
    DZ.render('#rep_report', DZ.skeleton(5));
    const data = await DZ.get(API.report(taskId));
    if (!data || data.error){
      DZ.render('#rep_report', DZ.banner('bad', '报告加载失败：' + errMsg(data), function(){ loadReport(taskId); }));
      return;
    }
    renderReport(taskId, data);
  }

  // ---------- 渲染行业版报告 ----------
  function renderReport(taskId, rep){
    const meta = rep.meta || {};
    const summary = rep.summary || {};
    const items = Array.isArray(rep.items) ? rep.items : [];
    const gaps = rep.gapSummary || {};
    const opinions = Array.isArray(rep.expertOpinions) ? rep.expertOpinions : [];
    const total = items.length;
    const evOk = items.filter(function(i){ return !!i.evidenceComplete; }).length;
    const ctOk = items.filter(function(i){ return !!i.contentAdequate; }).length;
    const evPct = total ? round1(evOk / total * 100) : 0;
    const ctPct = total ? round1(ctOk / total * 100) : 0;

    // 导出按钮：直接指向报告接口，带 download 属性
    const dlName = '自查报告-' + String(taskId) + '.md';
    const dlBtn = '<a class="dz-chip" style="text-decoration:none" download="' + DZ.esc(dlName) + '" ' +
      'href="' + API.reportMd(taskId) + '" title="下载自查报告" aria-label="下载自查报告">下载自查报告</a>';

    // 页脚（footer 字段 + 前端兜底标识）
    let foot = String(rep.footer || '').trim();
    if (foot.indexOf('脱敏') < 0) foot = (foot ? foot + ' ' : '') + '脱敏样例，仅供演示使用。';

    let html = '';
    // 报告头
    html += '<div class="dz-toolbar">' +
      '<span class="pill" title="报告模板">' + DZ.esc(meta.template || '行业版报告') + '</span>' +
      '<span class="muted" title="报告元信息">' + DZ.esc(meta.orgName || '') + ' · ' + DZ.esc(meta.cycle || '') +
        ' · 行业 ' + DZ.esc(meta.industry || '—') + ' · 生成于 ' + DZ.esc(DZ.date(meta.generatedAt)) + '</span>' +
      dlBtn + '</div>';

    // 摘要 KPI
    html += '<div class="dz-kpi-row">' +
      DZ.kpi('合规率', (summary.score != null ? summary.score : 0) + '%', '符合 / 合计', scoreKind(summary.score)) +
      DZ.kpi('判定结论', verdictText(summary.verdict), '按最差项聚合', verdictKind(summary.verdict)) +
      DZ.kpi('风险等级', riskText(summary.riskLevel), '综合风险等级', riskKind(summary.riskLevel)) +
      DZ.kpi('佐证完整性', evPct + '%', evOk + ' / ' + total, evPct >= 80 ? 'ok' : 'warn') +
      DZ.kpi('内容完备性', ctPct + '%', ctOk + ' / ' + total, ctPct >= 80 ? 'ok' : 'warn') +
    '</div>';

    // 符合 / 部分符合 / 不符合 / 需补充 计数
    html += '<h4>结论计数</h4><div class="row" title="四态结论计数">' +
      '<span>' + DZ.resultBadge('pass') + ' ' + DZ.number(summary.pass) + '</span>' +
      '<span>' + DZ.resultBadge('partial') + ' ' + DZ.number(gaps.partial) + '</span>' +
      '<span>' + DZ.resultBadge('fail') + ' ' + DZ.number(gaps.fail) + '</span>' +
      '<span>' + DZ.resultBadge('supplement') + ' ' + DZ.number(gaps.supplement) + '</span>' +
    '</div>';

    // 报告五项结构（白皮书第 3 章 / 附录 B）
    html += renderFive(rep.five);

    // 逐条检查项（不符合 / 部分符合默认展开）
    html += '<h4>逐条检查项（' + total + '）</h4>';
    if (!total){
      html += DZ.empty('该报告暂无检查项详情');
    } else {
      html += items.map(renderReportItem).join('');
    }

    // 差距汇总
    html += '<h4>差距汇总</h4><div class="row" title="差距汇总">' +
      '<span class="pill">不符合 ' + DZ.number(gaps.fail) + '</span>' +
      '<span class="pill">部分符合 ' + DZ.number(gaps.partial) + '</span>' +
      '<span class="pill">需补充 ' + DZ.number(gaps.supplement) + '</span></div>';

    // 专家意见汇总
    if (opinions.length){
      html += '<h4>专家意见汇总</h4><div class="why">' +
        '<ul style="margin:0 0 0 18px">' +
        opinions.map(function(o){ return '<li>' + DZ.esc(o) + '</li>'; }).join('') +
        '</ul></div>';
    }

    // 页脚标识
    html += '<div class="dz-cite" title="报告标识"><div>' + DZ.esc(foot) + '</div>' +
      '<div class="dz-cite-src">脱敏样例 · 生成于 ' + DZ.esc(DZ.date(meta.generatedAt)) + '</div></div>';

    DZ.render('#rep_report', html);
  }

  // ---------- 报告五项结构（问题清单 / 依据条款 / 责任归属 / 证据缺口 / 下一步建议） ----------
  function renderFive(five){
    five = five || {};
    const problems  = Array.isArray(five.problems)      ? five.problems      : [];
    const bases     = Array.isArray(five.bases)         ? five.bases         : [];
    const ownership = Array.isArray(five.ownership)     ? five.ownership     : [];
    const gaps      = Array.isArray(five.evidenceGaps)  ? five.evidenceGaps  : [];
    const nexts     = Array.isArray(five.nextSteps)     ? five.nextSteps     : [];

    function ul(list, textOf){
      if (!list.length) return '<div class="muted">无</div>';
      return '<ul style="margin:0 0 0 18px">' + list.map(function(x){ return '<li>' + DZ.esc(textOf(x)) + '</li>'; }).join('') + '</ul>';
    }
    function use(txt){ return ' <span class="muted">' + DZ.esc(txt) + '</span>'; }

    let html = '<h4>报告五项结构</h4>';
    if (five.note) html += '<div class="muted" style="margin-bottom:8px">' + DZ.esc(five.note) + '</div>';

    html += '<div class="grid2">' +
      '<div class="card"><h3>一、问题清单' + use('给牵头部门掌握全貌') + '</h3>' +
        ul(problems, function(p){ return p.text; }) + '</div>' +
      '<div class="card"><h3>二、依据条款' + use('复核时可直接对照') + '</h3>' +
        '<div class="dz-table-wrap"><table>' +
          '<thead><tr><th>监管要求</th><th>判定口径</th></tr></thead><tbody>' +
          (bases.length ? bases.map(function(b){
            return '<tr><td>' + DZ.esc(b.requirement) + '</td><td>' + DZ.esc(b.criterion) + '</td></tr>';
          }).join('') : '<tr><td colspan="2" class="muted">无</td></tr>') +
        '</tbody></table></div>' +
        '<div class="muted" style="margin-top:6px">此处不列具体条号，引用以公开文件为准。</div></div>' +
    '</div>';

    html += '<div class="card"><h3>三、责任归属' + use('拆到条线的派单依据') + '</h3>' +
      (ownership.length ? '<div class="dz-table-wrap"><table>' +
        '<thead><tr><th style="min-width:200px">环节</th><th>发起</th><th>审批</th><th>复核</th><th>问责</th></tr></thead><tbody>' +
        ownership.map(function(o){
          return '<tr><td>' + DZ.esc(o.title) + '<br><span class="muted">' + DZ.esc(o.code) + '</span></td>' +
            '<td>' + DZ.esc(o.initiator) + '</td><td>' + DZ.esc(o.approver) + '</td>' +
            '<td>' + DZ.esc(o.reviewer) + '</td><td>' + DZ.esc(o.accountable) + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<div class="muted">无</div>') + '</div>';

    html += '<div class="grid2">' +
      '<div class="card"><h3>四、证据缺口' + use('下一轮补齐的起点') + '</h3>' +
        ul(gaps, function(g){ return g.text; }) + '</div>' +
      '<div class="card"><h3>五、下一步建议' + use('形成地图的第一条路线') + '</h3>' +
        (nexts.length ? nexts.map(function(n){
          return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(n.priority) + '</span>' +
            '<span class="dz-metric-v" style="font-weight:400;text-align:right;max-width:70%">' + DZ.esc(n.text) + '</span></div>';
        }).join('') : '<div class="muted">无</div>') + '</div>' +
    '</div>';

    return html;
  }

  // 单条检查项：checkCode / title / result / priority / 佐证完整性 / 内容完备性 / 是否合规 / 差距 / 整改建议 / 专家意见
  function renderReportItem(it){
    const open = (it.result === 'fail' || it.result === 'partial');
    const head = '<span class="dz-tag-soft" title="条款编码">' + DZ.esc(it.checkCode || '—') + '</span> ' +
      DZ.esc(it.title || it.checkCode || '') + ' ' +
      DZ.resultBadge(it.result) + ' ' + priorityBadge(it.priority);

    const gapList = (Array.isArray(it.gaps) && it.gaps.length)
      ? '<ul style="margin:4px 0 0 18px">' + it.gaps.map(function(g){ return '<li>' + DZ.esc(g) + '</li>'; }).join('') + '</ul>'
      : '<div class="muted">无</div>';

    const body =
      '<div class="dz-metric"><span class="dz-metric-k">条款依据</span>' +
        '<span class="dz-metric-v">' + DZ.esc(it.checkCode || '—') + ' · ' + DZ.esc(it.title || '') + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">佐证完整性</span>' +
        '<span class="dz-metric-v">' + boolBadge(it.evidenceComplete, '齐备', '缺失') + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">内容完备性</span>' +
        '<span class="dz-metric-v">' + boolBadge(it.contentAdequate, '完备', '不完备') + '</span></div>' +
      '<div class="dz-metric"><span class="dz-metric-k">是否符合监管要求</span>' +
        '<span class="dz-metric-v">' + boolBadge(it.compliant, '符合', '不符合') + '</span></div>' +
      '<h4>差距</h4>' + gapList +
      '<h4>整改建议</h4><div class="why">' +
        (it.remediation ? DZ.esc(it.remediation) : '<span class="muted">无</span>') + '</div>' +
      '<h4>专家意见</h4><div class="why">' +
        (it.expertOpinion ? DZ.esc(it.expertOpinion) : '<span class="muted">无</span>') + '</div>';

    return '<details' + (open ? ' open' : '') + '>' +
      '<summary title="点击展开 / 收起检查项详情">' + head + '</summary>' + body + '</details>';
  }

  // ---------- 注册视图 ----------
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['rep'] = function(){ mount(); };
})();
