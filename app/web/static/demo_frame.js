/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   治理框架（闭合链：问题 → 依据 → 责任 → 控制 → 证据 → 整改验收）
   · demo_frame.js
   视图 id：frame   容器：#frame_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/governance/frame（闭合链案件读自运行台账）、GET /api/issues/classes
   写操作：POST /api/governance/frame/cases、POST /api/governance/frame/cases/{id}/rings
          （前后端双重校验，失败 VALIDATION_FAILED）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { frame: '/api/governance/frame', classes: '/api/issues/classes' };

  var S = { data: null, classes: [], mode: 'none', ringCase: null, busy: false };

  function rootEl() { return document.getElementById('frame_root'); }

  function caseStatusBadge(st) {
    if (st === 'closed') return DZ.badge('ok', '已闭环');
    return DZ.badge('warn', '推进中');
  }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="frame_newcase" title="新建一个闭合链案件" aria-label="新建闭合链案件">新建闭合链案件</button>' +
        '<button class="ghost" id="frame_refresh" title="重新查询治理框架数据" aria-label="查询治理框架数据">查询</button>' +
      '</div>' +
      '<div id="frame_msg"></div>' +
      '<div id="frame_form"></div>' +
      '<div id="frame_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>闭合链六环</h3><div id="frame_chain">' + DZ.skeleton(1) + '</div></div>' +
      '<div id="frame_cases">' + DZ.skeleton(3) + '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('frame_newcase');
    if (nb) nb.onclick = function () { S.mode = (S.mode === 'case' ? 'none' : 'case'); renderForm(); };
    var rb = document.getElementById('frame_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderForm();
    load(false);
  }

  function issueClasses() { return S.classes || []; }

  function renderForm() {
    var box = document.getElementById('frame_form');
    if (!box) return;
    if (S.mode === 'none') { box.innerHTML = ''; return; }
    if (S.mode === 'case') { renderCaseForm(box); return; }
    if (S.mode === 'ring') { renderRingForm(box); return; }
  }

  function issueOptions() {
    var used = {};
    ((S.data && S.data.cases) || []).forEach(function (c) {
      if (c.status === 'in_progress') used[c.issueNo] = true;
    });
    return issueClasses().map(function (c) {
      var dis = used[c.no] ? ' disabled' : '';
      return '<option value="' + DZ.esc(c.no) + '"' + dis + '>' + DZ.esc(c.no) + ' ' +
        DZ.esc(c.name) + (used[c.no] ? '（已有在办）' : '') + '</option>';
    }).join('');
  }

  function renderCaseForm(box) {
    box.innerHTML = '<div class="card"><h3>新建闭合链案件</h3>' +
      '<div class="form-narrow">' +
        '<label for="frame_issue">要推进的问题类别</label>' +
        '<select id="frame_issue">' + issueOptions() + '</select>' +
        '<label for="frame_title">案件标题（可选）</label>' +
        '<input id="frame_title" placeholder="例如：分类分级与目录覆盖不完整 —— 闭合链推进" maxlength="60">' +
        '<div class="dz-actions">' +
          '<button id="frame_case_submit" title="创建案件">创建案件</button>' +
          '<button class="ghost" id="frame_case_cancel" title="取消">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('frame_case_submit');
    if (sub) sub.onclick = submitCase;
    var can = document.getElementById('frame_case_cancel');
    if (can) can.onclick = function () { S.mode = 'none'; renderForm(); };
  }

  function currentCase() {
    var list = (S.data && S.data.cases) || [];
    return list.filter(function (c) { return c.caseId === S.ringCase; })[0] || null;
  }

  function renderRingForm(box) {
    var c = currentCase();
    if (!c) { box.innerHTML = ''; return; }
    var chain = (S.data && S.data.chain) || [];
    var ring = chain[c.currentRing - 1];
    var needEvidence = ring && (ring.name === '证据' || ring.name === '整改验收');
    box.innerHTML = '<div class="card"><h3>登记第 ' + DZ.esc(c.currentRing) + ' 环 · ' +
      DZ.esc(ring ? ring.name : '') + '</h3>' +
      '<div class="muted" style="margin-bottom:8px">' + DZ.esc(c.title) + '</div>' +
      '<div class="form-narrow">' +
        '<label for="frame_output">本环结论 / 输出（必填）</label>' +
        '<input id="frame_output" placeholder="例如：形成分级覆盖缺口清单" maxlength="100">' +
        '<label for="frame_evidence">本环证据材料' + (needEvidence ? '（该环必填）' : '（可选）') + '</label>' +
        '<input id="frame_evidence" placeholder="例如：分类分级办法相关条款、目录维护规范" maxlength="100">' +
        '<div class="dz-actions">' +
          '<button id="frame_ring_submit" title="登记本环">登记本环</button>' +
          '<button class="ghost" id="frame_ring_cancel" title="取消">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('frame_ring_submit');
    if (sub) sub.onclick = submitRing;
    var can = document.getElementById('frame_ring_cancel');
    if (can) can.onclick = function () { S.mode = 'none'; S.ringCase = null; renderForm(); };
  }

  function setMsg(html) { DZ.render('#frame_msg', html || ''); }

  async function submitCase() {
    if (S.busy) return;
    var issueNo = ((document.getElementById('frame_issue') || {}).value || '').trim();
    var title = ((document.getElementById('frame_title') || {}).value || '').trim();
    if (!issueNo) { setMsg(DZ.banner('bad', '请选择要推进的问题类别')); DZ.toast('请选择问题类别', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '创建中…'));
    var res = await DZ.post(API.frame + '/cases', { issueNo: issueNo, title: title });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '创建失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('创建失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('闭合链案件已创建，已写入审计留痕', 'ok');
    S.mode = 'none';
    await load(true);
  }

  async function submitRing() {
    if (S.busy) return;
    var c = currentCase();
    if (!c) { setMsg(DZ.banner('bad', '案件不存在')); return; }
    var output = ((document.getElementById('frame_output') || {}).value || '').trim();
    var evidence = ((document.getElementById('frame_evidence') || {}).value || '').trim();
    var chain = (S.data && S.data.chain) || [];
    var ring = chain[c.currentRing - 1] || {};
    if (!output) { setMsg(DZ.banner('bad', '请填写本环结论 / 输出')); DZ.toast('请填写本环结论', 'bad'); return; }
    if ((ring.name === '证据' || ring.name === '整改验收') && !evidence) {
      setMsg(DZ.banner('bad', '「' + ring.name + '」环须归集证据材料'));
      DZ.toast('该环须填写证据材料', 'bad');
      return;
    }
    S.busy = true;
    setMsg(DZ.banner('', '登记中…'));
    var res = await DZ.post(API.frame + '/cases/' + encodeURIComponent(c.caseId) + '/rings',
      { output: output, evidence: evidence });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '登记失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('登记失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast(res.closed ? '本环已登记，闭合链已闭环' : '本环已登记，已写入审计留痕', 'ok');
    S.mode = 'none'; S.ringCase = null;
    await load(true);
  }

  function renderKpis(summary) {
    var s = summary || {};
    DZ.render('#frame_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('闭合环节', DZ.number(s.chain), '从问题到整改验收', '') +
      DZ.kpi('在办案件', DZ.number(s.cases), '已建闭合链', '') +
      DZ.kpi('推进中', DZ.number(s.progressing), '未闭环', 'warn') +
    '</div>');
  }

  function renderChain(chain) {
    var box = document.getElementById('frame_chain');
    if (!box) return;
    if (!chain.length) { box.innerHTML = DZ.empty('暂无闭合环节'); return; }
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="闭合链">' +
      chain.map(function (c, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="第 ' + DZ.esc(c.no) + ' 环：' + DZ.esc(c.name) + '">' +
            '<div class="dz-node-title">' + DZ.esc(c.no) + '．' + DZ.esc(c.name) + '</div>' +
            '<div class="dz-mini">' + DZ.esc(c.desc) + '</div>' +
          '</div>';
      }).join('') + '</div>';
  }

  function ringTrail(c, chain) {
    var done = {};
    c.records.forEach(function (r) { done[r.ringNo] = r; });
    return chain.map(function (ch) {
      var rec = done[ch.no];
      var mark = rec ? DZ.badge('ok', '已登记') : (c.currentRing === ch.no && c.status === 'in_progress'
        ? DZ.badge('warn', '待登记') : DZ.badge('unk', '未开始'));
      var body = rec
        ? '<div>' + DZ.esc(rec.output) + '</div>' +
          (rec.evidence ? '<div class="muted">证据：' + DZ.esc(rec.evidence) + '</div>' : '') +
          '<div class="muted">' + DZ.esc(rec.operator) + ' · ' + DZ.esc(DZ.date(rec.createdAt)) + '</div>'
        : '<div class="muted">—</div>';
      return '<div class="dz-metric" style="align-items:flex-start">' +
        '<span class="dz-metric-k" style="min-width:96px">' + DZ.esc(ch.no) + '．' + DZ.esc(ch.name) + '</span>' +
        '<span class="dz-metric-v" style="flex:1;text-align:left;font-weight:400">' + body + '</span>' +
        '<span>' + mark + '</span>' +
      '</div>';
    }).join('');
  }

  function renderCases(cases, chain) {
    var box = document.getElementById('frame_cases');
    if (!box) return;
    if (!cases.length) {
      box.innerHTML = DZ.empty('暂无闭合链案件', '<button class="ghost" onclick="document.getElementById(\'frame_newcase\').click()" title="新建闭合链案件">新建闭合链案件</button>');
      return;
    }
    box.innerHTML = cases.map(function (c) {
      var pct = Math.round((c.doneRings.length / chain.length) * 100);
      var btn = c.status === 'in_progress'
        ? '<button class="ghost" data-case="' + DZ.esc(c.caseId) + '" title="登记下一环">登记第 ' + DZ.esc(c.currentRing) + ' 环</button>'
        : '<span class="muted">已闭环，无待办环节</span>';
      return '<div class="card">' +
        '<h3>' + DZ.esc(c.title) + ' ' + caseStatusBadge(c.status) + '</h3>' +
        '<div class="dz-metric"><span class="dz-metric-k">对应问题类别</span>' +
          '<span class="dz-metric-v" style="text-align:right">' + DZ.esc(c.issueNo) + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">当前进度</span>' +
          '<span class="dz-metric-v" style="text-align:right">第 ' + DZ.esc(Math.min(c.currentRing, chain.length)) +
          ' 环 / 共 ' + DZ.esc(chain.length) + ' 环（' + DZ.esc(pct) + '%）</span></div>' +
        '<div style="margin:6px 0 10px">' + DZ.bar(pct) + '</div>' +
        ringTrail(c, chain) +
        '<div class="dz-actions">' + btn + '</div>' +
      '</div>';
    }).join('');
    box.querySelectorAll('[data-case]').forEach(function (b) {
      b.onclick = function () {
        S.ringCase = b.getAttribute('data-case');
        S.mode = 'ring';
        renderForm();
        var f = document.getElementById('frame_form');
        if (f && f.scrollIntoView) f.scrollIntoView({ block: 'nearest' });
      };
    });
  }

  async function load(force) {
    if (S.data && !force) {
      renderForm();
      renderKpis(S.data.summary);
      renderChain(S.data.chain || []);
      renderCases(S.data.cases || [], S.data.chain || []);
      return;
    }
    var box = document.getElementById('frame_cases');
    if (box) box.innerHTML = DZ.skeleton(3);
    var out = await Promise.all([DZ.get(API.frame), DZ.get(API.classes)]);
    var res = out[0], cls = out[1];
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '治理框架数据加载失败';
      DZ.render('#frame_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#frame_chain', DZ.empty('闭合链数据不可读'));
      DZ.render('#frame_cases', DZ.empty('闭合链案件不可读'));
      return;
    }
    S.data = res;
    S.classes = (cls && !cls.error && Array.isArray(cls.classes)) ? cls.classes : [];
    renderForm();
    renderKpis(res.summary || {});
    renderChain(Array.isArray(res.chain) ? res.chain : []);
    renderCases(Array.isArray(res.cases) ? res.cases : [], Array.isArray(res.chain) ? res.chain : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['frame'] = mount;
})();
