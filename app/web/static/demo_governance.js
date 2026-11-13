/* ============================================================
   金融行业数据安全知识库和智能体平台 · 整改与复检视图（demo_governance.js）
   视图 id: rem ｜ 容器: #rem_root

   覆盖能力：
   - L1 问题清单与整改任务（含新增问题 / 创建整改 / 状态流转）
   - L4 复检前后对比（任务级 before/after/delta + 逐项 changed 高亮）
   - L3 经验回流与提案审核（14 类目筛选 / 详情 / 新建 / 审核，含职责分离 403 演示）
   - K1.5 人工确认队列（抽取 / AI 匹配 / 人工判定）

   硬性约束：仅使用 window.DZ.* 与 dz-* 类；颜色/圆角全部复用现有 CSS 变量；
   所有异步先骨架屏、失败给出可重试提示条、无数据渲染空态，绝不出现死路。
   ============================================================ */
(function(){
  'use strict';

  const ROOT = '#rem_root';

  // 整改状态机：后端 status 为自由文本，前端统一归一到 5 个中文态
  const REM_STATES = ['待分派', '整改中', '待复检', '已通过', '已关闭'];
  const REM_KIND = {'待分派':'unk', '整改中':'warn', '待复检':'warn', '已通过':'ok', '已关闭':'ok'};
  // 兼容后端种子里的英文状态
  const REM_ALIAS = {
    assigned:'待分派', open:'待分派', new:'待分派', pending:'待分派',
    in_progress:'整改中', remediating:'整改中', processing:'整改中',
    recheck:'待复检', pending_recheck:'待复检',
    done:'已通过', passed:'已通过', pass:'已通过', approved:'已通过',
    closed:'已关闭', close:'已关闭'
  };

  // 问题状态归一到 DZ.statusBadge 能识别的中文键
  const FINDING_STATUS = {
    remediating:'整改中', assigned:'已分派', passed:'通过', closed:'关闭',
    open:'发现', recheck:'待复检', in_progress:'整改中', done:'通过'
  };
  const TASK_STATUS = {in_progress:'进行中', draft:'草稿', closed:'已关闭', pending:'待处理', running:'进行中'};

  // 回流提案 14 类目
  const PROPOSAL_CATS = ['RA1', 'RA2', 'RA3', 'RB1', 'RB2', 'RB3', 'RB4', 'RB5',
                         'RC1', 'RC2', 'RD1', 'RD2', 'RD3', 'RH1'];
  // 人工确认来源类型
  const HITL_SRC = {extraction:'抽取候选', ai_match:'AI 匹配', manual_judge:'人工判定'};

  // 复核结果强弱序（用于判定改善/恶化）
  const RANK = {pass:3, partial:2, supplement:1, fail:0};

  // 视图内状态（跨重入保留当前页签与选中任务）
  const state = {tab:'findings', taskId:null, category:'', propStatus:'', hitlStatus:'', session:null};

  /* ---------------- 基础小工具 ---------------- */
  function esc(s){ return DZ.esc(s); }
  function errMsg(r){ return (r && r.error && (r.error.message || r.error.code)) || '未知错误'; }
  function acc(){ return (state.session && state.session.account) || ''; }
  function each(sel, fn){ document.querySelectorAll(sel).forEach(function(el){ fn(el); }); }

  function remLabel(s){ return REM_ALIAS[String(s == null ? '' : s).toLowerCase()] || (s || '待分派'); }
  function remKind(label){ return REM_KIND[label] || 'unk'; }
  function findingStatusBadge(s){
    const l = FINDING_STATUS[String(s == null ? '' : s).toLowerCase()] || s || '—';
    return DZ.statusBadge(l);
  }
  function opts(list, sel){
    return list.map(function(x){
      return '<option value="' + esc(x) + '"' + (x === sel ? ' selected' : '') + '>' + esc(x) + '</option>';
    }).join('');
  }

  /* ---------------- 视图装载 ---------------- */
  function init(){
    const root = document.querySelector(ROOT);
    if (!root) return;
    root.innerHTML = shell();
    buildTabs();
    bindShell();
    loadSession();
    loadTasks();
  }

  function shell(){
    return '' +
      '<div class="dz-toolbar dz-toolbar--single">' +
        '<label class="muted" for="rem_task">自查任务</label>' +
        '<select id="rem_task" title="选择要整改/复检的自查任务" aria-label="选择自查任务">' +
          '<option value="">加载中…</option></select>' +
        '<button id="rem_refresh" class="ghost" title="刷新任务与当前页签数据" aria-label="刷新">刷新</button>' +
        '<span id="rem_session" class="muted dz-toolbar-note">账号加载中…</span>' +
      '</div>' +
      '<div id="rem_tabs"></div>' +
      '<div id="rem_panel">' + DZ.skeleton(4) + '</div>';
  }

  function buildTabs(){
    DZ.tabs('#rem_tabs', [
      {key:'findings',  label:'问题与整改'},
      {key:'recheck',   label:'复检对比'},
      {key:'proposals', label:'回流提案'},
      {key:'hitl',      label:'人工确认'}
    ], state.tab, function(k){ state.tab = k; renderTab(); });
  }

  function bindShell(){
    const sel = document.getElementById('rem_task');
    if (sel) sel.onchange = function(){ state.taskId = sel.value; renderTab(); };
    const rf = document.getElementById('rem_refresh');
    if (rf) rf.onclick = function(){ loadSession(); loadTasks(); };
  }

  /* ---------------- 会话与任务 ---------------- */
  async function loadSession(){
    const box = document.getElementById('rem_session');
    if (box) box.innerHTML = DZ.skeleton(1);
    const r = await DZ.get('/api/auth/session');
    state.session = (r && !r.error) ? r : null;
    const el = document.getElementById('rem_session');
    if (!el) return;
    if (!state.session){
      el.innerHTML = '<span class="muted">账号信息不可用</span>';
      return;
    }
    const s = state.session;
    const ini = (s.displayName || s.account || '?').slice(0, 1);
    el.innerHTML =
      '<span class="dz-avatar" title="' + esc(s.displayName || s.account) + '">' + esc(ini) + '</span> ' +
      '<span>当前账号 <b>' + esc(s.account) + '</b>（' + esc(s.displayName || '') + '）</span>' +
      ((s.roles && s.roles.length) ? ' ' + s.roles.map(function(x){
        return '<span class="dz-tag-soft">' + esc(x) + '</span>';
      }).join(' ') : '');
  }

  async function loadTasks(){
    const sel = document.getElementById('rem_task');
    const r = await DZ.get('/api/selfcheck/tasks');
    if (r && r.error){
      if (sel) sel.innerHTML = '<option value="">加载失败</option>';
      DZ.render('#rem_panel', DZ.banner('bad', '任务列表加载失败：' + errMsg(r), loadTasks));
      return;
    }
    const tasks = (r && r.tasks) || [];
    if (sel){
      sel.innerHTML = tasks.length ? tasks.map(function(t){
        const st = TASK_STATUS[t.status] || t.status || '';
        return '<option value="' + esc(t.taskId) + '">' +
          esc(t.orgName + ' · ' + (t.cycle || '') + ' · ' + (t.topic || '') + '（' + st + '）') +
          '</option>';
      }).join('') : '<option value="">暂无可见任务</option>';
    }
    if (!state.taskId || !tasks.some(function(t){ return t.taskId === state.taskId; })){
      state.taskId = tasks.length ? tasks[0].taskId : null;
    }
    if (sel && state.taskId) sel.value = state.taskId;
    renderTab();
  }

  function renderTab(){
    const panel = document.getElementById('rem_panel');
    if (!panel) return;
    if (state.tab === 'findings' || state.tab === 'recheck'){
      if (!state.taskId){
        panel.innerHTML = DZ.empty('暂无可选自查任务', '');
        return;
      }
    }
    if (state.tab === 'findings') renderFindings();
    else if (state.tab === 'recheck') renderRecheck();
    else if (state.tab === 'proposals') renderProposals();
    else if (state.tab === 'hitl') renderHitl();
  }

  /* ================= 页签一：问题与整改（L1） ================= */
  async function renderFindings(){
    const panel = document.getElementById('rem_panel');
    panel.innerHTML = DZ.skeleton(5);
    const tid = state.taskId;
    const r = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(tid) + '/findings');
    if (state.taskId !== tid || state.tab !== 'findings') return;   // 任务/页签已切换
    if (r && r.error){
      panel.innerHTML = DZ.banner('bad', '问题清单加载失败：' + errMsg(r), renderFindings);
      return;
    }
    const list = (r && r.findings) || [];
    let html = '<div class="dz-toolbar">' +
        '<button id="rem_add_finding" title="为当前任务新增问题" aria-label="新增问题">＋ 新增问题</button>' +
        '<span class="muted">共 ' + list.length + ' 条问题</span>' +
      '</div>' +
      '<div id="rem_finding_form"></div>';
    if (!list.length){
      html += DZ.empty('该任务暂无问题记录', '<button id="rem_add_finding2" title="新增问题">新增问题</button>');
      panel.innerHTML = html;
      bindFindingAdd();
      return;
    }
    html += list.map(findingCard).join('');
    panel.innerHTML = html;
    bindFindingAdd();
    bindRemCreate();
    bindRemSave();
  }

  function findingCard(f){
    const rems = f.remediations || [];
    return '<div class="card" style="margin-bottom:12px">' +
      '<div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">' +
        '<span class="dz-tag-soft" title="检查项编号">' + esc(f.checkCode) + '</span>' +
        DZ.severityBadge(f.severity) +
        findingStatusBadge(f.status) +
        '<span class="muted">负责人 ' + esc(f.owner || '—') + '</span>' +
        '<span class="muted">到期 ' + esc(DZ.date(f.dueDate)) + '</span>' +
        (f.sourceRunId ? '<span class="muted" title="来源运行">来源运行 ' + esc(f.sourceRunId) + '</span>' : '') +
      '</div>' +
      '<h4 style="margin:8px 0 4px">' + esc(f.problem) + '</h4>' +
      '<div class="muted">根因：' + esc(f.rootCause || '—') + '</div>' +
      '<div style="margin-top:10px">' +
        '<div class="dz-mini" style="margin-bottom:6px">整改任务（' + rems.length + '）</div>' +
        (rems.length ? rems.map(remCard).join('') : '<div class="muted dz-mini">尚未创建整改任务</div>') +
      '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
        '<button class="ghost" data-act="add-rem" data-finding="' + esc(f.findingId) + '" ' +
          'title="为该问题创建整改任务" aria-label="创建整改任务">＋ 创建整改任务</button>' +
      '</div>' +
      '<div id="rem_form_' + esc(f.findingId) + '"></div>' +
    '</div>';
  }

  function remCard(rm){
    const id = rm.remediationId;
    const label = remLabel(rm.status);
    return '<div class="dz-cite">' +
      '<div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">' +
        '<span class="dz-tag-soft">整改 ' + esc(id) + '</span>' +
        DZ.badge(remKind(label), label) +
        '<span class="muted">负责人 ' + esc(rm.owner || '—') + '</span>' +
        '<span class="muted">到期 ' + esc(DZ.date(rm.dueDate)) + '</span>' +
        (rm.evidenceRef ? '<span class="dz-cite-src">证据：' + esc(rm.evidenceRef) + '</span>' : '') +
      '</div>' +
      '<div style="margin-top:6px">' + esc(rm.measures || '（无措施说明）') + '</div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
        '<label class="muted" for="rem_st_' + esc(id) + '">状态</label>' +
        '<select id="rem_st_' + esc(id) + '" title="整改状态" aria-label="整改状态">' +
          opts(REM_STATES, label) + '</select>' +
        '<input id="rem_ev_' + esc(id) + '" placeholder="证据引用（可选）" value="' + esc(rm.evidenceRef || '') +
          '" title="证据引用" aria-label="证据引用">' +
        '<button data-act="save-rem" data-rem="' + esc(id) + '" title="保存整改状态与证据" aria-label="保存整改">保存</button>' +
      '</div>' +
    '</div>';
  }

  // 新增问题
  function bindFindingAdd(){
    const open = function(){
      const box = document.getElementById('rem_finding_form');
      if (!box) return;
      box.innerHTML = '<div class="dz-cite" style="margin-bottom:12px">' +
        '<div class="row" style="gap:10px;flex-wrap:wrap">' +
          '<label class="muted">检查项编号 <input id="ff_code" placeholder="如 15.5" title="检查项编号" aria-label="检查项编号"></label>' +
          '<label class="muted">严重程度 <select id="ff_sev" title="严重程度" aria-label="严重程度">' +
            '<option value="high">高</option><option value="medium" selected>中</option><option value="low">低</option>' +
          '</select></label>' +
          '<label class="muted">负责人 <input id="ff_owner" value="' + esc(acc()) + '" title="负责人" aria-label="负责人"></label>' +
          '<label class="muted">到期日 <input id="ff_due" type="date" title="到期日" aria-label="到期日"></label>' +
        '</div>' +
        '<label class="muted" style="display:block;margin-top:8px">问题描述 <textarea id="ff_problem" rows="2" ' +
          'placeholder="描述发现的问题" title="问题描述" aria-label="问题描述"></textarea></label>' +
        '<label class="muted" style="display:block;margin-top:8px">根因 <textarea id="ff_root" rows="2" ' +
          'placeholder="根因分析（可选）" title="根因" aria-label="根因"></textarea></label>' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
          '<button data-act="do-finding" title="提交新增问题">提交</button>' +
          '<button class="ghost" data-act="cancel-finding" title="取消">取消</button>' +
        '</div>' +
      '</div>';
      each('#rem_finding_form [data-act="do-finding"]', function(b){ b.onclick = submitFinding; });
      each('#rem_finding_form [data-act="cancel-finding"]', function(b){
        b.onclick = function(){ box.innerHTML = ''; };
      });
    };
    each('#rem_add_finding, #rem_add_finding2', function(b){ b.onclick = open; });
  }

  async function submitFinding(){
    const btn = document.querySelector('#rem_finding_form [data-act="do-finding"]');
    const code = (document.getElementById('ff_code') || {}).value || '';
    const problem = (document.getElementById('ff_problem') || {}).value || '';
    if (!code.trim() || !problem.trim()){ DZ.toast('检查项编号与问题描述为必填', 'warn'); return; }
    const body = {
      checkCode: code.trim(),
      severity: (document.getElementById('ff_sev') || {}).value || 'medium',
      problem: problem.trim(),
      rootCause: (document.getElementById('ff_root') || {}).value || '',
      owner: (document.getElementById('ff_owner') || {}).value || acc(),
      dueDate: (document.getElementById('ff_due') || {}).value || null
    };
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    await DZ.delay(300);
    const r = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(state.taskId) + '/findings', body);
    if (r && r.error){
      if (btn){ btn.disabled = false; btn.textContent = '提交'; }
      DZ.toast('新增问题失败：' + errMsg(r), 'bad');
      return;
    }
    DZ.toast('问题已新增', 'ok');
    renderFindings();
  }

  // 创建整改任务
  function bindRemCreate(){
    each('#rem_panel [data-act="add-rem"]', function(btn){
      btn.onclick = function(){
        const fid = btn.dataset.finding;
        const box = document.getElementById('rem_form_' + fid);
        if (!box) return;
        box.innerHTML = '<div class="dz-cite" style="margin-top:8px">' +
          '<div class="row" style="gap:10px;flex-wrap:wrap">' +
            '<label class="muted">负责人 <input id="ro_owner_' + esc(fid) + '" value="' + esc(acc()) + '" ' +
              'title="负责人" aria-label="负责人"></label>' +
            '<label class="muted">到期日 <input id="ro_due_' + esc(fid) + '" type="date" title="到期日" aria-label="到期日"></label>' +
          '</div>' +
          '<label class="muted" style="display:block;margin-top:8px">整改措施 <textarea id="ro_meas_' + esc(fid) + '" rows="2" ' +
            'placeholder="填写整改措施" title="整改措施" aria-label="整改措施"></textarea></label>' +
          '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
            '<button data-act="do-rem" title="提交整改任务">提交整改任务</button>' +
            '<button class="ghost" data-act="cancel-rem" title="取消">取消</button>' +
          '</div>' +
        '</div>';
        each('#rem_form_' + fid + ' [data-act="cancel-rem"]', function(b){
          b.onclick = function(){ box.innerHTML = ''; };
        });
        each('#rem_form_' + fid + ' [data-act="do-rem"]', function(b){ b.onclick = function(){ submitRemCreate(fid, b); }; });
      };
    });
  }

  async function submitRemCreate(fid, btn){
    const body = {
      findingId: fid,
      owner: (document.getElementById('ro_owner_' + fid) || {}).value || acc(),
      dueDate: (document.getElementById('ro_due_' + fid) || {}).value || null,
      measures: (document.getElementById('ro_meas_' + fid) || {}).value || ''
    };
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    await DZ.delay(300);
    const r = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(state.taskId) + '/remediations', body);
    if (r && r.error){
      if (btn){ btn.disabled = false; btn.textContent = '提交整改任务'; }
      DZ.toast('创建整改任务失败：' + errMsg(r), 'bad');
      return;
    }
    DZ.toast('整改任务已创建', 'ok');
    renderFindings();
  }

  // 整改状态流转
  function bindRemSave(){
    each('#rem_panel [data-act="save-rem"]', function(btn){
      btn.onclick = async function(){
        const id = btn.dataset.rem;
        const stEl = document.getElementById('rem_st_' + id);
        const evEl = document.getElementById('rem_ev_' + id);
        const status = stEl ? stEl.value : '';
        if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
        await DZ.delay(300);
        const r = await DZ.patch('/api/selfcheck/remediations/' + encodeURIComponent(id),
          {status: status, evidenceRef: evEl ? evEl.value : '', actor: acc() || undefined});
        if (r && r.error){
          if (btn){ btn.disabled = false; btn.textContent = '保存'; }
          DZ.toast('整改状态更新失败：' + errMsg(r), 'bad');
          return;
        }
        DZ.toast('整改状态已更新为「' + status + '」', 'ok');
        renderFindings();
      };
    });
  }

  /* ================= 页签二：复检对比（L4） ================= */
  async function renderRecheck(){
    const panel = document.getElementById('rem_panel');
    panel.innerHTML = DZ.skeleton(5);
    const tid = state.taskId;
    const r = await DZ.get('/api/selfcheck/tasks/' + encodeURIComponent(tid) + '/recheck/diff');
    if (state.taskId !== tid || state.tab !== 'recheck') return;

    const toolbar = '<div class="dz-toolbar">' +
        '<button id="rem_run_recheck" title="对当前任务发起复检运行" aria-label="发起复检">↻ 发起复检</button>' +
        '<span class="muted">复检写入运行态库并生成前后对比</span>' +
      '</div>';

    if (r && r.error){
      // 尚无复检运行（≥2 个运行才能比对）——引导而非死路
      panel.innerHTML = toolbar + DZ.empty('暂无复检运行，无法比对',
        '<button id="rem_run_recheck2" title="发起复检">发起复检</button>');
      bindRecheck();
      return;
    }

    const tl = r.taskLevel || {};
    const before = tl.before || {}, after = tl.after || {}, delta = tl.delta || {};
    // 注意：后端 tally 覆盖了 pass 字段——before.pass/after.pass 是"通过项数量"，非百分比；
    // 通过率需按 通过数/总数 现算，delta.pass 才是通过率差值（百分点）。
    const tb = total(before), ta = total(after);
    const rateB = tb ? Math.round((Number(before.pass) || 0) / tb * 1000) / 10 : 0;
    const rateA = ta ? Math.round((Number(after.pass) || 0) / ta * 1000) / 10 : 0;
    const dPass = Number(delta.pass) || 0;
    const items = r.items || [];

    let html = toolbar;

    // 任务级：通过率 before → after
    html += '<div class="dz-kpi-row">' +
      DZ.kpi('复检前通过率', pct(rateB), '通过 ' + (Number(before.pass) || 0) + '/' + tb +
             (r.beforeRun ? '｜' + esc(r.beforeRun) : ''), 'warn') +
      DZ.kpi('复检后通过率', pct(rateA), '通过 ' + (Number(after.pass) || 0) + '/' + ta +
             (r.afterRun ? '｜' + esc(r.afterRun) : ''),
             dPass > 0 ? 'ok' : (dPass < 0 ? 'bad' : undefined)) +
      DZ.kpi('通过率变化', (dPass > 0 ? '+' : '') + dPass + 'pp', deltaText(dPass),
             dPass > 0 ? 'ok' : (dPass < 0 ? 'bad' : undefined)) +
    '</div>';

    // 任务级：各判定数量对比
    html += DZ.sectionTitle('任务级判定对比') +
      '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th>判定维度</th><th>复检前</th><th>复检后</th><th>变化</th></tr></thead><tbody>' +
      countRow('通过', before.pass, after.pass, false) +
      countRow('部分符合', before.partial, after.partial, true) +
      countRow('不符合', before.fail, after.fail, true) +
      countRow('需补充', before.supplement, after.supplement, true) +
      '<tr><td>通过率（%）</td><td>' + num(rateB) + '</td><td>' + num(rateA) +
        '</td><td>' + deltaBadge(dPass) + '</td></tr>' +
      '</tbody></table></div>';

    // 逐项对比
    html += DZ.sectionTitle('逐项复检对比') +
      '<div class="dz-legend">' +
        '<span><b style="background:var(--ok)"></b>改善</span>' +
        '<span><b style="background:var(--bad)"></b>恶化</span>' +
        '<span><b style="background:var(--unk)"></b>未变</span>' +
        '<span class="muted">｜ 变化项整行高亮</span>' +
      '</div>' +
      '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th>检查项</th><th>复检前</th><th>复检后</th><th>变化</th><th>证据</th></tr></thead><tbody>' +
      (items.length ? items.map(diffRow).join('') : '<tr><td colspan="5" class="muted">暂无可比对检查项</td></tr>') +
      '</tbody></table></div>';

    panel.innerHTML = html;
    bindRecheck();
  }

  function countRow(label, b, a, lowerBetter){
    const bn = num(b), an = num(a);
    let deltaBadgeHtml;
    if (b == null && a == null) deltaBadgeHtml = DZ.badge('unk', '未变');
    else {
      const d = (Number(a) || 0) - (Number(b) || 0);
      const improved = lowerBetter ? d < 0 : d > 0;
      const worsened = lowerBetter ? d > 0 : d < 0;
      deltaBadgeHtml = improved ? DZ.badge('ok', '改善 ' + (d > 0 ? '+' : '') + d)
        : worsened ? DZ.badge('bad', '恶化 ' + (d > 0 ? '+' : '') + d)
        : DZ.badge('unk', '未变');
    }
    return '<tr><td>' + esc(label) + '</td><td>' + bn + '</td><td>' + an + '</td><td>' + deltaBadgeHtml + '</td></tr>';
  }

  function diffRow(it){
    const cls = classify(it.before, it.after);
    const bg = cls === 'improve' ? 'background:var(--ok-bg)'
      : cls === 'worsen' ? 'background:var(--bad-bg)'
      : (it.changed ? 'background:var(--warn-bg)' : '');
    return '<tr' + (bg ? ' style="' + bg + '"' : '') + (it.changed ? ' aria-label="已变化"' : '') + '>' +
      '<td><span class="dz-tag-soft">' + esc(it.checkCode) + '</span> ' +
        '<span class="muted">' + esc(it.title || '') + '</span>' +
        (it.changed ? ' ' + DZ.badge('bad', '变化') : '') + '</td>' +
      '<td>' + (it.before ? DZ.resultBadge(it.before) : '<span class="muted">—</span>') + '</td>' +
      '<td>' + (it.after ? DZ.resultBadge(it.after) : '<span class="muted">—</span>') + '</td>' +
      '<td>' + changeBadge(cls) + '</td>' +
      '<td>' + (it.evidenceAdded ? DZ.badge('ok', '已补证') : '<span class="muted">—</span>') + '</td>' +
    '</tr>';
  }

  function classify(b, a){
    if ((b == null || b === '') && a) return 'new';
    if ((a == null || a === '') && b) return 'removed';
    if (b === a) return 'unchanged';
    const rb = RANK[b], ra = RANK[a];
    if (ra == null || rb == null) return 'changed';
    if (ra > rb) return 'improve';
    if (ra < rb) return 'worsen';
    return 'changed';
  }

  function changeBadge(cls){
    if (cls === 'improve') return DZ.badge('ok', '改善');
    if (cls === 'worsen') return DZ.badge('bad', '恶化');
    if (cls === 'unchanged') return DZ.badge('unk', '未变');
    if (cls === 'new') return DZ.badge('warn', '新增');
    if (cls === 'removed') return DZ.badge('warn', '移除');
    return DZ.badge('warn', '变化');
  }

  function deltaBadge(d){
    if (d > 0) return DZ.badge('ok', '改善 +' + d);
    if (d < 0) return DZ.badge('bad', '恶化 ' + d);
    return DZ.badge('unk', '未变');
  }
  function deltaText(d){ return d > 0 ? '整体改善' : (d < 0 ? '整体恶化' : '与初检持平'); }
  function num(v){ return (v == null || v === '') ? '—' : String(v); }
  function pct(v){ return (v == null || v === '') ? '—' : (v + '%'); }
  // 复检任务级总数 = 各判定计数之和（后端未直接给出 total）
  function total(t){
    return (Number(t.pass) || 0) + (Number(t.partial) || 0) +
           (Number(t.fail) || 0) + (Number(t.supplement) || 0);
  }

  function bindRecheck(){
    each('#rem_run_recheck, #rem_run_recheck2', function(btn){
      btn.onclick = async function(){
        const label = btn.textContent;
        btn.disabled = true; btn.textContent = '复检执行中…';
        await DZ.delay(400);
        const r = await DZ.post('/api/selfcheck/tasks/' + encodeURIComponent(state.taskId) + '/recheck', {});
        if (r && r.error){
          btn.disabled = false; btn.textContent = label;
          DZ.toast('复检发起失败：' + errMsg(r), 'bad');
          return;
        }
        DZ.toast('复检完成：作业 ' + (r.runId || ''), 'ok');
        renderRecheck();
      };
    });
  }

  /* ================= 页签三：回流提案审核（L3，含职责分离） ================= */
  async function renderProposals(){
    const panel = document.getElementById('rem_panel');
    panel.innerHTML = DZ.skeleton(5);
    const url = '/api/review/proposals?status=' + encodeURIComponent(state.propStatus) +
      '&category=' + encodeURIComponent(state.category);
    const r = await DZ.get(url);
    if (state.tab !== 'proposals') return;
    if (r && r.error){
      panel.innerHTML = DZ.banner('bad', '提案队列加载失败：' + errMsg(r), renderProposals);
      return;
    }
    const list = (r && r.proposals) || [];

    let html = '<div class="dz-toolbar">' +
      '<button id="rem_add_prop" title="新建回流提案" aria-label="新建提案">＋ 新建提案</button>' +
      '<label class="muted" for="rem_prop_status">状态 ' +
        '<select id="rem_prop_status" title="按状态筛选" aria-label="按状态筛选">' +
          '<option value="">全部</option>' +
          '<option value="pending"' + (state.propStatus === 'pending' ? ' selected' : '') + '>待审核</option>' +
          '<option value="approved"' + (state.propStatus === 'approved' ? ' selected' : '') + '>已通过</option>' +
          '<option value="rejected"' + (state.propStatus === 'rejected' ? ' selected' : '') + '>已驳回</option>' +
        '</select></label>' +
      '<span class="muted">共 ' + list.length + ' 条</span>' +
    '</div>' +
    '<div id="rem_prop_form"></div>' +
    categoryChipbar();
    html += list.length ? list.map(propCard).join('')
      : DZ.empty('当前筛选下暂无提案', '<button id="rem_add_prop2" title="新建提案">新建提案</button>');

    panel.innerHTML = html;
    bindProposals();
  }

  function categoryChipbar(){
    const chip = function(cat, label){
      const on = (state.category || '') === cat;
      return '<button class="dz-chip' + (on ? ' on' : '') + '" data-cat="' + esc(cat) + '" ' +
        'title="筛选类目 ' + esc(label) + '" aria-label="筛选类目 ' + esc(label) + '">' + esc(label) + '</button>';
    };
    return '<div class="dz-chipbar" id="rem_prop_cats">' +
      chip('', '全部') + PROPOSAL_CATS.map(function(c){ return chip(c, c); }).join('') +
    '</div>';
  }

  function propCard(p){
    return '<div class="card" style="margin-bottom:10px">' +
      '<div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">' +
        '<span class="dz-tag-soft" title="提案类目">' + esc(p.category) + '</span>' +
        DZ.statusBadge(p.status) +
        '<span class="muted">来源 ' + esc(p.raisedFrom || '—') + '</span>' +
        '<span class="muted">提出人 ' + esc(p.raisedBy || '—') + '</span>' +
        '<span class="muted">' + esc(DZ.date(p.createdAt)) + '</span>' +
        (p.reviewedBy ? '<span class="muted">复核人 ' + esc(p.reviewedBy) + '</span>' : '') +
      '</div>' +
      '<h4 style="margin:8px 0 4px">' + esc(p.title) + '</h4>' +
      '<div class="dz-actions" style="justify-content:flex-start">' +
        '<button class="ghost" data-act="prop-open" data-id="' + esc(p.proposalId) + '" ' +
          'title="查看提案详情并审核" aria-label="查看提案详情">查看详情 / 审核</button>' +
      '</div>' +
      '<div id="rem_prop_detail_' + esc(p.proposalId) + '"></div>' +
    '</div>';
  }

  function bindProposals(){
    each('#rem_prop_cats .dz-chip', function(c){
      c.onclick = function(){
        state.category = c.dataset.cat || '';
        renderProposals();
      };
    });
    const sel = document.getElementById('rem_prop_status');
    if (sel) sel.onchange = function(){ state.propStatus = sel.value; renderProposals(); };
    each('#rem_add_prop, #rem_add_prop2', function(b){ b.onclick = openProposalForm; });
    each('#rem_panel [data-act="prop-open"]', function(b){
      b.onclick = function(){ openProposalDetail(b.dataset.id); };
    });
  }

  async function openProposalDetail(id){
    const box = document.getElementById('rem_prop_detail_' + id);
    if (!box) return;
    box.innerHTML = DZ.skeleton(2);
    const r = await DZ.get('/api/review/proposals/' + encodeURIComponent(id));
    if (r && r.error){
      box.innerHTML = DZ.banner('bad', '提案详情加载失败：' + errMsg(r),
        function(){ openProposalDetail(id); });
      return;
    }
    const payload = JSON.stringify(r.payload || {}, null, 2);
    box.innerHTML = '<div class="dz-cite" style="margin-top:8px">' +
      '<div class="dz-mini" style="margin-bottom:6px">提案内容</div>' +
      '<div class="dz-contract">' + esc(payload) + '</div>' +
      (r.reviewComment ? '<div class="dz-mini" style="margin-top:6px">上次复核意见：' + esc(r.reviewComment) + '</div>' : '') +
      '<div class="row" style="gap:10px;flex-wrap:wrap;margin-top:10px">' +
        '<label class="muted">复核人 <input id="pp_rev_' + esc(id) + '" value="' + esc(acc()) + '" ' +
          'title="复核人账号" aria-label="复核人账号"></label>' +
        '<button class="ghost" data-act="fill-raiser" data-id="' + esc(id) + '" data-raiser="' + esc(r.raisedBy || '') + '" ' +
          'title="以提案人身份复核，用于演示职责分离拦截" aria-label="填入提案人">填入提案人（演示职责分离）</button>' +
      '</div>' +
      '<label class="muted" style="display:block;margin-top:8px">复核意见 <textarea id="pp_cmt_' + esc(id) + '" rows="2" ' +
        'placeholder="复核意见（可选）" title="复核意见" aria-label="复核意见"></textarea></label>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
        '<button data-act="prop-decide" data-id="' + esc(id) + '" data-dec="approve" title="通过该提案">通过</button>' +
        '<button class="ghost" data-act="prop-decide" data-id="' + esc(id) + '" data-dec="return" title="退回该提案">退回</button>' +
        '<button class="ghost" data-act="prop-decide" data-id="' + esc(id) + '" data-dec="reject" title="驳回该提案">驳回</button>' +
      '</div>' +
      '<div id="pp_msg_' + esc(id) + '"></div>' +
    '</div>';

    const fill = document.querySelector('#rem_prop_detail_' + id + ' [data-act="fill-raiser"]');
    if (fill) fill.onclick = function(){
      const inp = document.getElementById('pp_rev_' + id);
      if (inp) inp.value = fill.dataset.raiser || '';
      DZ.toast('已填入提案人，用于演示职责分离拦截', 'warn');
    };
    each('#rem_prop_detail_' + id + ' [data-act="prop-decide"]', function(b){
      b.onclick = function(){ decideProposal(id, b.dataset.dec, b); };
    });
  }

  async function decideProposal(id, decision, btn){
    const reviewer = (document.getElementById('pp_rev_' + id) || {}).value || acc();
    const comment = (document.getElementById('pp_cmt_' + id) || {}).value || '';
    const msg = document.getElementById('pp_msg_' + id);
    if (msg) msg.innerHTML = '';
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    await DZ.delay(300);
    const r = await DZ.post('/api/review/proposals/' + encodeURIComponent(id) + '/decision',
      {decision: decision, reviewer: reviewer, comment: comment});
    if (r && r.error){
      if (btn){ btn.disabled = false; btn.textContent = decisionLabel(decision); }
      if (r.error.code === 'FORBIDDEN'){
        // 职责分离互斥：提案人不能自审——按契约渲染红色提示条
        if (msg) msg.innerHTML = DZ.banner('bad',
          r.error.message || '职责分离校验不通过：经办与复核不得为同一账号');
        DZ.toast('职责分离校验拦截：提案人不能自审，请更换复核人', 'bad');
      } else {
        if (msg) msg.innerHTML = DZ.banner('bad', '审核失败：' + errMsg(r));
        DZ.toast('审核失败：' + errMsg(r), 'bad');
      }
      return;
    }
    DZ.toast('提案已' + decisionLabel(decision) + '（复核人 ' + reviewer + '）', 'ok');
    renderProposals();
  }

  function decisionLabel(d){ return d === 'approve' ? '通过' : d === 'reject' ? '驳回' : '退回'; }

  function openProposalForm(){
    const box = document.getElementById('rem_prop_form');
    if (!box) return;
    box.innerHTML = '<div class="dz-cite" style="margin-bottom:12px">' +
      '<div class="row" style="gap:10px;flex-wrap:wrap">' +
        '<label class="muted">类目 <select id="pf_cat" title="提案类目" aria-label="提案类目">' +
          PROPOSAL_CATS.map(function(c){ return '<option value="' + c + '">' + c + '</option>'; }).join('') +
        '</select></label>' +
        '<label class="muted">提出人 <input id="pf_by" value="' + esc(acc()) + '" title="提出人账号" aria-label="提出人账号"></label>' +
        '<label class="muted">来源 <input id="pf_from" value="t-bank-2026q4" title="提出来源" aria-label="提出来源"></label>' +
      '</div>' +
      '<label class="muted" style="display:block;margin-top:8px">标题 <input id="pf_title" ' +
        'placeholder="提案标题" title="提案标题" aria-label="提案标题"></label>' +
      '<label class="muted" style="display:block;margin-top:8px">提案内容（JSON，可空） ' +
        '<textarea id="pf_payload" rows="3" placeholder=\'{"checkCode":"15.5","element":"..."}\' ' +
        'title="提案内容（JSON）" aria-label="提案内容（JSON）"></textarea></label>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:8px">' +
        '<button data-act="do-prop" title="提交新建提案">提交提案</button>' +
        '<button class="ghost" data-act="cancel-prop" title="取消">取消</button>' +
      '</div>' +
    '</div>';
    each('#rem_prop_form [data-act="cancel-prop"]', function(b){ b.onclick = function(){ box.innerHTML = ''; }; });
    each('#rem_prop_form [data-act="do-prop"]', function(b){ b.onclick = function(){ submitProposal(b); }; });
  }

  async function submitProposal(btn){
    const title = (document.getElementById('pf_title') || {}).value || '';
    if (!title.trim()){ DZ.toast('提案标题为必填', 'warn'); return; }
    const raw = (document.getElementById('pf_payload') || {}).value || '';
    let payload = {};
    if (raw.trim()){
      try { payload = JSON.parse(raw); }
      catch (e){ payload = {note: raw.trim()}; }
    }
    const body = {
      category: (document.getElementById('pf_cat') || {}).value || 'RA1',
      title: title.trim(),
      payload: payload,
      raisedFrom: (document.getElementById('pf_from') || {}).value || 'manual',
      raisedBy: (document.getElementById('pf_by') || {}).value || acc()
    };
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    await DZ.delay(300);
    const r = await DZ.post('/api/review/proposals', body);
    if (r && r.error){
      if (btn){ btn.disabled = false; btn.textContent = '提交提案'; }
      DZ.toast('新建提案失败：' + errMsg(r), 'bad');
      return;
    }
    DZ.toast('提案已提交，进入待审核队列', 'ok');
    state.propStatus = '';
    renderProposals();
  }

  /* ================= 页签四：人工确认（K1.5） ================= */
  async function renderHitl(){
    const panel = document.getElementById('rem_panel');
    panel.innerHTML = DZ.skeleton(5);
    const r = await DZ.get('/api/hitl/candidates?status=' + encodeURIComponent(state.hitlStatus));
    if (state.tab !== 'hitl') return;
    if (r && r.error){
      panel.innerHTML = DZ.banner('bad', '人工确认队列加载失败：' + errMsg(r), renderHitl);
      return;
    }
    const list = (r && r.candidates) || [];

    let html = '<div class="dz-toolbar">' +
      '<label class="muted" for="rem_hitl_status">状态 ' +
        '<select id="rem_hitl_status" title="按状态筛选" aria-label="按状态筛选">' +
          '<option value="">全部</option>' +
          '<option value="pending"' + (state.hitlStatus === 'pending' ? ' selected' : '') + '>待处理</option>' +
          '<option value="approved"' + (state.hitlStatus === 'approved' ? ' selected' : '') + '>已通过</option>' +
          '<option value="rejected"' + (state.hitlStatus === 'rejected' ? ' selected' : '') + '>已驳回</option>' +
        '</select></label>' +
      '<span class="muted">共 ' + list.length + ' 条待人工确认候选</span>' +
    '</div>';

    html += list.length ? list.map(hitlCard).join('')
      : DZ.empty('当前筛选下暂无人工确认候选', '');
    panel.innerHTML = html;

    const sel = document.getElementById('rem_hitl_status');
    if (sel) sel.onchange = function(){ state.hitlStatus = sel.value; renderHitl(); };
    each('#rem_panel [data-act="hitl-decide"]', function(b){
      b.onclick = function(){ decideHitl(b.dataset.id, b.dataset.dec, b); };
    });
  }

  function hitlCard(c){
    const id = c.candidateId;
    const conf = Number(c.confidence);
    const low = isFinite(conf) && conf < 0.6;
    const srcLabel = HITL_SRC[c.sourceType] || c.sourceType || '—';
    return '<div class="card" style="margin-bottom:10px' + (low ? ';border-color:var(--warn)' : '') + '">' +
      (low ? '<div class="dz-banner warn" role="note">低置信度（' + DZ.confidence(c.confidence) +
        '）需人工重点确认</div>' : '') +
      '<div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">' +
        '<span class="dz-tag-soft" title="来源类型">' + esc(srcLabel) + '</span>' +
        '<span class="muted">来源 ' + esc(c.sourceId || '—') + '</span>' +
        '<span class="dz-tag-soft" title="检查项编号">' + esc(c.checkCode || '—') + '</span>' +
        '<span class="muted">置信度 ' + DZ.confidence(c.confidence) + '</span>' +
        DZ.statusBadge(c.status) +
        '<span class="muted">分配审核人 ' + esc(c.assignedReviewer || '未分配') + '</span>' +
        '<span class="muted">' + esc(DZ.date(c.createdAt)) + '</span>' +
      '</div>' +
      '<h4 style="margin:8px 0 4px">' + esc(c.title) + '</h4>' +
      (c.status === 'pending' ?
        '<div class="dz-actions" style="justify-content:flex-start;flex-wrap:wrap">' +
          '<label class="muted">审核人 <input id="hh_rev_' + esc(id) + '" value="' + esc(acc()) + '" ' +
            'title="审核人账号" aria-label="审核人账号"></label>' +
          '<label class="muted">意见 <input id="hh_cmt_' + esc(id) + '" placeholder="审核意见（可选）" ' +
            'title="审核意见" aria-label="审核意见"></label>' +
          '<button data-act="hitl-decide" data-id="' + esc(id) + '" data-dec="approve" title="通过该候选">通过</button>' +
          '<button class="ghost" data-act="hitl-decide" data-id="' + esc(id) + '" data-dec="reject" title="驳回该候选">驳回</button>' +
        '</div>'
        : '<div class="muted dz-mini">已于 ' + esc(DZ.date(c.decidedAt)) + ' 处理</div>') +
    '</div>';
  }

  async function decideHitl(id, decision, btn){
    const reviewer = (document.getElementById('hh_rev_' + id) || {}).value || acc();
    const comment = (document.getElementById('hh_cmt_' + id) || {}).value || '';
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    await DZ.delay(300);
    const r = await DZ.post('/api/hitl/candidates/' + encodeURIComponent(id) + '/decision',
      {decision: decision, reviewer: reviewer, comment: comment});
    if (r && r.error){
      if (btn){ btn.disabled = false; btn.textContent = decision === 'approve' ? '通过' : '驳回'; }
      DZ.toast('人工确认提交失败：' + errMsg(r), 'bad');
      return;
    }
    DZ.toast('人工确认已' + (decision === 'approve' ? '通过' : '驳回'), 'ok');
    renderHitl();
  }

  /* ---------------- 注册视图装载函数 ---------------- */
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['rem'] = function(){ init(); };
})();
