/* ============================================================
   资产台账（demo_ledger.js）
   视图 id：ledger   容器：#ledger_root
   分类汇总 · 手工登记 · 存入知识库升版 · 从知识库同步
   读：GET /api/asset-ledger
   写：POST /api/asset-ledger、PUT /api/asset-ledger/{id}、DELETE /api/asset-ledger/{id}
   入库：POST /api/asset-ledger/{id}/push-kb
   同步：POST /api/asset-ledger/sync
   知识库清单：GET /api/kb/targets      责任部门：GET /api/admin/org-nodes
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = '/api/asset-ledger';
  var KB_API = '/api/kb/targets';
  var ORG_API = '/api/admin/org-nodes';

  var STATUS_KIND = { '在册': 'ok', '待更新': 'warn', '已入库': 'ok' };

  var S = {
    data: null, kbs: null, depts: null,
    filter: { cat: 'all', source: 'all', status: 'all' },
    mode: 'none', editId: null, pushId: null, syncOpen: false, confirmDel: null,
    busy: false
  };

  function rootEl() { return document.getElementById('ledger_root'); }
  function assets() { return (S.data && S.data.assets) || []; }
  function cats() { return (S.data && S.data.categories) || ['应用资产', '配置管理', '数据资产', '制度办法', '接口清单']; }
  function sources() { return (S.data && S.data.sources) || ['系统对接', '手工上传', '治理回写']; }
  function statuses() { return (S.data && S.data.statuses) || ['在册', '待更新', '已入库']; }
  function editAsset() { return assets().filter(function (a) { return a.assetId === S.editId; })[0] || null; }
  function findAsset(id) { return assets().filter(function (a) { return a.assetId === id; })[0] || null; }

  function filtered() {
    return assets().filter(function (a) {
      if (S.filter.cat !== 'all' && a.category !== S.filter.cat) return false;
      if (S.filter.source !== 'all' && a.source !== S.filter.source) return false;
      if (S.filter.status !== 'all' && a.status !== S.filter.status) return false;
      return true;
    });
  }

  function nextVersion(v) {
    var m = /(\d+)\s*$/.exec(v || '');
    return m ? ('v' + (parseInt(m[1], 10) + 1)) : 'v2';
  }

  function statusBadge(s) { return DZ.badge(STATUS_KIND[s] || 'unk', s || '—'); }
  function kbBadge(on) { return DZ.badge(on ? 'ok' : 'unk', on ? '已入库' : '未入库'); }

  // ---------------------------------------------------------------- 骨架
  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button id="ledger_query" title="按当前条件重新查询资产台账">查询</button>' +
        '<button class="ghost" id="ledger_new" title="手工登记一条资产">登记资产</button>' +
        '<button class="ghost" id="ledger_sync" title="从知识库加载资产记录">从知识库同步</button>' +
        '<span class="muted" id="ledger_srcnote"></span>' +
      '</div>' +
      '<div id="ledger_msg"></div>' +
      '<div id="ledger_op"></div>' +
      '<div id="ledger_form"></div>' +
      '<div id="ledger_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="ledger_summary"></div>' +
      '<div class="card"><h3>资产清单</h3>' +
        '<div id="ledger_table" class="dz-table-wrap">' + DZ.skeleton(5) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    S.pushId = null; S.syncOpen = false; S.confirmDel = null;
    var q = document.getElementById('ledger_query');
    if (q) q.onclick = function () { S.confirmDel = null; load(true); };
    var n = document.getElementById('ledger_new');
    if (n) n.onclick = function () { openCreate(); };
    var sy = document.getElementById('ledger_sync');
    if (sy) sy.onclick = function () { openSync(); };
    if (S.data && !S.busy) { renderAll(); }
    load(false);
  }

  function setMsg(html) { DZ.render('#ledger_msg', html || ''); }

  // ---------------------------------------------------------------- 取数
  function ensureKbs() {
    if (S.kbs) return Promise.resolve(S.kbs);
    return DZ.get(KB_API).then(function (res) {
      if (res && res.targets) S.kbs = res.targets;
      return S.kbs;
    });
  }

  function ensureDepts() {
    if (S.depts) return Promise.resolve(S.depts);
    return DZ.get(ORG_API).then(function (res) {
      var out = [];
      (function walk(nodes) {
        (nodes || []).forEach(function (x) {
          out.push({ id: x.node_id, name: x.name });
          if (x.children) walk(x.children);
        });
      })(res && res.tree);
      S.depts = out;
      return out;
    }).catch(function () { S.depts = []; return []; });
  }

  async function load(force) {
    if (S.data && !force) { renderAll(); return; }
    var t = document.getElementById('ledger_table');
    if (t) t.innerHTML = DZ.skeleton(5);
    DZ.render('#ledger_kpis', DZ.skeleton(2));
    var res = (await Promise.all([DZ.get(API), ensureDepts()]))[0];
    if (!res || res.error) {
      if (t) t.innerHTML = DZ.empty('资产台账暂不可用');
      DZ.render('#ledger_kpis', '');
      DZ.render('#ledger_summary', '');
      var msg = (res && res.error && res.error.message) || '资产台账加载失败';
      setMsg(DZ.banner('bad', msg, function () { load(true); }));
      return;
    }
    S.data = res;
    setMsg('');
    renderAll();
  }

  function renderAll() {
    renderNote();
    renderKpis(S.data.summary || {});
    renderSummary();
    renderTable();
    renderForm();
    renderOp();
  }

  function renderNote() {
    var env = S.data || {};
    var n = assets().length;
    DZ.render('#ledger_srcnote', '共 ' + DZ.esc(String(n)) + ' 条 · 取数 ' + DZ.esc(DZ.date(env.fetchedAt)));
  }

  // ---------------------------------------------------------------- KPI
  function renderKpis(s) {
    var catCount = (s.byCategory || []).length;
    DZ.render('#ledger_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('资产总数', DZ.number(s.total), '在册全部资产', '') +
      DZ.kpi('已入库知识库', DZ.number(s.inKnowledgeBase), '已生成知识文档', 'ok') +
      DZ.kpi('待更新', DZ.number(s.pendingUpdate), '需升版的过时资产', 'warn') +
      DZ.kpi('资产类别', DZ.number(catCount), '按类别汇总', '') +
    '</div>');
  }

  // ---------------------------------------------------------------- 分类汇总与筛选
  function chipbar(group, items) {
    return '<div class="dz-chipbar" data-group="' + group + '">' + items.map(function (it) {
      var on = S.filter[group] === it.key;
      return '<button class="dz-chip' + (on ? ' on' : '') + '" data-v="' + DZ.esc(it.key) +
        '" title="' + DZ.esc(it.label) + '">' + DZ.esc(it.label) + '</button>';
    }).join('') + '</div>';
  }

  function countBy(field) {
    var m = {};
    assets().forEach(function (a) { var k = a[field] || '—'; m[k] = (m[k] || 0) + 1; });
    return m;
  }

  function renderSummary() {
    var box = document.getElementById('ledger_summary');
    if (!box) return;
    var catN = countBy('category'), srcN = countBy('source'), stN = countBy('status');

    function items(valueList, cnt, total) {
      var list = [{ key: 'all', label: '全部 ' + total }];
      valueList.forEach(function (v) { if (cnt[v]) list.push({ key: v, label: v + ' ' + cnt[v] }); });
      return list;
    }

    box.innerHTML = '<div class="card"><h3>分类汇总</h3>' +
      '<div class="muted">按类别</div>' + chipbar('cat', items(cats(), catN, assets().length)) +
      '<div class="muted" style="margin-top:8px">按来源</div>' + chipbar('source', items(sources(), srcN, assets().length)) +
      '<div class="muted" style="margin-top:8px">按状态</div>' + chipbar('status', items(statuses(), stN, assets().length)) +
    '</div>';

    box.querySelectorAll('.dz-chipbar').forEach(function (bar) {
      var g = bar.getAttribute('data-group');
      bar.querySelectorAll('.dz-chip').forEach(function (c) {
        c.onclick = function () {
          S.filter[g] = c.getAttribute('data-v');
          renderSummary(); renderTable();
        };
      });
    });
  }

  // ---------------------------------------------------------------- 表格
  function renderTable() {
    var box = document.getElementById('ledger_table');
    if (!box) return;
    var list = filtered();
    if (!list.length) {
      box.innerHTML = DZ.empty('当前筛选条件下暂无资产',
        '<button class="ghost" id="ledger_empty_new" title="手工登记一条资产">登记资产</button>');
      var eb = document.getElementById('ledger_empty_new');
      if (eb) eb.onclick = openCreate;
      return;
    }
    box.innerHTML = '<table>' +
      '<thead><tr>' +
        '<th style="min-width:180px">名称</th><th>类别</th><th>来源</th>' +
        '<th style="min-width:110px">责任部门</th><th>版本</th><th>状态</th>' +
        '<th>是否已入知识库</th><th style="min-width:130px">更新时间</th>' +
        '<th style="min-width:210px">操作</th>' +
      '</tr></thead><tbody>' +
      list.map(function (a) {
        var confirming = S.confirmDel === a.assetId;
        var actions;
        if (confirming) {
          actions = '<button class="ghost" data-del-yes="' + DZ.esc(a.assetId) + '" title="确认移除该资产">确认移除</button>' +
                    '<button class="ghost" data-del-no="' + DZ.esc(a.assetId) + '" title="取消移除">取消</button>';
        } else {
          var kbBtn = a.inKnowledgeBase
            ? '<button data-push="' + DZ.esc(a.assetId) + '" title="再次推送将升版">版本更新</button>'
            : '<button data-push="' + DZ.esc(a.assetId) + '" title="存入知识库">存入知识库</button>';
          actions = kbBtn +
            '<button class="ghost" data-edit="' + DZ.esc(a.assetId) + '" title="编辑资产">编辑</button>' +
            '<button class="ghost" data-del="' + DZ.esc(a.assetId) + '" title="移除资产">移除</button>';
        }
        return '<tr>' +
          '<td><b>' + DZ.esc(a.name) + '</b></td>' +
          '<td>' + DZ.pill(a.category || '—') + '</td>' +
          '<td>' + DZ.esc(a.source || '—') + '</td>' +
          '<td>' + DZ.esc(a.deptName || '—') + '</td>' +
          '<td>' + DZ.esc(a.version || '—') + '</td>' +
          '<td>' + statusBadge(a.status) + '</td>' +
          '<td>' + kbBadge(a.inKnowledgeBase) + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(a.updatedAt)) + '</td>' +
          '<td><div class="dz-actions" style="margin:0;justify-content:flex-start">' + actions + '</div></td>' +
        '</tr>';
      }).join('') + '</tbody></table>';

    box.querySelectorAll('[data-push]').forEach(function (b) {
      b.onclick = function () { openPush(b.getAttribute('data-push')); };
    });
    box.querySelectorAll('[data-edit]').forEach(function (b) {
      b.onclick = function () { openEdit(b.getAttribute('data-edit')); };
    });
    box.querySelectorAll('[data-del]').forEach(function (b) {
      b.onclick = function () { S.confirmDel = b.getAttribute('data-del'); renderTable(); };
    });
    box.querySelectorAll('[data-del-no]').forEach(function (b) {
      b.onclick = function () { S.confirmDel = null; renderTable(); };
    });
    box.querySelectorAll('[data-del-yes]').forEach(function (b) {
      b.onclick = function () { removeAsset(b.getAttribute('data-del-yes')); };
    });
  }

  // ---------------------------------------------------------------- 登记 / 编辑表单
  function openCreate() { S.mode = 'create'; S.editId = null; S.confirmDel = null; renderForm(); scrollForm(); }
  function openEdit(id) { S.mode = 'edit'; S.editId = id; S.confirmDel = null; renderForm(); scrollForm(); }
  function closeForm() { S.mode = 'none'; S.editId = null; renderForm(); }

  function deptField(selId) {
    if (S.depts && S.depts.length) {
      var opts = '<option value=""' + (!selId ? ' selected' : '') + '>（未指定）</option>' +
        S.depts.map(function (d) {
          return '<option value="' + DZ.esc(d.id) + '"' + (d.id === selId ? ' selected' : '') + '>' + DZ.esc(d.name) + '</option>';
        }).join('');
      return '<select id="lg_dept">' + opts + '</select>';
    }
    return '<input id="lg_dept" maxlength="40" placeholder="责任部门（选填）" value="">';
  }

  function renderForm() {
    var box = document.getElementById('ledger_form');
    if (!box) return;
    if (S.mode === 'none') { box.innerHTML = ''; return; }
    var r = S.mode === 'edit' ? editAsset() : null;
    if (S.mode === 'edit' && !r) { box.innerHTML = ''; return; }
    var v = r || { name: '', category: cats()[0] || '', source: '手工上传', deptId: '', version: 'v1', note: '' };

    var catOpts = cats().map(function (c) {
      return '<option value="' + DZ.esc(c) + '"' + (c === v.category ? ' selected' : '') + '>' + DZ.esc(c) + '</option>';
    }).join('');
    var srcOpts = sources().map(function (s) {
      return '<option value="' + DZ.esc(s) + '"' + (s === v.source ? ' selected' : '') + '>' + DZ.esc(s) + '</option>';
    }).join('');

    box.innerHTML = '<div class="card"><h3>' + (S.mode === 'edit' ? '编辑资产' : '登记资产') + '</h3>' +
      '<div class="grid2">' +
        '<div><label for="lg_name">名称（必填）</label>' +
          '<input id="lg_name" maxlength="60" placeholder="例如：数据分类分级操作指引" value="' + DZ.esc(v.name) + '"></div>' +
        '<div><label for="lg_cat">类别（必填）</label>' +
          '<select id="lg_cat">' + catOpts + '</select></div>' +
        '<div><label for="lg_src">来源（必填）</label>' +
          '<select id="lg_src">' + srcOpts + '</select></div>' +
        '<div><label for="lg_dept">责任部门</label>' + deptField(v.deptId) + '</div>' +
        '<div><label for="lg_ver">版本</label>' +
          '<input id="lg_ver" maxlength="20" placeholder="例如：v1" value="' + DZ.esc(v.version) + '"></div>' +
        '<div><label for="lg_note">说明（选填）</label>' +
          '<input id="lg_note" maxlength="120" placeholder="资产用途或备注" value="' + DZ.esc(v.note) + '"></div>' +
      '</div>' +
      '<div class="dz-actions">' +
        '<button id="lg_submit" title="保存资产">' + (S.mode === 'edit' ? '保存修改' : '登记') + '</button>' +
        '<button class="ghost" id="lg_cancel" title="取消">取消</button>' +
      '</div></div>';

    var sub = document.getElementById('lg_submit');
    if (sub) sub.onclick = submitForm;
    var can = document.getElementById('lg_cancel');
    if (can) can.onclick = closeForm;
  }

  function scrollForm() {
    var f = document.getElementById('ledger_form');
    if (f && f.scrollIntoView) f.scrollIntoView({ block: 'nearest' });
  }

  function val(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }

  async function submitForm() {
    if (S.busy) return;
    var payload = {
      name: val('lg_name'), category: val('lg_cat'), source: val('lg_src'),
      deptId: val('lg_dept'), version: val('lg_ver'), note: val('lg_note')
    };
    if (!payload.name) { setMsg(DZ.banner('bad', '「名称」必填')); DZ.toast('「名称」必填', 'bad'); return; }
    if (!payload.category) { setMsg(DZ.banner('bad', '「类别」必填')); DZ.toast('「类别」必填', 'bad'); return; }
    S.busy = true;
    var btn = document.getElementById('lg_submit');
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    var edit = S.mode === 'edit';
    var res = edit
      ? await DZ.put(API + '/' + encodeURIComponent(S.editId), payload)
      : await DZ.post(API, payload);
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '保存失败';
      if (btn) { btn.disabled = false; btn.textContent = edit ? '保存修改' : '登记'; }
      setMsg(DZ.banner('bad', m));
      DZ.toast('保存失败：' + m, 'bad');
      return;
    }
    setMsg('');
    DZ.toast(edit ? '资产已更新' : '资产已登记', 'ok');
    S.mode = 'none'; S.editId = null;
    await load(true);
  }

  async function removeAsset(id) {
    if (S.busy) return;
    S.busy = true;
    S.confirmDel = null;
    var res = await DZ.del(API + '/' + encodeURIComponent(id));
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '移除失败';
      setMsg(DZ.banner('bad', m));
      DZ.toast('移除失败：' + m, 'bad');
      renderTable();
      return;
    }
    setMsg('');
    DZ.toast('资产已移除', 'ok');
    if (S.editId === id) { S.mode = 'none'; S.editId = null; }
    await load(true);
  }

  // ---------------------------------------------------------------- 存入知识库
  function openPush(id) {
    S.pushId = id; S.syncOpen = false; S.confirmDel = null;
    renderTable();
    renderOp();
    ensureKbs().then(function () { renderOp(); });
  }

  function kbOptions(sel) {
    if (!S.kbs) return '';
    var def = sel || (S.kbs.filter(function (k) { return k.kbId === 'kt-inner'; })[0] || S.kbs[0] || {}).kbId;
    return S.kbs.map(function (k) {
      return '<option value="' + DZ.esc(k.kbId) + '"' + (k.kbId === def ? ' selected' : '') + '>' +
        DZ.esc(k.name) + (k.kind ? '（' + DZ.esc(k.kind) + '）' : '') + '</option>';
    }).join('');
  }

  function renderOp() {
    var box = document.getElementById('ledger_op');
    if (!box) return;
    if (S.pushId) { box.innerHTML = pushPanel(); bindPush(); }
    else if (S.syncOpen) { box.innerHTML = syncPanel(); bindSync(); }
    else { box.innerHTML = ''; }
  }

  function pushPanel() {
    var a = findAsset(S.pushId);
    if (!a) { S.pushId = null; return ''; }
    var inKB = !!a.inKnowledgeBase;
    var body = S.kbs
      ? '<div class="grid2">' +
          '<div><label for="lg_push_kb">目标知识库（必选）</label><select id="lg_push_kb">' + kbOptions() + '</select></div>' +
          '<div><label>版本变化</label><div class="row" style="margin:0">' +
            '<span class="pill">当前 ' + DZ.esc(a.version || '—') + '</span>' +
            '<span class="muted">→</span>' +
            '<span class="pill">推送后 ' + DZ.esc(nextVersion(a.version)) + '</span>' +
          '</div></div>' +
        '</div>' +
        '<div class="muted" style="margin-top:6px">' +
          (inKB ? '该资产已入库：再次推送按「过时文档升版」处理，版本号加一，状态回到「待专家审核」。'
                : '首次推送将在所选知识库新建知识文档并登记版本。') +
        '</div>'
      : DZ.skeleton(2);
    return '<div class="card"><h3>存入知识库 · ' + DZ.esc(a.name) + '</h3>' + body +
      '<div class="dz-actions" style="justify-content:flex-start">' +
        '<button id="lg_push_go" title="确认存入知识库">' + (inKB ? '确认升版' : '确认存入') + '</button>' +
        '<button class="ghost" id="lg_push_cancel" title="取消">取消</button>' +
      '</div></div>';
  }

  function bindPush() {
    var go = document.getElementById('lg_push_go');
    if (go) go.onclick = submitPush;
    var can = document.getElementById('lg_push_cancel');
    if (can) can.onclick = function () { S.pushId = null; renderOp(); };
  }

  async function submitPush() {
    if (S.busy || !S.pushId) return;
    var a = findAsset(S.pushId);
    var inKB = !!(a && a.inKnowledgeBase);
    var sel = document.getElementById('lg_push_kb');
    var kbId = sel ? sel.value : '';
    if (!kbId) { DZ.toast('请先选择目标知识库', 'bad'); return; }
    S.busy = true;
    var go = document.getElementById('lg_push_go');
    if (go) { go.disabled = true; go.textContent = '处理中…'; }
    var res = await DZ.post(API + '/' + encodeURIComponent(S.pushId) + '/push-kb', { kbId: kbId });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '存入失败';
      if (go) { go.disabled = false; go.textContent = inKB ? '确认升版' : '确认存入'; }
      DZ.toast('存入失败：' + m, 'bad');
      return;
    }
    DZ.toast(inKB ? ('已升版至 ' + res.version) : ('已存入知识库（' + res.version + '）'), 'ok');
    S.pushId = null;
    await load(true);
  }

  // ---------------------------------------------------------------- 从知识库同步
  function openSync() {
    S.syncOpen = true; S.pushId = null; S.confirmDel = null;
    renderOp();
    ensureKbs().then(function () { renderOp(); });
  }

  function syncPanel() {
    var body = S.kbs
      ? '<div><label for="lg_sync_kb">来源知识库（必选）</label><select id="lg_sync_kb">' + kbOptions() + '</select></div>' +
        '<div class="muted" style="margin-top:6px">将该知识库中尚未登记到台账的文档加载为资产记录（类别「制度办法」、来源「系统对接」）。</div>'
      : DZ.skeleton(2);
    return '<div class="card"><h3>从知识库同步</h3>' + body +
      '<div class="dz-actions" style="justify-content:flex-start">' +
        '<button id="lg_sync_go" title="开始同步">开始同步</button>' +
        '<button class="ghost" id="lg_sync_cancel" title="取消">取消</button>' +
      '</div></div>';
  }

  function bindSync() {
    var go = document.getElementById('lg_sync_go');
    if (go) go.onclick = submitSync;
    var can = document.getElementById('lg_sync_cancel');
    if (can) can.onclick = function () { S.syncOpen = false; renderOp(); };
  }

  async function submitSync() {
    if (S.busy) return;
    var sel = document.getElementById('lg_sync_kb');
    var kbId = sel ? sel.value : '';
    if (!kbId) { DZ.toast('请先选择知识库', 'bad'); return; }
    S.busy = true;
    var go = document.getElementById('lg_sync_go');
    if (go) { go.disabled = true; go.textContent = '处理中…'; }
    var res = await DZ.post(API + '/sync', { kbId: kbId });
    S.busy = false;
    if (!res || res.error) {
      var m = (res && res.error && res.error.message) || '同步失败';
      if (go) { go.disabled = false; go.textContent = '开始同步'; }
      DZ.toast('同步失败：' + m, 'bad');
      return;
    }
    var added = res.added || 0;
    DZ.toast(added > 0 ? ('已从知识库加载 ' + added + ' 条资产') : '未发现需要加载的新文档', 'ok');
    S.syncOpen = false;
    await load(true);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['ledger'] = mount;
})();
