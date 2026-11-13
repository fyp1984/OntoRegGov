/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo 公共层（demo_common.js）
   提供全局 window.DZ 命名空间：取数封装 / 组件生成 / 视图装载 / 全局兜底。
   依赖：app.js 已定义 showView / esc / srcBar / SRC_LABEL / api（本文件不改 app.js）。
   ============================================================ */
(function(){
  'use strict';

  const DZ = {};
  window.DZ = DZ;

  // 与 app.js 保持一致的来源语义（知识取数"来源可辨"）
  const SRC_LABEL = {weknora:'知识库实时', canonical:'正本图', db:'结构化投影', sqlite:'运行台账', none:'来源不可用'};
  DZ.SRC_LABEL = SRC_LABEL;

  // ---------- 基础工具 ----------
  DZ.esc = function(s){
    return String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  };

  DZ.delay = function(ms){ return new Promise(r => setTimeout(r, ms||0)); };

  // ---------- 取数封装：~400ms 基础延迟；失败统一错误信封 ----------
  DZ.api = async function(path, opt){
    opt = opt || {};
    if (opt.delay !== false) await DZ.delay(400);
    try {
      const r = await fetch(path, opt);
      let data = null;
      try { data = await r.json(); } catch(e){ data = null; }
      if (!r.ok){
        if (data && data.error) return data;                 // 后端错误信封
        return {error:{code:'HTTP_'+r.status,
          message:(data && (data.message||data.detail)) || ('请求失败（HTTP '+r.status+'）'),
          details:{}}, traceId:(data && data.traceId) || ''};
      }
      return data;
    } catch(e){
      return {error:{code:'NETWORK', message:'网络不可达：'+((e&&e.message)||e), details:{}}, traceId:''};
    }
  };
  const _json = {headers:{'Content-Type':'application/json'}};
  DZ.get   = function(path, opt){ return DZ.api(path, Object.assign({method:'GET'}, opt||{})); };
  DZ.post  = function(path, body){ return DZ.api(path, Object.assign({method:'POST',  body:JSON.stringify(body||{})}, _json)); };
  DZ.patch = function(path, body){ return DZ.api(path, Object.assign({method:'PATCH', body:JSON.stringify(body||{})}, _json)); };
  DZ.put   = function(path, body){ return DZ.api(path, Object.assign({method:'PUT',   body:JSON.stringify(body||{})}, _json)); };
  DZ.del   = function(path){ return DZ.api(path, Object.assign({method:'DELETE'}, _json)); };

  // ---------- 徽章 / 标签 ----------
  const BADGE = {ok:'b-ok', warn:'b-warn', bad:'b-bad', unk:'b-unk', p0:'b-p0', p1:'b-p1', p2:'b-p2'};
  DZ.badge = function(kind, text){
    return '<span class="badge '+(BADGE[kind]||'b-unk')+'">'+DZ.esc(text)+'</span>';
  };
  DZ.pill = function(text){ return '<span class="pill">'+DZ.esc(text)+'</span>'; };

  // ---------- 骨架屏 ----------
  DZ.skeleton = function(rows){
    let n = typeof rows === 'number' ? rows : (Array.isArray(rows) ? rows.length : 3);
    if (!n || n < 1) n = 3;
    let html = '<div class="dz-skeleton">';
    for (let i=0;i<n;i++){
      const w = 55 + ((i*17)%40);       // 55%~95% 宽度，错落有致
      html += '<div class="dz-skeleton-row"><span class="dz-sk-bar" style="width:'+w+'%"></span></div>';
    }
    return html + '</div>';
  };

  // ---------- 空态 ----------
  DZ.empty = function(text, actionHtml){
    return '<div class="dz-empty"><div class="dz-empty-title">'+DZ.esc(text||'暂无数据')+'</div>'+
      (actionHtml ? '<div class="dz-actions">'+actionHtml+'</div>' : '')+'</div>';
  };

  // ---------- 提示条（可带重试） ----------
  let _retrySeq = 0;
  const _retryHandlers = {};
  DZ.__retry = function(id){ const f = _retryHandlers[id]; if (typeof f === 'function') f(); };
  DZ.banner = function(kind, text, retryFn){
    const cls = kind === 'bad' ? 'dz-banner bad' : (kind === 'warn' ? 'dz-banner warn' : 'dz-banner');
    let btn = '';
    if (typeof retryFn === 'function'){
      const id = 'dzr' + (++_retrySeq);
      _retryHandlers[id] = retryFn;
      btn = '<button class="ghost dz-banner-retry" onclick="DZ.__retry(\''+id+'\')">重试</button>';
    }
    return '<div class="'+cls+'" role="alert"><span class="dz-banner-text">'+DZ.esc(text||'')+'</span>'+btn+'</div>';
  };

  // ---------- 右下角轻提示（自动淡出） ----------
  DZ.toast = function(text, kind){
    let box = document.getElementById('dz_toast_box');
    if (!box){
      box = document.createElement('div');
      box.id = 'dz_toast_box';
      document.body.appendChild(box);
    }
    const el = document.createElement('div');
    el.className = 'dz-toast' + (kind==='ok'?' ok':kind==='warn'?' warn':kind==='bad'?' bad':'');
    el.setAttribute('role', 'status');
    el.textContent = String(text==null?'':text);
    box.appendChild(el);
    setTimeout(function(){ el.classList.add('out'); }, 2600);
    setTimeout(function(){ if (el.parentNode) el.parentNode.removeChild(el); }, 3200);
  };

  // ---------- 进度条 ----------
  DZ.bar = function(pct){
    let v = Number(pct); if (!isFinite(v)) v = 0;
    v = Math.max(0, Math.min(100, Math.round(v)));
    return '<div class="dz-bar" role="progressbar" aria-valuenow="'+v+'" aria-valuemin="0" aria-valuemax="100"><i style="width:'+v+'%"></i></div>';
  };

  // ---------- KPI 指标卡 ----------
  DZ.kpi = function(label, value, sub, kind){
    return '<div class="dz-kpi'+(kind?' k-'+kind:'')+'">'+
      '<div class="dz-kpi-label">'+DZ.esc(label)+'</div>'+
      '<div class="dz-kpi-value">'+DZ.esc(value)+'</div>'+
      (sub ? '<div class="dz-kpi-sub">'+DZ.esc(sub)+'</div>' : '')+'</div>';
  };

  // ---------- 格式化 ----------
  DZ.number = function(n, digits){
    if (n==null || n==='') return '—';
    const v = Number(n);
    if (!isFinite(v)) return String(n);
    const opt = digits==null ? {} : {minimumFractionDigits:digits, maximumFractionDigits:digits};
    return v.toLocaleString('zh-CN', opt);
  };
  DZ.money = function(n, digits){
    if (n==null || n==='') return '—';
    const v = Number(n);
    if (!isFinite(v)) return String(n);
    const d = digits==null ? 2 : digits;
    return '¥' + v.toLocaleString('zh-CN', {minimumFractionDigits:d, maximumFractionDigits:d});
  };
  DZ.date = function(s){
    if (s==null || s==='') return '—';
    return String(s).replace('T',' ').replace(/\.\d+$/,'').replace(/(Z|[+-]\d{2}:?\d{2})$/,'').trim();
  };

  // ---------- 段落标题 ----------
  DZ.sectionTitle = function(text){ return '<h3 class="dz-section-title">'+DZ.esc(text)+'</h3>'; };

  // ---------- 来源徽章 + 取数时间 ----------
  DZ.srcBar = function(env, extra){
    const s = (env && env.source) || 'none';
    const ok = s !== 'none';
    const t = ((env && env.fetchedAt) || '').replace('T',' ');
    return '<span class="dz-srcbar"><span class="badge b-'+(ok?'ok':'bad')+'">'+
      DZ.esc(SRC_LABEL[s]||s)+'</span><span class="muted">取数 '+(t||'—')+
      (extra ? '｜'+extra : '')+'</span></span>';
  };

  // ---------- 语义徽章 ----------
  const RESULT = {pass:['ok','符合'], partial:['warn','部分符合'], fail:['bad','不符合'], supplement:['unk','需补充']};
  DZ.resultBadge = function(r){ const m = RESULT[r] || ['unk', r||'—']; return DZ.badge(m[0], m[1]); };

  const SEV = {high:['bad','高'], medium:['warn','中'], low:['unk','低']};
  DZ.severityBadge = function(s){ const m = SEV[s] || ['unk', s||'—']; return DZ.badge(m[0], m[1]); };

  const STATUS = {
    draft:['unk','草稿'], pending:['warn','待处理'], in_progress:['warn','进行中'],
    running:['warn','进行中'], open:['bad','待处理'], new:['warn','新建'],
    review:['warn','待审核'], submitted:['warn','已提交'], dispatched:['warn','已下发'],
    approved:['ok','已通过'], success:['ok','成功'], succeeded:['ok','成功'],
    closed:['ok','已关闭'], done:['ok','已完成'], completed:['ok','已完成'], active:['ok','启用'],
    rejected:['bad','已驳回'], failed:['bad','失败'], returned:['warn','已退回'],
    disabled:['unk','已停用'], inactive:['unk','未启用'],
    '发现':['bad','发现'], '已分派':['warn','已分派'], '整改中':['warn','整改中'],
    '待复检':['warn','待复检'], '通过':['ok','通过'], '关闭':['ok','关闭'],
    '待处理':['warn','待处理'], '待审核':['warn','待审核'], '已通过':['ok','已通过'],
    '已驳回':['bad','已驳回'], '部分符合':['warn','部分符合'], '需补充':['unk','需补充'],
    '在册':['ok','在册'], '已归档':['unk','已归档'], '已接入':['ok','已接入'], '已停用':['unk','已停用'],
    '推进中':['warn','推进中'], '已闭环':['ok','已闭环'], '未开始':['unk','未开始'], '已完成':['ok','已完成'],
    '已对上':['ok','已对上'], '部分对上':['warn','部分对上'], '未对上':['bad','未对上'],
    '已指派':['ok','已指派']
  };
  DZ.statusBadge = function(status){
    const k = String(status==null?'':status);
    const m = STATUS[k] || STATUS[k.toLowerCase()] || ['unk', k || '—'];
    return DZ.badge(m[0], m[1]);
  };

  // ---------- 审计动作中文名（页面语言统一：不直接暴露英文动作码） ----------
  // 后端审计 action 保持机器可读（审计链路不因展示而改动），仅在界面呈现时翻译。
  const ACTION_LABEL = {
    'auth.login':'登录','auth.logout':'退出登录',
    'role.update':'角色更新','role.binding.create':'新增角色绑定',
    'kb.publish':'知识发布','kb.publish.start':'发起知识重建','kb.fetch':'知识取数',
    'kb.collect.run':'知识采集','kb.rollback':'版本回滚','kb.collect.decision':'采集决策',
    'demo.reset':'演示数据重置','demo.fault':'错误信封演示','demo.fault.switch':'故障开关切换',
    'demo.scenario.run':'一键演示执行',
    'selfcheck.create':'创建自查任务','selfcheck.view':'查看自查任务','selfcheck.report':'导出自查报告',
    'selfcheck.item.update':'登记检查项','selfcheck.signoff':'复核签署',
    'assignment.preview':'责任映射预览','assignment.dispatch':'责任下发','assignment.override':'责任覆盖',
    'evidence.upload':'上传证据',
    'finding.create':'登记问题','remediation.create':'创建整改任务','remediation.update':'更新整改任务',
    'recheck.run':'发起复检',
    'proposal.create':'创建知识提案','review.proposal':'提案审核','review.decision':'提案决策',
    'hitl.decide':'人工确认决策',
    'admin.doc.register':'登记文号','admin.doc.confirm':'确认文号结构','admin.user.status':'启用/停用账号',
    'admin.org.create':'新增组织节点','admin.rule.update':'更新分配规则','admin.audit.export':'导出审计记录',
    'settings.retention.update':'更新数据保存策略','settings.retention.reset':'恢复默认数据保存策略',
    'scenario.create':'创建场景包','scenario.launch':'启动场景包','plugin.invoke':'插件调用',
    'diag.assessment.create':'创建诊断批次','diag.answer.save':'保存诊断作答','diag.assessment.submit':'提交现状诊断',
    'ledger.row.create':'登记对账行','ledger.row.update':'更新对账行','ledger.row.delete':'移除对账行',
    'issue.disposal.create':'创建处置工单','issue.disposal.assign':'指派处置责任','issue.disposal.advance':'推进处置工单',
    'issue.disposal.close':'关闭处置工单','issue.disposal.delete':'移除处置工单',
    'frame.case.create':'新建闭合链案件','frame.ring.record':'登记闭合链环节',
    'arch.module.create':'登记层模块','arch.module.update':'更新层模块','arch.module.delete':'移除层模块',
    'capability.instance.create':'登记能力实例','capability.instance.update':'更新能力实例','capability.instance.delete':'移除能力实例',
    'path.gate.check':'判定转段判据','path.stage.advance':'实施阶段转段',
    'asset.create':'登记留存资产','asset.archive':'归档留存资产','asset.delete':'移除留存资产'
  };
  DZ.actionLabel = function(code){ return ACTION_LABEL[code] || code || '—'; };
  // 反向查：把界面上的中文动作名还原为后端动作码（用于审计筛选）
  DZ.actionCode = function(v){
    const s = String(v == null ? '' : v).trim();
    for (const k in ACTION_LABEL){ if (ACTION_LABEL[k] === s) return k; }
    return s;
  };

  // ---------- 置信度可视化 ----------
  DZ.confidence = function(v){
    let n = Number(v);
    if (!isFinite(n)) return '<span class="muted">—</span>';
    if (n <= 1) n = n * 100;
    n = Math.round(n);
    const cls = n >= 80 ? 'ok' : (n >= 60 ? 'warn' : 'bad');
    return DZ.badge(cls, n + '%');
  };

  // ---------- DOM 便捷 ----------
  DZ.render = function(sel, html){
    const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
    if (el) el.innerHTML = html;
    return el;
  };
  DZ.on = function(sel, event, fn){
    const list = typeof sel === 'string' ? document.querySelectorAll(sel) : [sel];
    list.forEach(function(el){ if (el) el.addEventListener(event, fn); });
  };
  DZ.debounce = function(fn, ms){
    let t;
    return function(){
      const ctx = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function(){ fn.apply(ctx, args); }, ms||250);
    };
  };

  // ---------- 选项卡 ----------
  DZ.tabs = function(container, items, activeKey, onSwitch){
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el) return;
    el.className = 'dz-tabs';
    el.innerHTML = (items||[]).map(function(it){
      const isObj = it && typeof it === 'object';
      const key = isObj ? it.key : it;
      const label = isObj ? (it.label || it.text || it.key) : it;
      const count = isObj && it.count != null ? it.count : null;
      const on = key === activeKey;
      return '<button class="dz-tab'+(on?' on':'')+'" data-key="'+DZ.esc(key)+'" title="'+DZ.esc(label)+'">'+
        DZ.esc(label)+(count!=null?' <span class="dz-tab-count">'+DZ.esc(count)+'</span>':'')+'</button>';
    }).join('');
    el.querySelectorAll('.dz-tab').forEach(function(b){
      b.onclick = function(){
        el.querySelectorAll('.dz-tab').forEach(function(x){ x.classList.remove('on'); });
        b.classList.add('on');
        if (typeof onSwitch === 'function') onSwitch(b.dataset.key);
      };
    });
  };

  // ---------- 视图装载机制 ----------
  // 每个模块 JS 注册 window.DEMO_VIEW_INIT['x']；showView 切换到该视图时触发。

  // 视图元信息：所属分组（与左侧菜单分组一致）+ 页面标题。
  // 门楣只承载"当前位置"这一导航信息：不放模块编号，也不放功能介绍文字。
  const VIEW_META = {
    dsc:      {group:'自查与报告', title:'安全自查'},
    rep:      {group:'自查与报告', title:'报告与看板'},
    diag:     {group:'诊断与治理', title:'现状诊断'},
    ledger:   {group:'诊断与治理', title:'应用与业务层台账'},
    issues:   {group:'诊断与治理', title:'逐类问题处置'},
    rem:      {group:'整改闭环', title:'整改与复检'},
    kbdash:   {group:'知识底座', title:'知识库'},
    pipeline: {group:'知识底座', title:'知识发布'},
    ext:      {group:'能力与接入', title:'场景与插件'},
    capability: {group:'能力与接入', title:'能力域目录'},
    gov:      {group:'平台与治理', title:'权限与组织'},
    dsk:      {group:'平台与治理', title:'运行驾驶舱'},
    frame:    {group:'平台与治理', title:'治理框架'},
    arch:     {group:'平台与治理', title:'平台架构'},
    path:     {group:'实施与资产', title:'实施路径'},
    assets:   {group:'实施与资产', title:'留存资产'}
  };
  DZ.VIEW_META = VIEW_META;

  // 页面头：注入到视图 section 顶部（每视图仅一次）。无元信息的视图（如设置）不注入。
  function ensurePageHead(id){
    const view = document.getElementById(id);
    if (!view || !VIEW_META[id]) return;
    if (view.querySelector(':scope > .dz-pagehead')) return;
    const meta = VIEW_META[id];
    const head = document.createElement('div');
    head.className = 'dz-pagehead';
    head.setAttribute('data-v', id);
    head.innerHTML =
      '<div class="dz-crumb" role="navigation" aria-label="当前位置">' +
        '<span class="dz-crumb-group">' + DZ.esc(meta.group) + '</span>' +
        '<span class="dz-crumb-sep" aria-hidden="true">›</span>' +
        '<h2 class="dz-pagehead-title">' + DZ.esc(meta.title) + '</h2>' +
      '</div>';
    view.insertBefore(head, view.firstChild);
  }
  DZ.ensurePageHead = ensurePageHead;

  function runDemoView(id){
    const init = window.DEMO_VIEW_INIT && window.DEMO_VIEW_INIT[id];
    if (typeof init !== 'function') return;
    const view = document.getElementById(id);
    if (!view) return;
    ensurePageHead(id);
    const box = document.getElementById(id + '_root');
    // 首次进入先渲染骨架屏占位（各模块 JS 随后覆盖）
    if (!view.dataset.inited && box && !box.innerHTML.trim()){
      box.innerHTML = DZ.skeleton(4);
    }
    view.dataset.inited = '1';
    try { init(); }
    catch(e){ DZ.toast('视图渲染异常：'+((e&&e.message)||e), 'bad'); }
  }
  DZ.runDemoView = runDemoView;

  function installShowView(){
    if (typeof window.showView !== 'function') return false;
    if (window.showView.__dzWrapped) return true;
    const _origShowView = window.showView;
    const wrapped = function(id){
      const r = _origShowView.apply(this, arguments);
      // 页面头与视图初始化解耦：知识库等由独立模块渲染的视图没有 DEMO_VIEW_INIT，也要有统一页面头
      try { ensurePageHead(id); } catch(e){ /* 兜底 */ }
      try { runDemoView(id); } catch(e){ /* 兜底：不影响原视图 */ }
      return r;
    };
    wrapped.__dzWrapped = true;
    window.showView = wrapped;
    return true;
  }

  // 优先直接接管（demo_common.js 在 app.js 之后加载）；
  // 若脚本顺序异常（showView 尚未定义），用 DOMContentLoaded 兜底包裹。
  if (!installShowView()){
    document.addEventListener('DOMContentLoaded', function(){ installShowView(); });
  }

  // 首次加载兜底：默认视图未经 showView 切换，主动为该视图注入统一页面头。
  function injectInitialPageHead(){
    const active = document.querySelector('main > section.view:not(.hidden)');
    if (active && active.id) ensurePageHead(active.id);
  }
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', injectInitialPageHead);
  } else {
    injectInitialPageHead();
  }

  // ---------- 全局兜底：避免白屏 ----------
  window.addEventListener('error', function(e){
    try { DZ.toast('运行错误：'+((e && e.message) || (e && e.error && e.error.message) || '未知错误'), 'bad'); } catch(_){}
  });
  window.addEventListener('unhandledrejection', function(e){
    try {
      const r = e && e.reason;
      DZ.toast('异步错误：'+((r && r.message) || r || '未知错误'), 'bad');
    } catch(_){}
  });

  /* ==========================================================================
     数据保存策略（设置页）
     - 设置页承载"保留期限 / 归档期限 / 销毁审批"这几项可配置要求；
       不可配置的合规不变量（证据不可变、哈希链可验、运行态隔离等）同页只读展示。
     - 字段名（taskOnlineCycles 等）保持机器可读，界面文案全部中文。
     ========================================================================== */
  const RETENTION_API = '/api/demo/retention-policy';

  // 表单项：按数据类别分组；每组一个标题 + 若干可配置行
  const RET_GROUPS = [
    { title:'自查任务与结果（运行库）', rows:[
      { key:'taskOnlineCycles', before:'关闭后在线保留', unit:'个核查周期' },
      { key:'taskArchiveYears', before:'归档只读保留', unit:'年' } ]},
    { title:'审计日志（只追加）', rows:[
      { key:'auditOnlineYears', before:'在线保留', unit:'年' },
      { key:'auditArchiveYears', before:'归档保留', unit:'年' } ]},
    { title:'备份（运行库 + 知识库快照）', rows:[
      { key:'backupDays', before:'保留', unit:'天' },
      { key:'backupDrillQuarterly', before:'季度恢复演练', type:'bool' } ]},
    { title:'超期数据销毁', rows:[
      { key:'purgeApprovalLevel', before:'销毁走「申请 → 审批 → 留痕」，审批方式',
        type:'select' } ]}
  ];
  const RET_LIMITS = {
    taskOnlineCycles:[1,12], taskArchiveYears:[1,30], auditOnlineYears:[1,10],
    auditArchiveYears:[1,30], backupDays:[30,730]
  };
  // 只读的合规不变量（不可通过设置页调整）
  const RET_FIXED = [
    ['证据文件', '与所属任务同周期保留 · 存储不可变'],
    ['账号停用后个人数据', '历史任务 / 证据 / 签署 / 审计全部保留'],
    ['哈希链完整性', '前序哈希 → 当前哈希 可验'],
    ['运行态 / 只读知识视图', '数据物理隔离'],
    ['审计追加语义', '只追加、不可改写'],
    ['导出留痕', '导出行为计入审计链路']
  ];

  function retInput(f, v){
    if (f.type === 'select'){
      return '<select data-ret="' + f.key + '" aria-label="超期数据销毁审批方式">' +
        '<option value="dual"' + (v === 'dual' ? ' selected' : '') + '>双人审批</option>' +
        '<option value="single"' + (v === 'single' ? ' selected' : '') + '>单人审批</option>' +
        '</select>';
    }
    if (f.type === 'bool'){
      return '<input type="checkbox" data-ret="' + f.key + '"' + (v ? ' checked' : '') +
             ' aria-label="' + DZ.esc(f.before) + '">';
    }
    const lim = RET_LIMITS[f.key] || [0, 9999];
    return '<input type="number" min="' + lim[0] + '" max="' + lim[1] + '" data-ret="' + f.key +
           '" value="' + DZ.esc(v) + '" aria-label="' + DZ.esc(f.before) + '">';
  }

  function renderRetention(p){
    const el = document.getElementById('retention_form');
    if (!el) return;
    const groups = RET_GROUPS.map(function(g){
      const rows = g.rows.map(function(f){
        return '<div class="ret-row"><span>' + DZ.esc(f.before) + '</span>' +
          retInput(f, p[f.key]) + (f.unit ? '<span>' + DZ.esc(f.unit) + '</span>' : '') + '</div>';
      }).join('');
      return '<div class="ret-group"><div class="ret-group-title">' + DZ.esc(g.title) + '</div>' +
        rows + '</div>';
    }).join('');
    const fixed = RET_FIXED.map(function(x){
      return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(x[0]) +
        '</span><span class="dz-metric-v">' + DZ.esc(x[1]) + '</span></div>';
    }).join('');
    const meta = p.updatedAt
      ? '最近更新：' + DZ.date(p.updatedAt) + (p.updatedBy ? ' · 操作人 ' + DZ.esc(p.updatedBy) : '')
      : '当前为默认策略，尚未调整过。';
    el.className = '';
    el.innerHTML = '<div class="ret-grid">' + groups + '</div>' +
      '<div class="ret-fixed">' + fixed + '</div>' +
      '<div class="muted" style="margin-top:10px">' + meta + '</div>';
  }

  async function retentionLoad(){
    const el = document.getElementById('retention_form');
    if (!el) return;
    el.className = 'muted';
    el.textContent = '加载中…';
    const p = await DZ.get(RETENTION_API, { delay: false });
    if (!p || p.error){
      el.className = 'muted';
      el.innerHTML = '策略不可读取' +
        ' <button class="ghost" onclick="retentionLoad()" title="重试读取数据保存策略">重试</button>';
      return;
    }
    renderRetention(p);
  }
  DZ.retentionLoad = retentionLoad;

  function retStatus(msg, kind){
    const el = document.getElementById('retention_status');
    if (!el) return;
    el.innerHTML = msg ? (kind === 'bad' ? '<span class="badge b-bad">保存失败</span> ' : '') + DZ.esc(msg) : '';
  }

  function collectRetention(){
    const body = {};
    document.querySelectorAll('#retention_form [data-ret]').forEach(function(node){
      const k = node.getAttribute('data-ret');
      if (node.type === 'checkbox') body[k] = node.checked;
      else if (node.tagName === 'SELECT') body[k] = node.value;
      else body[k] = node.value;
    });
    return body;
  }

  window.retentionSave = async function(){
    const body = collectRetention();
    for (const k in RET_LIMITS){
      const [lo, hi] = RET_LIMITS[k];
      const v = Number(body[k]);
      if (!isFinite(v) || v < lo || v > hi){
        retStatus('「' + k + '」需在 ' + lo + '–' + hi + ' 之间', 'bad');
        DZ.toast('保存失败：数值超出允许范围', 'bad');
        return;
      }
    }
    retStatus('保存中…');
    const r = await DZ.put(RETENTION_API, body);
    if (!r || r.error){
      const msg = (r && r.error && r.error.message) || '接口不可达';
      retStatus(msg, 'bad');
      DZ.toast('保存失败：' + msg, 'bad');
      return;
    }
    renderRetention(r);
    retStatus('已保存');
    DZ.toast('数据保存策略已更新，已写入审计留痕', 'ok');
  };

  window.retentionReset = async function(){
    retStatus('恢复中…');
    const r = await DZ.post(RETENTION_API + '/reset');
    if (!r || r.error){
      retStatus('接口不可达', 'bad');
      return;
    }
    renderRetention(r);
    retStatus('已恢复默认策略');
    DZ.toast('已恢复默认数据保存策略', 'ok');
  };

  // 设置页由 app.js 的 showView 触发 loadSettings()，在此挂接策略加载，避免改动 app.js。
  const _loadSettings = window.loadSettings;
  window.loadSettings = function(){
    if (typeof _loadSettings === 'function') _loadSettings.apply(this, arguments);
    try { retentionLoad(); } catch(e){ /* 兜底：不影响设置页其它区块 */ }
  };
  // 首屏若已停留在设置页（直接刷新），补一次加载
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', function(){
      if (document.getElementById('retention_form')) retentionLoad();
    });
  } else if (document.getElementById('retention_form')) {
    retentionLoad();
  }
})();
