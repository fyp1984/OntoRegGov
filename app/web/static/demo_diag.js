/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   现状诊断（五个维度 × 三问「有没有 / 有没有执行 / 有没有证据」）
   · demo_diag.js
   视图 id：diag   容器：#diag_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   读：GET /api/diagnosis/dimensions（诊断批次与作答读自运行台账）
   写：POST /api/diagnosis/assessments（新建批次）、
      PUT /api/diagnosis/assessments/{id}/answers（保存作答）、
      POST /api/diagnosis/assessments/{id}/submit（提交，须全部作答且证据说明非空）
   前后端双重校验：三问判定取值、提交前完整性校验；失败 VALIDATION_FAILED。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { dimensions: '/api/diagnosis/dimensions', assessments: '/api/diagnosis/assessments' };
  var STATES = [{ v: 'yes', label: '有' }, { v: 'partial', label: '部分' }, { v: 'no', label: '缺' }];

  var S = { data: null, sel: null, mode: 'none', busy: false };

  function rootEl() { return document.getElementById('diag_root'); }

  function dimensions() { return (S.data && S.data.dimensions) || []; }
  function assessments() { return (S.data && S.data.assessments) || []; }
  function current() {
    return assessments().filter(function (a) { return a.assessmentId === S.sel; })[0] || null;
  }
  function statusBadge(st) {
    if (st === 'submitted') return DZ.badge('ok', '已提交');
    return DZ.badge('warn', '草稿');
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

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button id="diag_new" title="新建一次现状诊断批次" aria-label="新建诊断批次">新建诊断批次</button>' +
        '<button class="ghost" id="diag_refresh" title="重新拉取现状诊断数据" aria-label="刷新现状诊断">刷新</button>' +
        '<span class="muted">同一组三问逐层收紧：先问有没有，再问有没有执行，最后问有没有证据；三问都过，才拿到可核对的结论。</span>' +
      '</div>' +
      '<div id="diag_msg"></div>' +
      '<div id="diag_form"></div>' +
      '<div id="diag_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div class="card"><h3>三问链条</h3><div id="diag_chain">' + DZ.skeleton(1) + '</div></div>' +
      '<div class="card"><h3>诊断批次</h3><div id="diag_batches">' + DZ.skeleton(3) + '</div></div>' +
      '<div id="diag_work"></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var nb = document.getElementById('diag_new');
    if (nb) nb.onclick = function () { S.mode = (S.mode === 'create' ? 'none' : 'create'); renderForm(); };
    var rb = document.getElementById('diag_refresh');
    if (rb) rb.onclick = function () { load(true); };
    renderChain();
    load(false);
  }

  function setMsg(html) { DZ.render('#diag_msg', html || ''); }

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
      }).join('') + '</div>' +
      '<div class="muted">只答「有没有」，得到的是一张制度清单；三问都过，才拿到可核对的结论。</div>';
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
        '<div class="muted">创建后按五个维度 × 三问逐项作答，并为每一项补齐证据说明，然后提交。</div>' +
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
    DZ.toast('诊断批次已创建，已写入审计留痕', 'ok');
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
      DZ.kpi('部分', DZ.number(a.partial), '基准判定', 'warn') +
      DZ.kpi('缺', DZ.number(a.no), '基准判定', 'bad') +
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
        renderBatches(); renderWork();
      };
    });
  }

  // ------------------------------------------------------------- 作答区
  function renderWork() {
    var box = document.getElementById('diag_work');
    if (!box) return;
    var a = current();
    if (!a) { box.innerHTML = ''; return; }
    var idx = dimIndex();
    var readOnly = a.status === 'submitted';
    var answered = {};
    a.answers.forEach(function (x) { answered[dimTextKey(x.dimNo, x.q)] = x; });

    var groups = dimensions().map(function (d) {
      var rows = (d.answers || []).map(function (q) {
        var ans = answered[dimTextKey(d.no, q.q)] || { state: '', evidence: '', note: '' };
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
        return '<tr>' +
          '<td><b>' + DZ.esc(q.q) + '</b></td>' +
          '<td>' + DZ.esc(q.text || idx[dimTextKey(d.no, q.q)] || '') + '</td>' +
          '<td>' + sel + '</td>' +
          '<td>' + ev + '</td>' +
        '</tr>';
      }).join('');
      return '<h4>维度 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + '</h4>' +
        '<div class="dz-table-wrap"><table><thead><tr>' +
          '<th style="width:120px">三问</th><th style="min-width:220px">对应现状</th>' +
          '<th style="width:120px">判定</th><th style="min-width:220px">证据说明</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="dz-cite" style="margin-top:6px">' + DZ.esc(d.note || '—') + '</div>';
    }).join('');

    var actions = readOnly
      ? '<div class="muted">该批次已提交，不可再修改；如需调整请新建一次诊断。</div>'
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
    if (!answers.length) { setMsg(DZ.banner('bad', '暂无作答内容')); return false; }
    S.busy = true;
    if (!silent) setMsg(DZ.banner('', '保存中…'));
    var res = await DZ.put(API.assessments + '/' + encodeURIComponent(a.assessmentId) + '/answers', { answers: answers });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '保存失败';
      setMsg(DZ.banner('bad', m)); DZ.toast('保存失败：' + m, 'bad'); return false;
    }
    setMsg('');
    DZ.toast('已保存 ' + DZ.number(res.saved) + ' 项作答，已写入审计留痕', 'ok');
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
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['diag'] = mount;
})();
