/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   现状诊断（输入材料 → 自动生成 → 条款人工修订）
   · demo_diag.js
   视图 id：diag   容器：#diag_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   读：GET /api/diagnosis/dimensions、GET /api/diagnosis/inputs
   写：POST /api/diagnosis/assessments（新建批次）
      PUT  /api/diagnosis/assessments/{id}/answers（保存作答）
      POST /api/diagnosis/assessments/{id}/submit（提交）
      POST /api/diagnosis/inputs（上传输入材料）
      DELETE /api/diagnosis/inputs/{inputId}（移除输入材料）
      POST /api/diagnosis/assessments/{id}/generate（自动生成诊断报告）
      POST /api/diagnosis/answers/{answerId}/revise（人工修订条款判定与证据）
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    dimensions: '/api/diagnosis/dimensions',
    assessments: '/api/diagnosis/assessments',
    inputs: '/api/diagnosis/inputs',
    generate: function (id) { return '/api/diagnosis/assessments/' + encodeURIComponent(id) + '/generate'; },
    revise: function (id) { return '/api/diagnosis/answers/' + encodeURIComponent(id) + '/revise'; }
  };
  var STATES = [{ v: 'yes', label: '有' }, { v: 'partial', label: '部分有' }, { v: 'no', label: '无' }];
  var STATE_LABEL = { yes: '有', partial: '部分有', no: '无' };
  var AUTO_PREFIX = '依据：';   // 自动生成写入的证据说明前缀，用于区分人工修订

  var S = {
    data: null, sel: null, mode: 'none', busy: false, tab: 'overview',
    inputs: null, inputBusy: false, inSize: 0,
    revised: {}, edit: null
  };

  function rootEl() { return document.getElementById('diag_root'); }
  function dimensions() { return (S.data && S.data.dimensions) || []; }
  function assessments() { return (S.data && S.data.assessments) || []; }
  function current() {
    return assessments().filter(function (a) { return a.assessmentId === S.sel; })[0] || null;
  }
  function curAid() { var a = current(); return (a && a.assessmentId) || 'da-1'; }
  function statusBadge(st) {
    if (st === 'submitted') return DZ.badge('ok', '已提交');
    return DZ.badge('warn', '草稿');
  }
  function fmtSize(n) {
    var v = Number(n);
    if (!isFinite(v) || v <= 0) return '—';
    if (v >= 1048576) return (v / 1048576).toFixed(1) + ' MB';
    if (v >= 1024) return Math.round(v / 1024) + ' KB';
    return Math.round(v) + ' B';
  }
  // 人工修订：本会话修订过，或存在非自动生成的证据说明
  function isRevised(ans) {
    if (!ans) return false;
    if (S.revised[ans.answerId]) return true;
    var ev = ans.evidence || '';
    return !!ev && ev.indexOf(AUTO_PREFIX) !== 0;
  }

  // 维度问题参考文本：键 = 维度号 | 三问
  function dimTextKey(no, q) { return String(no) + '|' + q; }
  function dimIndex() {
    var map = {};
    dimensions().forEach(function (d) {
      (d.answers || []).forEach(function (a) { map[dimTextKey(d.no, a.q)] = a.text || ''; });
    });
    return map;
  }

  var TABS = [
    { key: 'overview', label: '诊断总览' },
    { key: 'inputs', label: '输入材料' },
    { key: 'items', label: '条款与修订' }
  ];

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button id="diag_new" title="新建一次现状诊断批次" aria-label="新建诊断批次">新建诊断批次</button>' +
        '<button class="ghost" id="diag_query" title="重新拉取现状诊断数据" aria-label="查询现状诊断">查询</button>' +
        '<button id="diag_generate" title="依据输入材料自动生成诊断判定" aria-label="自动生成诊断报告">自动生成诊断报告</button>' +
      '</div>' +
      '<div id="diag_msg"></div>' +
      '<div id="diag_form"></div>' +
      '<div id="diag_tabs"></div>' +
      '<div class="dz-pane" data-pane="overview">' +
        '<div class="card"><h3>三问链条</h3><div id="diag_chain">' + DZ.skeleton(1) + '</div></div>' +
        '<div id="diag_kpis">' + DZ.skeleton(2) + '</div>' +
        '<div class="card"><h3>诊断批次</h3><div id="diag_batches">' + DZ.skeleton(3) + '</div></div>' +
      '</div>' +
      '<div class="dz-pane" data-pane="inputs" hidden>' +
        '<div class="card"><h3>上传输入材料</h3><div id="diag_input_form"></div></div>' +
        '<div id="diag_input_kpis"></div>' +
        '<div class="card"><h3>输入材料清单</h3><div id="diag_input_list">' + DZ.skeleton(3) + '</div></div>' +
      '</div>' +
      '<div class="dz-pane" data-pane="items" hidden>' +
        '<div id="diag_edit"></div>' +
        '<div id="diag_work"></div>' +
      '</div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();

    var nb = document.getElementById('diag_new');
    if (nb) nb.onclick = function () { S.mode = (S.mode === 'create' ? 'none' : 'create'); renderForm(); };
    var qb = document.getElementById('diag_query');
    if (qb) qb.onclick = function () { doQuery(); };
    var gb = document.getElementById('diag_generate');
    if (gb) gb.onclick = function () { doGenerate(); };

    DZ.tabs('#diag_tabs', TABS, S.tab, function (key) { switchTab(key); });
    switchTab(S.tab);
    renderChain();
    load(false);
  }

  function switchTab(key) {
    S.tab = key;
    var root = rootEl();
    if (root) {
      root.querySelectorAll('.dz-pane').forEach(function (p) {
        p.hidden = (p.getAttribute('data-pane') !== key);
      });
    }
    DZ.tabs('#diag_tabs', TABS, key, function (k) { switchTab(k); });
    if (key === 'inputs') loadInputs();
  }

  async function doQuery() {
    await load(true);
    if (S.tab === 'inputs') await loadInputs();
    DZ.toast('已重新查询现状诊断数据', 'ok');
  }

  function setMsg(html) { DZ.render('#diag_msg', html || ''); }

  // ------------------------------------------------------------- 三问链条
  function renderChain() {
    var box = document.getElementById('diag_chain');
    if (!box) return;
    var steps = ['有没有', '有没有执行', '有没有证据'];
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="三问链条">' +
      steps.map(function (t, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="三问第 ' + (i + 1) + ' 层：' + DZ.esc(t) + '">' +
            '<div class="dz-node-title">' + DZ.esc(t) + '</div>' +
          '</div>';
      }).join('') + '</div>';
  }

  // ------------------------------------------------------------- 新建表单
  function renderForm() {
    var box = document.getElementById('diag_form');
    if (!box) return;
    if (S.mode !== 'create') { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="card"><h3>新建诊断批次</h3>' +
      '<div class="form-narrow">' +
        '<label for="diag_title">诊断批次名称（必填）</label>' +
        '<input id="diag_title" maxlength="60" placeholder="例如：第二轮现状诊断（演示）">' +
        '<div class="dz-actions">' +
          '<button id="diag_create_submit" title="创建诊断批次">创建批次</button>' +
          '<button class="ghost" id="diag_create_cancel" title="取消">取消</button>' +
        '</div>' +
      '</div></div>';
    var sub = document.getElementById('diag_create_submit');
    if (sub) sub.onclick = submitCreate;
    var can = document.getElementById('diag_create_cancel');
    if (can) can.onclick = function () { S.mode = 'none'; renderForm(); };
  }

  async function submitCreate() {
    if (S.busy) return;
    var title = ((document.getElementById('diag_title') || {}).value || '').trim();
    if (!title) { setMsg(DZ.banner('bad', '诊断批次名称必填')); DZ.toast('请填写诊断批次名称', 'bad'); return; }
    S.busy = true;
    setMsg(DZ.banner('', '创建中…'));
    var res = await DZ.post(API.assessments, { title: title });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '创建失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('创建失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('诊断批次已创建', 'ok');
    S.mode = 'none';
    S.sel = res.assessmentId;
    await load(true);
  }

  // ------------------------------------------------------------- 指标
  function renderKpis(summary, list) {
    var s = summary || {};
    var a = s.answers || {};
    var drafts = list.filter(function (x) { return x.status !== 'submitted'; }).length;
    DZ.render('#diag_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('诊断维度', DZ.number(s.dimensions), '逐层覆盖', '') +
      DZ.kpi('每层三问', DZ.number(s.questions), '同一组问法', '') +
      DZ.kpi('诊断批次', DZ.number(list.length), '在办 ' + DZ.number(drafts) + ' 个', '') +
      DZ.kpi('有', DZ.number(a.yes), '基准判定', 'ok') +
      DZ.kpi('部分有', DZ.number(a.partial), '基准判定', 'warn') +
      DZ.kpi('无', DZ.number(a.no), '基准判定', 'bad') +
    '</div>');
  }

  // ------------------------------------------------------------- 批次列表
  function renderBatches() {
    var box = document.getElementById('diag_batches');
    if (!box) return;
    var list = assessments();
    if (!list.length) {
      box.innerHTML = DZ.empty('暂无诊断批次',
        '<button class="ghost" onclick="document.getElementById(\'diag_new\').click()" title="新建诊断批次">新建诊断批次</button>');
      return;
    }
    box.innerHTML = list.map(function (a) {
      var c = a.counts || { total: 0, answered: 0, evidenceReady: 0 };
      var on = a.assessmentId === S.sel;
      var style = on ? ' style="border-color:var(--brand);background:var(--brand-bg)"' : '';
      return '<div class="card" data-batch="' + DZ.esc(a.assessmentId) + '"' + style + '>' +
        '<h3>' + DZ.esc(a.title) + ' ' + statusBadge(a.status) + '</h3>' +
        '<div class="dz-metric"><span class="dz-metric-k">负责人</span>' +
          '<span class="dz-metric-v" style="text-align:right">' + DZ.esc(a.owner) + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">三问作答</span>' +
          '<span class="dz-metric-v" style="text-align:right">' + DZ.number(c.answered) + ' / ' + DZ.number(c.total) + '</span></div>' +
        '<div class="dz-metric"><span class="dz-metric-k">证据说明</span>' +
          '<span class="dz-metric-v" style="text-align:right">' + DZ.number(c.evidenceReady) + ' / ' + DZ.number(c.total) + '</span></div>' +
        '<div style="margin:6px 0 10px">' + DZ.bar(a.completion) + '</div>' +
        '<div class="dz-actions"><button class="ghost" data-open="' + DZ.esc(a.assessmentId) + '" title="选择该批次作答">' +
          (a.status === 'submitted' ? '查看作答' : '选择作答') + '</button></div>' +
      '</div>';
    }).join('');
    box.querySelectorAll('[data-open]').forEach(function (b) {
      b.onclick = function () {
        S.sel = b.getAttribute('data-open');
        S.edit = null;
        renderBatches(); renderWork();
        if (S.tab === 'inputs') loadInputs();
      };
    });
  }

  // ------------------------------------------------------------- 输入材料
  function renderInputForm(kinds) {
    var box = document.getElementById('diag_input_form');
    if (!box) return;
    box.innerHTML = '<div class="form-narrow">' +
      '<label for="diag_in_kind">材料类型</label>' +
      '<select id="diag_in_kind" title="选择材料类型">' +
        kinds.map(function (k) { return '<option value="' + DZ.esc(k) + '">' + DZ.esc(k) + '</option>'; }).join('') +
      '</select>' +
      '<label for="diag_in_file">选择文件</label>' +
      '<input type="file" id="diag_in_file" title="选择本地文件">' +
      '<label for="diag_in_name">材料名称（必填）</label>' +
      '<input id="diag_in_name" maxlength="80" placeholder="选择文件后自动带出，也可手动填写">' +
      '<label for="diag_in_note">材料说明</label>' +
      '<input id="diag_in_note" maxlength="120" placeholder="选填：用途或来源说明">' +
      '<div class="dz-actions"><button id="diag_in_submit" title="上传输入材料">上传材料</button></div>' +
    '</div>';

    var fi = document.getElementById('diag_in_file');
    if (fi) {
      fi.onchange = function () {
        var f = fi.files && fi.files[0];
        if (!f) return;
        S.inSize = f.size || 0;
        var nm = document.getElementById('diag_in_name');
        if (nm && !nm.value) nm.value = f.name || '';
      };
    }
    var sub = document.getElementById('diag_in_submit');
    if (sub) sub.onclick = submitInput;
  }

  async function submitInput() {
    if (S.inputBusy) return;
    var kind = ((document.getElementById('diag_in_kind') || {}).value || '').trim();
    var name = ((document.getElementById('diag_in_name') || {}).value || '').trim();
    var note = ((document.getElementById('diag_in_note') || {}).value || '').trim();
    if (!kind) { setMsg(DZ.banner('bad', '请选择材料类型')); DZ.toast('请选择材料类型', 'bad'); return; }
    if (!name) { setMsg(DZ.banner('bad', '材料名称必填')); DZ.toast('请填写材料名称', 'bad'); return; }
    var btn = document.getElementById('diag_in_submit');
    S.inputBusy = true;
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    var res = await DZ.post(API.inputs, { assessmentId: curAid(), kind: kind, fileName: name, note: note, size: S.inSize || 0 });
    S.inputBusy = false;
    if (btn) { btn.disabled = false; btn.textContent = '上传材料'; }
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '上传失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('上传失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('输入材料已上传', 'ok');
    S.inSize = 0;
    await loadInputs();
  }

  function renderInputKpis(res) {
    var box = document.getElementById('diag_input_kpis');
    if (!box) return;
    var s = res.summary || {};
    var by = s.byKind || {};
    var kinds = res.kinds || [];
    box.innerHTML = '<div class="dz-kpi-row">' +
      DZ.kpi('输入材料', DZ.number(s.total), '合计', '') +
      kinds.map(function (k) { return DZ.kpi(k, DZ.number(by[k] || 0), '按材料类型', ''); }).join('') +
    '</div>';
  }

  function renderInputList(res) {
    var box = document.getElementById('diag_input_list');
    if (!box) return;
    var items = res.inputs || [];
    if (!items.length) {
      box.innerHTML = DZ.empty('暂无输入材料，可在上方上传历史自查报告、工作佐证、资产配置信息或资产清单');
      return;
    }
    box.innerHTML = '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th style="width:130px">材料类型</th><th style="min-width:200px">材料名称</th>' +
      '<th style="min-width:180px">说明</th><th style="width:90px">大小</th>' +
      '<th style="width:150px">上传人</th><th style="width:160px">上传时间</th>' +
      '<th style="width:90px">操作</th>' +
      '</tr></thead><tbody>' + items.map(function (it) {
        return '<tr>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(it.kind) + '</span></td>' +
          '<td><b>' + DZ.esc(it.fileName) + '</b></td>' +
          '<td class="muted">' + DZ.esc(it.note || '—') + '</td>' +
          '<td>' + DZ.esc(fmtSize(it.size)) + '</td>' +
          '<td>' + DZ.esc(it.uploadedByName || it.uploadedBy || '—') + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(it.uploadedAt)) + '</td>' +
          '<td><button class="ghost" data-rm="' + DZ.esc(it.inputId) + '" data-name="' + DZ.esc(it.fileName) + '" title="移除该输入材料">移除</button></td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';

    box.onclick = function (e) {
      var b = e.target.closest('button[data-rm]');
      if (b) doRemoveInput(b.getAttribute('data-rm'), b.getAttribute('data-name'));
    };
  }

  async function doRemoveInput(inputId, name) {
    if (!inputId) return;
    var ok = true;
    try { ok = window.confirm('确定移除输入材料「' + (name || inputId) + '」？'); } catch (e) { ok = true; }
    if (!ok) return;
    var res = await DZ.del(API.inputs + '/' + encodeURIComponent(inputId));
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      DZ.toast('移除失败：' + m, 'bad'); return;
    }
    DZ.toast('已移除输入材料', 'ok');
    await loadInputs();
  }

  async function loadInputs() {
    var listBox = document.getElementById('diag_input_list');
    var kpiBox = document.getElementById('diag_input_kpis');
    if (listBox) listBox.innerHTML = DZ.skeleton(3);
    if (kpiBox) kpiBox.innerHTML = DZ.skeleton(1);
    var aid = curAid();
    var res = await DZ.get(API.inputs + '?assessmentId=' + encodeURIComponent(aid));
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '输入材料加载失败';
      if (kpiBox) kpiBox.innerHTML = '';
      if (listBox) listBox.innerHTML = DZ.banner('bad', msg, function () { loadInputs(); });
      return;
    }
    S.inputs = res;
    renderInputKpis(res);
    renderInputForm(res.kinds || []);
    renderInputList(res);
  }

  // ------------------------------------------------------------- 自动生成
  async function doGenerate() {
    if (S.busy) return;
    var a = current();
    if (!a) { setMsg(DZ.banner('bad', '请先选择一个诊断批次')); DZ.toast('请先选择诊断批次', 'bad'); return; }
    var btn = document.getElementById('diag_generate');
    S.busy = true;
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    var res = await DZ.post(API.generate(a.assessmentId), {});
    S.busy = false;
    if (btn) { btn.disabled = false; btn.textContent = '自动生成诊断报告'; }
    if (!res || res.error) {
      var code = res && res.error && res.error.code;
      var m = (res && res.error && res.error.message) || '自动生成失败';
      setMsg(DZ.banner(code === 'VALIDATION_FAILED' ? 'warn' : 'bad', m));
      DZ.toast('自动生成失败：' + m, 'bad');
      if (code === 'VALIDATION_FAILED') switchTab('inputs');
      return;
    }
    setMsg('');
    DZ.toast('已自动生成 ' + DZ.number(res.filled) + ' 条判定，保留 ' + DZ.number(res.kept) + ' 条人工修订', 'ok');
    await load(true);
  }

  // ------------------------------------------------------------- 条款与修订
  function renderWork() {
    var box = document.getElementById('diag_work');
    if (!box) return;
    var a = current();
    if (!a) { box.innerHTML = DZ.empty('请先在「诊断总览」选择一个诊断批次'); renderEdit(); return; }
    var idx = dimIndex();
    var readOnly = a.status === 'submitted';
    var answered = {};
    a.answers.forEach(function (x) { answered[dimTextKey(x.dimNo, x.q)] = x; });

    var groups = dimensions().map(function (d) {
      var rows = (d.answers || []).map(function (q) {
        var ans = answered[dimTextKey(d.no, q.q)] || { state: '', evidence: '', note: '' };
        var revised = isRevised(ans);
        var sel = '<select class="diag-state" data-dim="' + DZ.esc(d.no) + '" data-q="' + DZ.esc(q.q) + '"' +
          ' data-name="' + DZ.esc(d.name) + '" data-note="' + DZ.esc(ans.note || d.note || '') + '"' +
          (readOnly ? ' disabled' : '') + '>' +
          '<option value="">未判定</option>' + STATES.map(function (s) {
            return '<option value="' + s.v + '"' + (s.v === ans.state ? ' selected' : '') + '>' + DZ.esc(s.label) + '</option>';
          }).join('') + '</select>';
        var ev = readOnly
          ? (DZ.esc(ans.evidence) || '<span class="muted">—</span>')
          : '<input class="diag-evidence" data-dim="' + DZ.esc(d.no) + '" data-q="' + DZ.esc(q.q) + '"' +
            ' maxlength="120" placeholder="填写该项应留证据（必填）" value="' + DZ.esc(ans.evidence || '') + '">';
        var badge = revised
          ? ' <span class="badge b-ok" title="该条款已被人工修订，自动生成不会覆盖">已人工修订</span>' : '';
        var revBtn = ans.answerId
          ? '<button class="ghost" data-revise="' + DZ.esc(ans.answerId) + '"' +
            ' data-dim="' + DZ.esc(d.no) + '" data-q="' + DZ.esc(q.q) + '"' +
            ' data-state="' + DZ.esc(ans.state || '') + '" data-ev="' + DZ.esc(ans.evidence || '') + '"' +
            ' title="人工修订该条款的判定与证据">修订</button>'
          : '<span class="muted">—</span>';
        return '<tr>' +
          '<td><b>' + DZ.esc(q.q) + '</b></td>' +
          '<td>' + DZ.esc(q.text || idx[dimTextKey(d.no, q.q)] || '') + '</td>' +
          '<td>' + sel + '</td>' +
          '<td>' + ev + badge + '</td>' +
          '<td style="white-space:nowrap">' + revBtn + '</td>' +
        '</tr>';
      }).join('');
      return '<h4>维度 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + '</h4>' +
        '<div class="dz-table-wrap"><table><thead><tr>' +
          '<th style="width:110px">三问</th><th style="min-width:200px">对应现状</th>' +
          '<th style="width:120px">判定</th><th style="min-width:220px">证据说明</th>' +
          '<th style="width:80px">操作</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }).join('');

    var actions = readOnly
      ? '<div class="muted">该批次已提交，如需调整请新建一次诊断。</div>'
      : '<div class="dz-actions">' +
          '<button id="diag_save" title="保存当前作答">保存作答</button>' +
          '<button class="ghost" id="diag_submit" title="提交现状诊断">提交诊断</button>' +
        '</div>';

    box.innerHTML = '<div class="card"><h3>' + DZ.esc(a.title) + ' ' + statusBadge(a.status) + '</h3>' +
      actions + groups + '</div>';

    var save = document.getElementById('diag_save');
    if (save) save.onclick = saveAnswers;
    var sub = document.getElementById('diag_submit');
    if (sub) sub.onclick = submitAssessment;

    box.onclick = function (e) {
      var b = e.target.closest('button[data-revise]');
      if (b) {
        S.edit = {
          answerId: b.getAttribute('data-revise'), dimNo: b.getAttribute('data-dim'),
          q: b.getAttribute('data-q'), state: b.getAttribute('data-state'),
          evidence: b.getAttribute('data-ev')
        };
        renderEdit();
      }
    };
    renderEdit();
  }

  // 人工修订小表单
  function renderEdit() {
    var box = document.getElementById('diag_edit');
    if (!box) return;
    if (!S.edit) { box.innerHTML = ''; return; }
    var e = S.edit;
    box.innerHTML = '<div class="card"><h3>修订条款 · 维度 ' + DZ.esc(e.dimNo) + ' · ' + DZ.esc(e.q) + '</h3>' +
      '<div class="form-narrow">' +
        '<label for="diag_ed_state">判定结果</label>' +
        '<select id="diag_ed_state" title="选择判定结果">' + STATES.map(function (s) {
          return '<option value="' + s.v + '"' + (s.v === e.state ? ' selected' : '') + '>' + DZ.esc(s.label) + '</option>';
        }).join('') + '</select>' +
        '<label for="diag_ed_evidence">证据说明</label>' +
        '<textarea id="diag_ed_evidence" rows="3" maxlength="200" placeholder="填写该项应留证据或现状说明">' + DZ.esc(e.evidence || '') + '</textarea>' +
        '<div class="dz-actions">' +
          '<button id="diag_ed_save" title="保存本次修订">保存修订</button>' +
          '<button class="ghost" id="diag_ed_cancel" title="取消修订">取消</button>' +
        '</div>' +
        '<div class="muted">修订后的条款将标记为「已人工修订」，自动生成不会覆盖。</div>' +
      '</div></div>';
    var sv = document.getElementById('diag_ed_save');
    if (sv) sv.onclick = saveRevise;
    var cc = document.getElementById('diag_ed_cancel');
    if (cc) cc.onclick = function () { S.edit = null; renderEdit(); };
    try { box.scrollIntoView({ block: 'nearest' }); } catch (err) { /* 兜底 */ }
  }

  async function saveRevise() {
    if (S.busy || !S.edit) return;
    var e = S.edit;
    var state = ((document.getElementById('diag_ed_state') || {}).value || '');
    var evidence = ((document.getElementById('diag_ed_evidence') || {}).value || '').trim();
    if (!state) { setMsg(DZ.banner('bad', '请选择判定结果')); DZ.toast('请选择判定结果', 'bad'); return; }
    var btn = document.getElementById('diag_ed_save');
    S.busy = true;
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    var res = await DZ.post(API.revise(e.answerId), { state: state, evidence: evidence });
    S.busy = false;
    if (btn) { btn.disabled = false; btn.textContent = '保存修订'; }
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '修订失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('修订失败：' + m, 'bad'); return;
    }
    S.revised[e.answerId] = true;
    S.edit = null;
    setMsg('');
    DZ.toast('条款已修订为「' + (res.stateLabel || STATE_LABEL[state] || state) + '」', 'ok');
    await load(true);
  }

  function collect() {
    var rows = Array.prototype.slice.call(document.querySelectorAll('#diag_work .diag-state'));
    return rows.map(function (sel) {
      var q = sel.getAttribute('data-q');
      var dimNo = Number(sel.getAttribute('data-dim'));
      var evEl = document.querySelector('#diag_work .diag-evidence[data-dim="' + dimNo + '"][data-q="' + q + '"]');
      return {
        dimNo: dimNo, q: q, dimName: sel.getAttribute('data-name'),
        state: sel.value, note: sel.getAttribute('data-note') || '',
        evidence: evEl ? String(evEl.value || '').trim() : ''
      };
    });
  }

  async function saveAnswers(silent) {
    if (S.busy) return false;
    var a = current();
    if (!a) { setMsg(DZ.banner('bad', '请先选择一个诊断批次')); return false; }
    var answers = collect();
    if (!answers.length) { setMsg(DZ.banner('bad', '暂无可保存的作答内容')); return false; }
    S.busy = true;
    if (!silent) setMsg(DZ.banner('', '保存中…'));
    var res = await DZ.put(API.assessments + '/' + encodeURIComponent(a.assessmentId) + '/answers', { answers: answers });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '保存失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('保存失败：' + m, 'bad'); return false;
    }
    setMsg('');
    DZ.toast('已保存 ' + DZ.number(res.saved) + ' 项作答', 'ok');
    await load(true);
    return true;
  }

  async function submitAssessment() {
    if (S.busy) return;
    var a = current();
    if (!a) { setMsg(DZ.banner('bad', '请先选择一个诊断批次')); return; }
    var answers = collect();
    var missing = answers.filter(function (x) { return !x.state; }).length;
    var noEv = answers.filter(function (x) { return !x.evidence; }).length;
    if (missing) { setMsg(DZ.banner('bad', '三问判定未答完：还有 ' + missing + ' 项未作答，请先补齐')); DZ.toast('还有 ' + missing + ' 项未作答', 'bad'); return; }
    if (noEv) { setMsg(DZ.banner('bad', '证据说明未填完：还有 ' + noEv + ' 项缺少说明，请先补齐')); DZ.toast('还有 ' + noEv + ' 项缺少证据说明', 'bad'); return; }
    var ok = await saveAnswers(true);
    if (!ok) return;
    S.busy = true;
    setMsg(DZ.banner('', '提交中…'));
    var res = await DZ.post(API.assessments + '/' + encodeURIComponent(a.assessmentId) + '/submit', {});
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '提交失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('提交失败：' + m, 'bad'); return;
    }
    setMsg('');
    DZ.toast('现状诊断已提交', 'ok');
    await load(true);
  }

  // ------------------------------------------------------------- 装载
  async function load(force) {
    if (S.data && !force) {
      renderForm(); renderKpis(S.data.summary, assessments()); renderBatches(); renderWork();
      return;
    }
    var box = document.getElementById('diag_batches');
    if (box) box.innerHTML = DZ.skeleton(3);
    var kpiBox = document.getElementById('diag_kpis');
    if (kpiBox) kpiBox.innerHTML = DZ.skeleton(2);
    var res = await DZ.get(API.dimensions);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '现状诊断数据加载失败';
      DZ.render('#diag_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#diag_batches', DZ.empty('诊断数据暂不可用'));
      return;
    }
    S.data = res;
    var list = Array.isArray(res.assessments) ? res.assessments : [];
    if (!S.sel || !list.some(function (a) { return a.assessmentId === S.sel; })) {
      S.sel = list.length ? list[0].assessmentId : null;
    }
    renderForm();
    renderKpis(res.summary, list);
    renderBatches();
    renderWork();
    if (S.tab === 'inputs') loadInputs();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['diag'] = mount;
})();
