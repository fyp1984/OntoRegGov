/* ============================================================
   运行驾驶舱（dsk）—— demo_console.js
   承载：身份切换 / 全局 KPI / 模块健康与运行保障 / 知识发布现状 /
        一键演示（9 幕全流程）/ 跨模块活动流。
   页签：运行总览 ｜ 一键演示 ｜ 活动留痕。
   严格只用 window.DZ.* 公共函数与 dz- / 现有 class；所有颜色圆角走 CSS 变量。
   依赖：app.js 的 showView / demo_common.js 的 DZ。
   ============================================================ */
(function(){
  'use strict';

  const DZ = window.DZ;
  if (!DZ) { return; }               // 公共层未就绪则静默退出（不影响其它视图）

  const ROOT = 'dsk_root';

  // 页签：把"态势 / 演示 / 留痕"三类信息互斥呈现，避免单页堆叠
  const TABS = [
    { key:'overview', label:'运行总览' },
    { key:'demo',     label:'一键演示' },
    { key:'activity', label:'活动留痕' }
  ];

  // 角色展示名（仅用于呈现，不改后端）
  const ROLE_LABEL = {
    sys_admin:'系统管理员', kb_ops:'知识运营', l0_lead:'L0 牵头', l1_handle:'L1 经办',
    l1_review:'L1 复核', l2_handle:'L2 经办', l3_exec:'L3 执行', manager:'管理者'
  };

  // 模块健康语义（文字 + 颜色，关键状态不只靠颜色）
  const HEALTH = { ok:['ok','正常'], warn:['warn','注意'], bad:['bad','异常'], unk:['unk','未知'] };

  // 发布作业取值的中文展示（仅用于呈现，不改后端）
  const TRIGGER_LABEL = { manual:'手动触发', schedule:'定时轮询', inbound:'变更推送' };
  const MODE_LABEL = { incremental:'增量', full:'全量' };

  // 活动流类型徽章
  const KIND_MAP = {
    audit:['unk','审计'], task:['p0','任务'], publish:['p1','重建'], plugin:['p2','插件']
  };
  // 活动流结果徽章
  const RESULT_MAP = {
    ok:['ok','成功'], success:['ok','成功'], succeeded:['ok','成功'],
    degraded:['warn','降级'], running:['warn','进行中'], pending:['warn','待处理'],
    failed:['bad','失败'], error:['bad','失败'],
    forbidden:['bad','已拦截'], forbidden_sod:['bad','已拦截'], blocked:['bad','已拦截'],
    in_progress:['warn','进行中'], closed:['ok','已闭环'], draft:['unk','草稿'],
    completed:['ok','已完成'], approved:['ok','已通过'], rejected:['bad','已驳回'],
    open:['warn','待处理'], pass:['ok','符合'], partial:['warn','部分符合'],
    fail:['bad','不符合'], supplement:['warn','需补充']
  };

  // 运行保障项：只做跳转，不复述实现细节
  const REDLINES = [
    { no:1, view:'kbdash',   label:'知识来源可辨' },
    { no:2, view:'pipeline', label:'知识变更可追溯' },
    { no:3, view:'dsc',      label:'运行数据可隔离' }
  ];

  // 模块级状态（跨多次进入视图保留）
  const S = {
    built:false, tab:'overview',
    session:null, sessionError:'',
    users:[],
    overview:null, gov:null, govError:'',
    steps:[], stepsLoaded:false, stepsError:'',
    stepIndex:-1, stepResult:null, stepError:'', running:false,
    publish:null, activity:null,
    resetBusy:false
  };

  function $(id){ return document.getElementById(id); }

  // 相对时间（后端时间戳为本地无时区 ISO，可直接 Date 解析）
  function relTime(ts){
    if (!ts) { return '—'; }
    const t = Date.parse(ts);
    if (isNaN(t)) { return DZ.date(ts); }
    const d = Date.now() - t;
    if (d < 0) { return DZ.date(ts); }
    if (d < 60000) { return '刚刚'; }
    const m = Math.floor(d / 60000);
    if (m < 60) { return m + ' 分钟前'; }
    const h = Math.floor(m / 60);
    if (h < 24) { return h + ' 小时前'; }
    const day = Math.floor(h / 24);
    if (day < 30) { return day + ' 天前'; }
    return DZ.date(ts);
  }

  // 从 "未闭环 3" 这类子串中提取数字
  function numIn(s){
    const m = String(s == null ? '' : s).match(/-?\d+/);
    return m ? Number(m[0]) : null;
  }

  // KPI 着色：按业务语义派生 kind（ok/warn/bad）
  function kpiKind(k){
    const key = k && k.key;
    switch (key){
      case 'findings': {
        const n = numIn(k.sub);
        return (n != null && n > 0) ? 'bad' : 'ok';
      }
      case 'proposals':
      case 'hitl': {
        const n = numIn(k.sub);
        return (n != null && n > 0) ? 'warn' : 'ok';
      }
      case 'plugins': {
        const m = String(k.value).match(/(\d+)\s*\/\s*(\d+)/);
        if (m) { return m[1] === m[2] ? 'ok' : 'bad'; }
        return 'warn';
      }
      default:
        return 'ok';
    }
  }

  // ===================== 页面骨架 =====================
  function buildShell(){
    const r = $(ROOT);
    if (!r) { return; }
    r.innerHTML =
      '<div class="dz-toolbar" id="dsk_toolbar" role="toolbar" aria-label="运行驾驶舱工具栏">' + DZ.skeleton(1) + '</div>' +
      '<div class="dz-kpi-row is-compact" id="dsk_kpi" aria-label="关键指标">' + DZ.skeleton(2) + '</div>' +
      '<div id="dsk_tabs"></div>' +
      // 页签一：运行总览（模块健康与运行保障 + 知识发布现状）
      '<div class="dz-pane" data-pane="overview">' +
        DZ.guide('<b>运行总览</b>：查看各模块健康状态与运行保障、以及知识发布现状。') +
        '<div class="grid2">' +
          '<div class="card" id="dsk_modules"><h3>模块健康与运行保障</h3>' + DZ.skeleton(3) + '</div>' +
          '<div class="card" id="dsk_publish"><h3>知识发布现状</h3>' + DZ.skeleton(2) + '</div>' +
        '</div>' +
      '</div>' +
      // 页签二：一键演示（9 幕全流程）
      '<div class="dz-pane" data-pane="demo" hidden>' +
        DZ.guide('<b>一键演示</b>：按 9 幕全流程一键走通，用于整体演示。') +
        '<div class="card" id="dsk_scenario"><h3>一键演示 · 9 幕全流程</h3>' + DZ.skeleton(4) + '</div>' +
      '</div>' +
      // 页签三：活动留痕（跨模块活动流）
      '<div class="dz-pane" data-pane="activity" hidden>' +
        DZ.guide('<b>活动留痕</b>：查看跨模块的最近活动流。') +
        '<div class="card" id="dsk_activity"><h3>跨模块活动流</h3>' + DZ.skeleton(5) + '</div>' +
      '</div>';
  }

  function buildTabs(){
    DZ.tabs('#dsk_tabs', TABS, S.tab, function(k){ switchTab(k); });
  }

  function switchTab(k){
    S.tab = k;
    const r = $(ROOT);
    if (!r) { return; }
    r.querySelectorAll('.dz-pane').forEach(function(p){
      p.hidden = (p.getAttribute('data-pane') !== k);
    });
    buildTabs();
  }

  // ===================== 顶部工具栏（演示动作；身份信息统一收口右上角账户入口） =====================
  function renderToolbar(){
    const el = $('dsk_toolbar');
    if (!el) { return; }
    el.innerHTML =
      '<button id="dsk_demo_go" title="打开一键演示并逐步执行 9 幕全流程" aria-label="一键演示">一键演示</button>' +
      '<button class="ghost" id="dsk_reset" title="幂等重播全部合成脱敏演示数据" aria-label="重置演示数据">重置演示数据</button>';
    bindToolbar();
  }

  function bindToolbar(){
    DZ.on('#dsk_demo_go', 'click', function(){
      switchTab('demo');
      const box = $('dsk_scenario');
      if (box && typeof box.scrollIntoView === 'function'){ box.scrollIntoView({ block:'nearest' }); }
    });
    DZ.on('#dsk_reset', 'click', doReset);
  }

  async function doReset(){
    if (S.resetBusy) { return; }
    if (!window.confirm('确认重置演示数据？将以幂等方式重播全部合成脱敏数据（不影响已实现功能）。')) { return; }
    S.resetBusy = true;
    const btn = $('dsk_reset');
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    const r = await DZ.post('/api/demo/reset');
    await DZ.delay(300 + Math.floor(Math.random() * 400));   // 300–700ms 处理中反馈
    S.resetBusy = false;
    if (!r || r.error){
      DZ.toast('重置失败：' + ((r && r.error && r.error.message) || '未知错误'), 'bad');
      renderToolbar();
      return;
    }
    DZ.toast('演示数据已重置（版本 ' + (r.version || '-') + '）', 'ok');
    S.stepIndex = -1; S.stepResult = null; S.stepError = '';
    loadAll();                                               // 刷新本页
  }

  // ===================== KPI 指标行 =====================
  function renderKpi(){
    const el = $('dsk_kpi');
    if (!el) { return; }
    const o = S.overview;
    if (o && o.error){
      el.innerHTML = DZ.banner('bad', '概览取数失败：' + (o.error.message || '未知错误'), loadOverview);
      return;
    }
    if (!o){ el.innerHTML = DZ.skeleton(2); return; }
    const kpi = o.kpi || [];
    if (!kpi.length){
      el.innerHTML = DZ.empty('暂无指标数据', '<button class="ghost" id="dsk_kpi_retry" title="重新取数">重试</button>');
      DZ.on('#dsk_kpi_retry', 'click', loadOverview);
      return;
    }
    el.innerHTML = kpi.map(function(k){
      return DZ.kpi(k.label, k.value, k.sub, kpiKind(k));
    }).join('');
  }

  // ===================== 一键演示（9 幕） =====================
  function renderScenario(){
    const el = $('dsk_scenario');
    if (!el) { return; }
    if (!S.stepsLoaded){
      el.innerHTML = '<h3>一键演示 · 9 幕全流程</h3>' +
        (S.stepsError ? DZ.banner('bad', '演示脚本加载失败：' + S.stepsError, loadSteps) : DZ.skeleton(4));
      return;
    }
    const total = S.steps.length || 9;

    // 步骤条：可点击单独回放
    let steps = '<ol class="dz-steps" aria-label="一键演示步骤条">';
    for (let i = 0; i < total; i++){
      const st = S.steps[i] || { step:i, title:'第 ' + (i + 1) + ' 幕', desc:'' };
      const cls = 'dz-step' + (i === S.stepIndex ? ' on' : (S.stepIndex >= 0 && i < S.stepIndex ? ' done' : ''));
      steps += '<li class="' + cls + '" data-step="' + i + '" role="button" tabindex="0" ' +
        'title="单独回放：' + DZ.esc(st.desc || st.title) + '" ' +
        'aria-label="回放第 ' + (i + 1) + ' 幕：' + DZ.esc(st.title) + '">' +
        '<span class="dz-step-no">' + (i + 1) + '</span><span>' + DZ.esc(st.title) + '</span></li>';
    }
    steps += '</ol>';

    // 控制按钮
    let controls;
    if (S.running){
      controls = '<button disabled title="执行中">执行中…</button>';
    } else if (S.stepIndex < 0){
      controls = '<button id="dsk_run" data-step="0" title="开始 9 幕全流程演示">开始演示</button>';
    } else if (S.stepIndex < total - 1){
      controls = '<button id="dsk_run" data-step="' + (S.stepIndex + 1) + '" title="执行下一幕">下一步</button>' +
        ' <button class="ghost" id="dsk_restart" title="从头开始演示">重新开始</button>';
    } else {
      controls = DZ.badge('ok', '演示完成') +
        ' <button class="ghost" id="dsk_restart" title="从头开始演示">重新开始</button>';
    }

    // 详情（时间线 + 结果 + 产物）
    let detail;
    if (S.running){
      detail = DZ.skeleton(4);
    } else if (S.stepError){
      detail = DZ.banner('bad', '第 ' + (S.stepIndex + 1) + ' 幕执行失败：' + S.stepError,
        function(){ runStep(S.stepIndex); });
    } else if (!S.stepResult){
      detail = DZ.empty('尚未开始演示：点击「开始演示」逐步走查，或点任意一幕单独回放。');
    } else {
      const r = S.stepResult;
      const logs = (r.logs || []).map(function(lg, idx){
        return '<li class="dz-tl-item"><div class="dz-tl-time">日志 ' + (idx + 1) + '</div>' +
          '<div class="dz-tl-title">' + DZ.esc(lg) + '</div></li>';
      }).join('') || '<li class="muted">无日志</li>';
      const arts = Object.keys(r.artifacts || {}).map(function(k){
        return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
          '<span class="dz-metric-v"><code>' + DZ.esc(String(r.artifacts[k])) + '</code></span></div>';
      }).join('');
      detail =
        '<div class="row" style="margin-bottom:8px">' +
          DZ.badge('ok', '第 ' + ((r.step || 0) + 1) + ' 幕') +
          '<b>' + DZ.esc(r.title || '') + '</b>' + DZ.statusBadge(r.status) +
        '</div>' +
        '<h4>执行日志</h4><ul class="dz-tl">' + logs + '</ul>' +
        '<h4>结果</h4><div class="dz-contract">' + DZ.esc(JSON.stringify(r.result, null, 2)) + '</div>' +
        (arts ? '<h4>产物 / 接口</h4>' + arts : '');
    }

    el.innerHTML = '<h3>一键演示 · ' + total + ' 幕全流程</h3>' +
      steps +
      '<div class="row" style="margin-bottom:12px">' + controls + '</div>' +
      detail;

    // 事件绑定
    DZ.on('#dsk_scenario .dz-step', 'click', function(){ runStep(Number(this.getAttribute('data-step'))); });
    DZ.on('#dsk_scenario .dz-step', 'keydown', function(e){
      if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); runStep(Number(this.getAttribute('data-step'))); }
    });
    DZ.on('#dsk_run', 'click', function(){ runStep(Number(this.getAttribute('data-step'))); });
    DZ.on('#dsk_restart', 'click', function(){
      S.stepIndex = -1; S.stepResult = null; S.stepError = '';
      renderScenario();
    });
  }

  async function runStep(i){
    if (S.running) { return; }
    if (!(i >= 0)) { return; }
    S.running = true; S.stepError = ''; S.stepIndex = i;
    renderScenario();
    const r = await DZ.post('/api/demo/scenario/run', { step:i });
    S.running = false;
    if (!r || r.error){
      S.stepError = (r && r.error && r.error.message) || '未知错误';
      renderScenario();
      return;
    }
    S.stepResult = r;
    renderScenario();
  }

  // ===================== 知识发布现状小卡 =====================
  function renderPublish(){
    const el = $('dsk_publish');
    if (!el) { return; }
    const p = S.publish;
    if (p && p.error){
      el.innerHTML = '<h3>知识发布现状</h3>' +
        DZ.banner('bad', '取数失败：' + (p.error.message || '未知错误'), loadPublish);
      return;
    }
    if (!p){ el.innerHTML = '<h3>知识发布现状</h3>' + DZ.skeleton(2); return; }

    const run = p.run;
    let body;
    if (!run){
      body = DZ.empty('暂无重建作业记录', '<button class="ghost" id="dsk_pub_go" title="跳转到知识发布视图">前往知识发布</button>');
    } else {
      const running = run.status === 'running';
      const idx = (!running && (run.status === 'success' || run.stage === '已完成')) ? 4 : (run.stageIndex || 0);
      const pct = running ? Math.round(((idx + 1) / 4) * 100) : (run.status === 'success' ? 100 : Math.round((idx / 4) * 100));
      body =
        '<div class="row" style="justify-content:space-between">' +
          '<div>' + DZ.statusBadge(run.status) + ' <b>作业编号 ' + DZ.esc(run.runId || '') + '</b></div>' +
          '<span class="pill" title="当前发布版本">当前版本 ' + DZ.esc(p.currentVersion || '-') + '</span>' +
        '</div>' +
        '<div class="dz-metric"><span class="dz-metric-k">阶段</span><span class="dz-metric-v">' + DZ.esc(run.stage || '-') + '</span></div>' +
        '<div style="margin:8px 0">' + DZ.bar(pct) + '</div>' +
        '<div class="dz-metric"><span class="dz-metric-k">变更文档</span><span class="dz-metric-v">' + DZ.number(run.changedDocs) + ' / ' + DZ.number(run.totalDocs) + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">触发方式 / 重建模式</span><span class="dz-metric-v">' + DZ.esc(TRIGGER_LABEL[run.trigger] || run.trigger || '-') + ' / ' + DZ.esc(MODE_LABEL[run.mode] || run.mode || '-') + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">耗时</span><span class="dz-metric-v">' + (run.durationMs != null ? DZ.number(run.durationMs) + ' 毫秒' : '—') + '</span></div>' +
        (run.error ? '<div class="muted" style="color:var(--bad-ink)">错误：' + DZ.esc(run.error) + '</div>' : '') +
        '<div class="row" style="margin-top:12px"><button class="ghost" id="dsk_pub_go" title="跳转到知识发布视图" aria-label="查看知识发布">查看知识发布 →</button></div>';
    }
    el.innerHTML = '<h3>知识发布现状</h3>' + body;
    DZ.on('#dsk_pub_go', 'click', function(){ goView('pipeline'); });
  }

  // ===================== 模块健康与运行保障 =====================
  function renderModules(){
    const el = $('dsk_modules');
    if (!el) { return; }
    const o = S.overview;
    if (o && o.error){
      el.innerHTML = '<h3>模块健康与运行保障</h3>' +
        DZ.banner('bad', '取数失败：' + (o.error.message || '未知错误'), loadOverview);
      return;
    }

    let health;
    if (!o){ health = DZ.skeleton(3); }
    else {
      health = (o.modules || []).map(function(m){
        const h = HEALTH[m.health] || HEALTH.unk;
        return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(m.label) + '</span>' +
          '<span class="dz-metric-v">' + DZ.badge(h[0], h[1]) +
          ' <span class="muted">' + DZ.esc(m.detail || '') + '</span></span></div>';
      }).join('') || DZ.empty('暂无模块健康数据');
    }

    let rates;
    if (S.gov){
      const over = Number(S.gov.degradeRate) > 0.2;
      rates = '<div class="row" style="gap:18px;margin:10px 0">' +
        '<span class="dz-sla ok" title="知识来源命中率">来源命中率 ' + DZ.confidence(S.gov.sourceHitRate) + '</span>' +
        '<span class="dz-sla ' + (over ? 'over' : 'ok') + '" title="知识/插件降级率">降级率 ' + DZ.confidence(S.gov.degradeRate) + '</span>' +
        '<span class="dz-sla" title="工具调用量">工具调用 ' + DZ.number(S.gov.mcpCalls) + '</span>' +
      '</div>';
    } else if (S.govError){
      rates = DZ.banner('bad', '治理看板取数失败：' + S.govError, loadGov);
    } else {
      rates = DZ.skeleton(1);
    }

    const rl = REDLINES.map(function(x){
      return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(x.label) + '</span>' +
        '<span class="dz-metric-v">' + DZ.badge('ok', '正常') +
        ' <button class="ghost" data-view="' + DZ.esc(x.view) + '" ' +
        'aria-label="查看：' + DZ.esc(x.label) + '">查看</button></span></div>';
    }).join('');

    el.innerHTML = '<h3>模块健康与运行保障</h3>' +
      '<h4>模块健康</h4>' + health + rates +
      '<h4>运行保障</h4>' + rl;

    DZ.on('#dsk_modules button[data-view]', 'click', function(){ goView(this.getAttribute('data-view')); });
  }

  // ===================== 跨模块活动流 =====================
  function renderActivity(){
    const el = $('dsk_activity');
    if (!el) { return; }
    const a = S.activity;
    if (a && a.error){
      el.innerHTML = '<h3>跨模块活动流</h3>' +
        DZ.banner('bad', '取数失败：' + (a.error.message || '未知错误'), loadActivity);
      return;
    }
    if (!a){ el.innerHTML = '<h3>跨模块活动流</h3>' + DZ.skeleton(5); return; }

    const items = a.activity || [];
    if (!items.length){
      el.innerHTML = '<h3>跨模块活动流</h3>' + DZ.empty('暂无活动记录');
      return;
    }
    const tl = items.map(function(it){
      const kb = KIND_MAP[it.kind] || ['unk', it.kind || '事件'];
      const res = RESULT_MAP[String(it.result == null ? '' : it.result).toLowerCase()];
      const resHtml = res ? DZ.badge(res[0], res[1]) : (it.result ? DZ.badge('unk', String(it.result)) : '');
      return '<li class="dz-tl-item">' +
        '<div class="dz-tl-time" title="' + DZ.esc(DZ.date(it.ts)) + '">' + DZ.esc(relTime(it.ts)) + ' · ' + DZ.esc(DZ.date(it.ts)) + '</div>' +
        '<div class="dz-tl-title">' + DZ.badge(kb[0], kb[1]) + ' ' +
          DZ.esc((it.kind === 'audit' ? DZ.actionLabel(it.title) : it.title) || '') + ' ' + resHtml + '</div>' +
        '<div class="muted">' + DZ.esc(it.actorName || it.actor || '—') +
          (it.detail ? ' · ' + DZ.esc(it.detail) : '') + '</div>' +
      '</li>';
    }).join('');
    el.innerHTML = '<h3>跨模块活动流 <span class="muted" style="font-weight:400">（最近 ' + items.length + ' 条 · 按时间倒序）</span></h3>' +
      '<ul class="dz-tl">' + tl + '</ul>';
  }

  // 跳转到指定视图（复用全局 showView，不重复实现对应视图）
  function goView(id){
    if (typeof window.showView === 'function'){
      try { window.showView(id); return; } catch(e){ /* 忽略 */ }
    }
    DZ.toast('无法打开视图：' + id, 'bad');
  }

  // ===================== 数据加载 =====================
  async function loadSession(){
    renderToolbar();
    const res = await Promise.all([
      DZ.get('/api/auth/session'),
      DZ.get('/api/admin/users')
    ]);
    const sess = res[0], users = res[1];
    S.session = (sess && sess.error) ? null : sess;
    S.sessionError = (sess && sess.error) ? (sess.error.message || '未知错误') : '';
    S.users = (users && users.users) ? users.users : [];
    renderToolbar();
  }

  async function loadOverview(){
    S.overview = null;
    renderKpi(); renderModules();
    const r = await DZ.get('/api/demo/overview');
    S.overview = r;
    if (r && !r.error && r.session && !S.session){ S.session = r.session; }
    renderKpi(); renderModules(); renderToolbar();
  }

  async function loadSteps(){
    renderScenario();
    const r = await DZ.get('/api/demo/scenario/steps');
    if (!r || r.error){
      S.stepsError = (r && r.error && r.error.message) || '未知错误';
      renderScenario();
      return;
    }
    S.stepsError = '';
    S.steps = r.steps || [];
    S.stepsLoaded = true;
    renderScenario();
  }

  async function loadPublish(){
    renderPublish();
    const r = await DZ.get('/api/kb/publish/status');
    S.publish = r;
    renderPublish();
  }

  async function loadGov(){
    S.gov = null;
    S.govError = '';
    renderModules();
    const r = await DZ.get('/api/admin/gov-dashboard');
    if (!r || r.error){
      S.govError = (r && r.error && r.error.message) || '未知错误';
      S.gov = null;
    } else {
      S.gov = r;
    }
    renderModules();
  }

  async function loadActivity(){
    S.activity = null;
    renderActivity();
    const r = await DZ.get('/api/demo/activity?limit=30');
    S.activity = r;
    renderActivity();
  }

  function loadAll(){
    loadSession();
    loadOverview();
    loadSteps();
    loadPublish();
    loadGov();
    loadActivity();
  }

  // ===================== 视图注册 =====================
  function init(){
    const r = $(ROOT);
    if (!r) { return; }
    if (!S.built){ buildShell(); S.built = true; }
    switchTab(S.tab || 'overview');
    loadAll();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['dsk'] = init;
})();
