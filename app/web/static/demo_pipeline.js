/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo：知识发布
   承载视图：
     - pipeline → 容器 #pipeline_root（知识库平台对接 · 知识发布治理）
   依赖：demo_common.js 提供的全局 window.DZ（严格只用 DZ.*），样式只用 dz- 前缀。
   新增对接：GET /api/kb/targets、/api/kb/documents、/api/kb/documents/{id}、
             /api/kb/change-log、/api/kb/call-log
             写：POST /api/kb/documents、/{id}/publish、/{id}/review、/{id}/versions
   保留既有：知识重建发布总览 / 版本历史 / 外部采集 / 分类映射 等既有能力。
   ============================================================ */
(function(){
  'use strict';

  var DZ = window.DZ;
  if (!DZ){ return; }

  // ---------- 视图容器与接口路径 ----------
  var ROOT_P = '#pipeline_root';
  var API = {
    // 知识发布治理（对接知识库平台）
    kbTargets:      '/api/kb/targets',
    kbDocuments:    '/api/kb/documents',
    kbDocument:     function(id){ return '/api/kb/documents/' + encodeURIComponent(id); },
    kbPublish:      function(id){ return '/api/kb/documents/' + encodeURIComponent(id) + '/publish'; },
    kbReview:       function(id){ return '/api/kb/documents/' + encodeURIComponent(id) + '/review'; },
    kbVersions:     function(id){ return '/api/kb/documents/' + encodeURIComponent(id) + '/versions'; },
    kbChangeLog:    '/api/kb/change-log',
    kbCallLog:      '/api/kb/call-log',
    // 既有重建发布
    pubStatus:      '/api/kb/publish/status',
    pubHistory:     '/api/kb/publish/history',
    pubCreate:      '/api/kb/publish',
    pubRun:         function(id){ return '/api/kb/publish/run/' + encodeURIComponent(id); },
    pubRollback:    '/api/kb/publish/rollback',
    pubManifest:    '/api/kb/publish/manifest',
    catMapping:     '/api/kb/category-mapping',
    collectTasks:   '/api/kb/collect/tasks',
    collectRun:     '/api/kb/collect/run',
    collectDecision: function(id){ return '/api/kb/collect/' + encodeURIComponent(id) + '/decision'; }
  };

  // 发布四阶段（与后端阶段序列对应）
  var STAGES = ['变更感知', '增量重建', '质量校验', '整版发布'];
  var TOTAL_MS = 6400;

  var TRIGGER_LABEL = {manual:'手动触发', schedule:'定时轮询', inbound:'变更推送'};
  var MODE_LABEL = {incremental:'增量', full:'全量'};
  var CTYPE_LABEL = {notice:'通知公告', guideline:'指引', standard:'标准', law:'法规', policy:'政策', regulation:'监管规则'};

  // 知识文档状态
  var DOC_STATUS = {
    draft:['unk','草稿'], pending_review:['warn','待专家审核'],
    published:['ok','已入库'], rejected:['bad','已退回']
  };
  var STATUS_OPTS = [['','全部状态'], ['draft','草稿'], ['pending_review','待专家审核'],
                     ['published','已入库'], ['rejected','已退回']];

  // ---------- 模块内状态 ----------
  var plState = {
    currentVersion: '',
    manifestAll: [], manFilter: 'all',
    collectFilter: '', collectCounts: {}, collectAll: null,
    tab: 'docs',
    kbTargets: null,
    docFilter: {kbId:'', status:''},
    docs: null,
    docForm: false, docSel: null, docDetail: null, docBusy: false,
    clFilter: '', clData: null,
    callFilter: '', callData: null
  };
  var plTimer = null;   // 发布作业轮询计时器

  // 页签定义：新治理能力在前，既有重建发布能力在后。
  var PL_TABS = [
    { key: 'docs',      label: '知识文档' },
    { key: 'changelog', label: '变更清单' },
    { key: 'calllog',   label: '调用日志' },
    { key: 'overview',  label: '发布总览' },
    { key: 'manifest',  label: '发布文档清单' },
    { key: 'history',   label: '版本历史' },
    { key: 'collect',   label: '外部采集' },
    { key: 'mapping',   label: '分类映射' }
  ];

  // ---------- 通用小工具 ----------
  function isErr(r){ return !!(r && r.error); }
  function errMsg(r){ return (r && r.error && r.error.message) || '接口返回异常'; }
  function errCode(r){ return (r && r.error && r.error.code) || ''; }
  function fmtMs(ms){
    if (ms == null || ms === '') return '—';
    var n = Number(ms); if (!isFinite(n)) return '—';
    return n >= 1000 ? (n / 1000).toFixed(1) + ' 秒' : Math.round(n) + ' 毫秒';
  }
  function shortHash(h){
    var s = String(h == null ? '' : h);
    return s.length > 12 ? (s.slice(0, 12) + '…') : (s || '—');
  }
  function shortUrl(u){
    var s = String(u == null ? '' : u);
    if (!s) return '—';
    var m = s.replace(/^https?:\/\//i, '');
    return m.length > 42 ? (m.slice(0, 42) + '…') : m;
  }
  function statusText(s){
    return ({running:'进行中', success:'成功', failed:'失败', pending:'待处理'})[s] || s || '—';
  }
  function manBadge(s){
    var m = {published:['ok','已发布'], built:['ok','已构建'], failed:['bad','构建失败'], stale:['warn','待重建']};
    var x = m[s] || ['unk', s || '—'];
    return DZ.badge(x[0], x[1]);
  }
  function collectBadge(s){
    var m = {pending:['warn','待审核'], approved:['ok','已通过'], rejected:['bad','已驳回']};
    var x = m[s] || ['unk', s || '—'];
    return DZ.badge(x[0], x[1]);
  }
  function docBadge(status, label){
    var x = DOC_STATUS[status] || ['unk', label || status || '—'];
    return DZ.badge(x[0], label || x[1]);
  }
  function row(k, v){
    return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
      '<span class="dz-metric-v">' + v + '</span></div>';
  }
  function chipBtn(k, label, n, active){
    return '<button class="dz-chip' + (active ? ' on' : '') + '" data-st="' + DZ.esc(k) + '"' +
      ' title="按' + DZ.esc(label) + '筛选">' + DZ.esc(label) + (n != null ? ' ' + n : '') + '</button>';
  }

  /* ==========================================================================
     视图骨架
     ========================================================================== */
  function pipelineShell(){
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="pl_query" title="重新查询知识发布数据" aria-label="查询">查询</button>' +
        '<span class="muted dz-toolbar-note" id="pl_current">当前版本 —</span>' +
      '</div>' +
      '<div id="pl_tabs"></div>' +

      // 页签一：知识文档（对接知识库平台 · 选库与类型 · 上传/采集 · 专家审核 · 版本与日志）
      '<div class="dz-pane" data-pane="docs">' +
        '<div id="pl_doc_form"></div>' +
        '<div id="pl_docs_kpis"></div>' +
        '<div class="card"><h3>知识文档清单</h3>' +
          '<div class="dz-toolbar">' +
            '<button id="pl_doc_new_btn" title="新建知识文档">新建文档</button>' +
            '<select id="pl_doc_kb_filter" title="按知识库筛选" aria-label="按知识库筛选"></select>' +
            '<select id="pl_doc_status_filter" title="按状态筛选" aria-label="按状态筛选"></select>' +
            '<button class="ghost" id="pl_doc_apply" title="应用筛选条件">筛选</button>' +
          '</div>' +
          '<div id="pl_docs_list"></div>' +
        '</div>' +
        '<div id="pl_doc_detail"></div>' +
      '</div>' +

      // 页签二：知识变更清单
      '<div class="dz-pane" data-pane="changelog" hidden>' +
        '<div class="card"><h3>知识变更清单</h3>' +
          '<div id="pl_cl_chips"></div>' +
          '<div id="pl_changelog"></div>' +
        '</div>' +
      '</div>' +

      // 页签三：知识调用日志
      '<div class="dz-pane" data-pane="calllog" hidden>' +
        '<div class="card"><h3>知识调用日志</h3>' +
          '<div id="pl_call_chips"></div>' +
          '<div id="pl_calllog"></div>' +
        '</div>' +
      '</div>' +

      // 页签四：发布总览（既有）
      '<div class="dz-pane" data-pane="overview" hidden>' +
        '<div class="dz-toolbar">' +
          '<button id="pl_trigger_btn" title="手动触发一次重建发布" aria-label="手动触发重建">手动触发重建</button>' +
          '<select id="pl_mode" title="选择重建模式" aria-label="重建模式">' +
            '<option value="incremental">增量重建</option>' +
            '<option value="full">全量重建</option>' +
          '</select>' +
        '</div>' +
        '<div id="pl_overview"></div>' +
        '<div class="grid2">' +
          '<div class="card"><h3>发布前质量校验</h3><div id="pl_gate"></div></div>' +
          '<div class="card"><h3>变更感知通道</h3><div id="pl_channels"></div></div>' +
        '</div>' +
      '</div>' +

      // 页签五：发布文档清单（既有）
      '<div class="dz-pane" data-pane="manifest" hidden>' +
        '<div class="card"><h3>发布文档清单</h3><div id="pl_manifest"></div></div>' +
      '</div>' +

      // 页签六：版本历史（既有）
      '<div class="dz-pane" data-pane="history" hidden>' +
        '<div class="card"><h3>版本历史与回滚</h3><div id="pl_history"></div></div>' +
      '</div>' +

      // 页签七：外部采集与入库审核（既有）
      '<div class="dz-pane" data-pane="collect" hidden>' +
        '<div class="card"><h3>外部采集与入库审核</h3>' +
          '<div class="dz-toolbar">' +
            '<button id="pl_collect_run" title="立即执行一次外部采集" aria-label="立即采集">立即采集</button>' +
          '</div>' +
          '<div id="pl_collect_hint"></div>' +
          '<div id="pl_collect"></div>' +
        '</div>' +
      '</div>' +

      // 页签八：知识库分类映射（既有）
      '<div class="dz-pane" data-pane="mapping" hidden>' +
        '<div class="card"><h3>知识库分类映射</h3>' +
          '<div class="row">' +
            '<button class="ghost" id="pl_map_add" title="新增一条映射">新增一行</button>' +
            '<button id="pl_map_save" title="保存分类映射">保存映射</button>' +
            '<span class="muted" id="pl_map_status"></span>' +
          '</div>' +
          '<div id="pl_mapping"></div>' +
        '</div>' +
      '</div>';
  }

  // ---------- 页签渲染与切换 ----------
  function renderPlTabs(){
    DZ.tabs('#pl_tabs', PL_TABS, plState.tab, function(key){ switchPlTab(key); });
  }

  function switchPlTab(key){
    plState.tab = key;
    var root = document.querySelector(ROOT_P);
    if (root){
      Array.prototype.forEach.call(root.querySelectorAll('.dz-pane'), function(p){
        p.hidden = (p.getAttribute('data-pane') !== key);
      });
    }
    renderPlTabs();
  }

  function pipelineInit(){
    if (plTimer){ clearInterval(plTimer); plTimer = null; }
    var root = document.querySelector(ROOT_P);
    if (!root) return;
    root.innerHTML = pipelineShell();

    switchPlTab(plState.tab);
    renderChannels();
    bindPipeline();
    loadDocTargets();
    loadDocs();
    loadChangeLog();
    loadCallLog();
    loadOverview();
    loadHistory();
    loadManifest();
    loadCollect('');
    loadMapping();
  }

  function bindPipeline(){
    DZ.on('#pl_query', 'click', function(){ doQuery(); });
    DZ.on('#pl_trigger_btn', 'click', function(){ doTrigger(); });
    DZ.on('#pl_collect_run', 'click', function(){ doCollectRun(); });
    DZ.on('#pl_map_add', 'click', function(){ addMappingRow(); });
    DZ.on('#pl_map_save', 'click', function(){ saveMapping(); });
    DZ.on('#pl_doc_new_btn', 'click', function(){ plState.docForm = !plState.docForm; renderDocForm(); });
    DZ.on('#pl_doc_apply', 'click', function(){ doDocFilter(); });
  }

  async function doQuery(){
    switchPlTab(plState.tab);
    await loadDocTargets();
    await loadDocs();
    await loadChangeLog();
    await loadCallLog();
    await loadOverview();
    await loadHistory();
    await loadManifest();
    await loadCollect(plState.collectFilter);
    await loadMapping();
    if (plState.docSel) await loadDocDetail(plState.docSel);
    DZ.toast('已重新查询知识发布数据', 'ok');
  }

  /* ==========================================================================
     A. 知识文档（对接知识库平台）
     ========================================================================== */
  async function loadDocTargets(){
    var r = await DZ.get(API.kbTargets);
    if (isErr(r)) return r;
    plState.kbTargets = r;
    renderDocFilters();
    renderDocForm();
    return r;
  }

  function renderDocFilters(){
    var t = plState.kbTargets || {};
    var kbSel = document.getElementById('pl_doc_kb_filter');
    if (kbSel){
      kbSel.innerHTML = '<option value="">全部知识库</option>' +
        ((t.targets || []).map(function(x){
          return '<option value="' + DZ.esc(x.kbId) + '"' +
            (plState.docFilter.kbId === x.kbId ? ' selected' : '') + '>' + DZ.esc(x.name) + '</option>';
        }).join(''));
    }
    var stSel = document.getElementById('pl_doc_status_filter');
    if (stSel){
      stSel.innerHTML = STATUS_OPTS.map(function(o){
        return '<option value="' + DZ.esc(o[0]) + '"' +
          (plState.docFilter.status === o[0] ? ' selected' : '') + '>' + DZ.esc(o[1]) + '</option>';
      }).join('');
    }
  }

  function doDocFilter(){
    var kbSel = document.getElementById('pl_doc_kb_filter');
    var stSel = document.getElementById('pl_doc_status_filter');
    plState.docFilter.kbId = kbSel ? kbSel.value : '';
    plState.docFilter.status = stSel ? stSel.value : '';
    loadDocs();
  }

  function renderDocForm(){
    var box = document.getElementById('pl_doc_form');
    if (!box) return;
    if (!plState.docForm){ box.innerHTML = ''; return; }
    var t = plState.kbTargets || {};
    var targets = t.targets || []; var types = t.docTypes || []; var srcs = t.sourceKind || [];
    box.innerHTML = '<div class="card"><h3>新建知识文档</h3>' +
      '<div class="form-narrow">' +
        '<label for="pl_new_kb">目标知识库（必选）</label>' +
        '<select id="pl_new_kb" title="选择目标知识库">' +
          '<option value="">请选择知识库</option>' +
          targets.map(function(x){ return '<option value="' + DZ.esc(x.kbId) + '">' + DZ.esc(x.name) + '</option>'; }).join('') +
        '</select>' +
        '<label for="pl_new_type">知识类型（必选）</label>' +
        '<select id="pl_new_type" title="选择知识类型">' +
          types.map(function(x){ return '<option value="' + DZ.esc(x) + '">' + DZ.esc(x) + '</option>'; }).join('') +
        '</select>' +
        '<label for="pl_new_title">标题（必填）</label>' +
        '<input id="pl_new_title" maxlength="60" placeholder="例如：数据分类分级实施细则">' +
        '<label for="pl_new_src">来源方式</label>' +
        '<select id="pl_new_src" title="选择来源方式">' +
          srcs.map(function(x){ return '<option value="' + DZ.esc(x.value) + '">' + DZ.esc(x.label) + '</option>'; }).join('') +
        '</select>' +
        '<div class="dz-actions">' +
          '<button id="pl_new_submit" title="提交新建知识文档">提交</button>' +
          '<button class="ghost" id="pl_new_cancel" title="取消新建">取消</button>' +
        '</div>' +
      '</div></div>';
    var sb = document.getElementById('pl_new_submit');
    if (sb) sb.onclick = submitDocCreate;
    var cb = document.getElementById('pl_new_cancel');
    if (cb) cb.onclick = function(){ plState.docForm = false; renderDocForm(); };
  }

  async function submitDocCreate(){
    if (plState.docBusy) return;
    var kbId = ((document.getElementById('pl_new_kb') || {}).value || '').trim();
    var docType = ((document.getElementById('pl_new_type') || {}).value || '').trim();
    var title = ((document.getElementById('pl_new_title') || {}).value || '').trim();
    var source = ((document.getElementById('pl_new_src') || {}).value || 'manual').trim();
    if (!kbId){ DZ.toast('请先选择目标知识库', 'bad'); return; }
    if (!title){ DZ.toast('请填写知识标题', 'bad'); return; }
    var btn = document.getElementById('pl_new_submit');
    plState.docBusy = true;
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    var r = await DZ.post(API.kbDocuments, {kbId: kbId, docType: docType, title: title, source: source});
    plState.docBusy = false;
    if (btn){ btn.disabled = false; btn.textContent = '提交'; }
    if (isErr(r)){ DZ.toast('新建失败：' + errMsg(r), 'bad'); return; }
    DZ.toast('已新建为草稿，提交发布后进入专家审核', 'ok');
    plState.docForm = false;
    renderDocForm();
    await loadDocs();
  }

  async function loadDocs(){
    var box = document.getElementById('pl_docs_list');
    if (!box) return;
    box.innerHTML = DZ.skeleton(5);
    var qs = [];
    if (plState.docFilter.kbId) qs.push('kbId=' + encodeURIComponent(plState.docFilter.kbId));
    if (plState.docFilter.status) qs.push('status=' + encodeURIComponent(plState.docFilter.status));
    var r = await DZ.get(API.kbDocuments + (qs.length ? ('?' + qs.join('&')) : ''));
    if (isErr(r)){
      box.innerHTML = DZ.banner('bad', '知识文档清单获取失败：' + errMsg(r), function(){ loadDocs(); });
      box.onclick = null;
      return;
    }
    plState.docs = r;
    renderDocsKpis(r);
    renderDocsList(r);
  }

  function renderDocsKpis(r){
    var box = document.getElementById('pl_docs_kpis');
    if (!box) return;
    var s = r.summary || {};
    box.innerHTML = '<div class="dz-kpi-row">' +
      DZ.kpi('知识文档', DZ.number(s.total), '合计', '') +
      DZ.kpi('已入库', DZ.number(s.published), '专家审核通过', 'ok') +
      DZ.kpi('待专家审核', DZ.number(s.pendingReview), '待审核', 'warn') +
      DZ.kpi('草稿', DZ.number(s.draft), '未提交发布', '') +
    '</div>';
  }

  function renderDocsList(r){
    var box = document.getElementById('pl_docs_list');
    if (!box) return;
    var docs = r.documents || [];
    if (!docs.length){
      box.innerHTML = DZ.empty('该筛选条件下暂无知识文档，可点击「新建文档」创建');
      box.onclick = null;
      return;
    }
    box.innerHTML = '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th style="min-width:200px">标题</th><th>所属知识库</th><th>知识类型</th><th>来源</th>' +
      '<th>版本</th><th>状态</th><th>创建人</th><th>更新时间</th><th style="width:170px">操作</th>' +
      '</tr></thead><tbody>' + docs.map(function(d){
        var acts = '<button class="ghost" data-act="detail" data-id="' + DZ.esc(d.docId) + '"' +
          ' title="查看文档详情、版本与日志">' + (d.status === 'pending_review' ? '审核' : '详情') + '</button>';
        if (d.status === 'draft'){
          acts += ' <button class="ghost" data-act="publish" data-id="' + DZ.esc(d.docId) + '"' +
            ' title="提交专家审核">提交发布</button>';
        }
        return '<tr>' +
          '<td><b>' + DZ.esc(d.title) + '</b></td>' +
          '<td>' + DZ.esc(d.kbName || '—') + '</td>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(d.docType || '—') + '</span></td>' +
          '<td>' + DZ.esc(d.sourceLabel || '—') + '</td>' +
          '<td>' + DZ.esc(d.version || '—') + '</td>' +
          '<td>' + docBadge(d.status, d.statusLabel) + '</td>' +
          '<td>' + DZ.esc(d.ownerName || d.owner || '—') + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(d.updatedAt)) + '</td>' +
          '<td style="white-space:nowrap">' + acts + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
    box.onclick = function(e){
      var b = e.target.closest('button[data-act]');
      if (!b) return;
      var id = b.getAttribute('data-id');
      if (b.getAttribute('data-act') === 'publish') doDocPublish(id);
      else loadDocDetail(id);
    };
  }

  async function doDocPublish(id){
    if (!id) return;
    var r = await DZ.post(API.kbPublish(id), {});
    if (isErr(r)){ DZ.toast('提交发布失败：' + errMsg(r), 'bad'); return; }
    DZ.toast('已提交，等待专家审核', 'ok');
    await loadDocs();
    if (plState.docSel === id) await loadDocDetail(id);
  }

  async function loadDocDetail(id){
    if (!id) return;
    plState.docSel = id;
    var box = document.getElementById('pl_doc_detail');
    if (!box) return;
    box.innerHTML = '<div class="card">' + DZ.skeleton(4) + '</div>';
    var r = await DZ.get(API.kbDocument(id));
    if (isErr(r)){
      box.innerHTML = DZ.banner('bad', '文档详情获取失败：' + errMsg(r), function(){ loadDocDetail(id); });
      box.onclick = null;
      return;
    }
    plState.docDetail = r;
    renderDocDetail(r);
  }

  function versionsTable(vers){
    if (!vers || !vers.length) return '<div class="muted">暂无版本记录</div>';
    return '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>版本号</th><th>内容摘要</th><th>版本说明</th><th>创建人</th><th>创建时间</th>' +
      '</tr></thead><tbody>' + vers.map(function(v){
        return '<tr>' +
          '<td><b>' + DZ.esc(v.version || '—') + '</b></td>' +
          '<td><code title="内容摘要">' + DZ.esc(shortHash(v.contentHash)) + '</code></td>' +
          '<td>' + DZ.esc(v.note || '—') + '</td>' +
          '<td>' + DZ.esc(v.createdByName || v.createdBy || '—') + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(v.createdAt)) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function changesList(changes){
    if (!changes || !changes.length) return '<div class="muted">暂无变更记录</div>';
    return '<ul class="dz-tl">' + changes.map(function(c){
      return '<li class="dz-tl-item">' +
        '<div class="dz-tl-title">' + DZ.esc(c.changeTypeLabel || '') + ' · ' + DZ.esc(c.summary || '—') + '</div>' +
        '<div class="dz-tl-time">' + DZ.esc(DZ.date(c.createdAt)) + ' · ' + DZ.esc(c.actorName || c.actor || '—') + '</div>' +
      '</li>';
    }).join('') + '</ul>';
  }

  function callsTable(calls){
    if (!calls || !calls.length) return '<div class="muted">暂无调用记录</div>';
    return '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>调用时间</th><th>调用人</th><th>使用场景</th><th>查询内容</th>' +
      '</tr></thead><tbody>' + calls.map(function(c){
        return '<tr>' +
          '<td class="muted">' + DZ.esc(DZ.date(c.createdAt)) + '</td>' +
          '<td>' + DZ.esc(c.callerName || c.caller || '—') + '</td>' +
          '<td>' + DZ.esc(c.scene || '—') + '</td>' +
          '<td>' + DZ.esc(c.query || '—') + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function reviewsList(reviews){
    if (!reviews || !reviews.length) return '<div class="muted">暂无审核记录</div>';
    return '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>审核人</th><th>审核结论</th><th>审核意见</th><th>审核时间</th>' +
      '</tr></thead><tbody>' + reviews.map(function(rv){
        var kind = rv.decision === 'approve' ? 'ok' : (rv.decision === 'reject' ? 'bad' : 'warn');
        return '<tr>' +
          '<td>' + DZ.esc(rv.reviewerName || rv.reviewer || '—') + '</td>' +
          '<td>' + DZ.badge(kind, rv.decisionLabel || '—') + '</td>' +
          '<td>' + DZ.esc(rv.comment || '—') + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(rv.decidedAt || rv.createdAt)) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function renderDocDetail(d){
    var box = document.getElementById('pl_doc_detail');
    if (!box) return;
    var h = '<div class="card"><h3>文档详情 · ' + DZ.esc(d.title) + ' ' + docBadge(d.status, d.statusLabel) + '</h3>' +
      '<div class="dz-kpi-row">' +
        DZ.kpi('所属知识库', d.kbName || '—', '', '') +
        DZ.kpi('知识类型', d.docType || '—', '', '') +
        DZ.kpi('来源方式', d.sourceLabel || '—', '', '') +
        DZ.kpi('当前版本', d.version || '—', '', '') +
        DZ.kpi('创建人', d.ownerName || d.owner || '—', '', '') +
        DZ.kpi('更新时间', DZ.date(d.updatedAt), '', '') +
      '</div>' +
      '<div class="dz-actions"><button class="ghost" id="pl_doc_close" title="收起文档详情">收起</button></div>' +
    '</div>';

    if (d.status === 'pending_review'){
      h += '<div class="card"><h3>专家审核</h3>' +
        '<div class="form-narrow">' +
          '<label for="pl_review_comment">审核意见（退回时必填）</label>' +
          '<input id="pl_review_comment" maxlength="120" placeholder="填写审核意见">' +
          '<div class="dz-actions">' +
            '<button id="pl_review_approve" title="同意入库">同意入库</button>' +
            '<button class="ghost" id="pl_review_reject" title="退回修改">退回</button>' +
          '</div>' +
        '</div></div>';
    }

    h += '<div class="card"><h3>版本管理</h3>' +
      '<div class="dz-toolbar">' +
        '<input id="pl_ver_note" maxlength="120" placeholder="新建版本说明（必填）">' +
        '<button id="pl_ver_add" title="新建一个版本">新建版本</button>' +
      '</div>' +
      versionsTable(d.versions) + '</div>';

    h += '<div class="grid2">' +
      '<div class="card"><h3>变更历史</h3>' + changesList(d.changes) + '</div>' +
      '<div class="card"><h3>调用日志</h3>' + callsTable(d.calls) + '</div>' +
    '</div>';

    h += '<div class="card"><h3>审核记录</h3>' + reviewsList(d.reviews) + '</div>';

    box.innerHTML = h;
    box.onclick = function(e){
      var b = e.target.closest('button');
      if (!b) return;
      if (b.id === 'pl_doc_close'){ plState.docSel = null; plState.docDetail = null; box.innerHTML = ''; return; }
      if (b.id === 'pl_review_approve'){ doReview('approve'); return; }
      if (b.id === 'pl_review_reject'){ doReview('reject'); return; }
      if (b.id === 'pl_ver_add'){ doAddVersion(); return; }
    };
  }

  async function doReview(decision){
    var d = plState.docDetail;
    if (!d) return;
    var comment = ((document.getElementById('pl_review_comment') || {}).value || '').trim();
    if (decision === 'reject' && !comment){ DZ.toast('退回修改须填写审核意见', 'bad'); return; }
    var btn = document.getElementById(decision === 'approve' ? 'pl_review_approve' : 'pl_review_reject');
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    var r = await DZ.post(API.kbReview(d.docId), {decision: decision, comment: comment});
    if (btn){ btn.disabled = false; btn.textContent = decision === 'approve' ? '同意入库' : '退回'; }
    if (isErr(r)){
      if (errCode(r) === 'FORBIDDEN'){ DZ.toast('当前账号不是专家审核岗，无法做出审核结论', 'bad'); }
      else DZ.toast('审核失败：' + errMsg(r), 'bad');
      return;
    }
    DZ.toast(decision === 'approve' ? '已同意入库，纳入知识库管理' : '已退回修改', 'ok');
    await loadDocs();
    await loadDocDetail(d.docId);
  }

  async function doAddVersion(){
    var d = plState.docDetail;
    if (!d) return;
    var note = ((document.getElementById('pl_ver_note') || {}).value || '').trim();
    if (!note){ DZ.toast('版本更新说明必填', 'bad'); return; }
    var btn = document.getElementById('pl_ver_add');
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    var r = await DZ.post(API.kbVersions(d.docId), {note: note});
    if (btn){ btn.disabled = false; btn.textContent = '新建版本'; }
    if (isErr(r)){ DZ.toast('新建版本失败：' + errMsg(r), 'bad'); return; }
    DZ.toast('已新建版本 ' + (r.version || ''), 'ok');
    await loadDocs();
    await loadDocDetail(d.docId);
  }

  /* ==========================================================================
     B. 全局变更清单与调用日志
     ========================================================================== */
  async function loadChangeLog(){
    var box = document.getElementById('pl_changelog');
    if (!box) return;
    box.innerHTML = DZ.skeleton(5);
    var r = await DZ.get(API.kbChangeLog);
    if (isErr(r)){
      box.innerHTML = DZ.banner('bad', '变更清单获取失败：' + errMsg(r), function(){ loadChangeLog(); });
      box.onclick = null;
      return;
    }
    plState.clData = r;
    renderChangeLog(r);
  }

  function renderChangeLog(r){
    var box = document.getElementById('pl_changelog');
    if (!box) return;
    var rows = (r && r.changes) || [];
    var types = (r && r.types) || [];
    var counts = {};
    rows.forEach(function(x){ counts[x.changeType] = (counts[x.changeType] || 0) + 1; });
    var chipsBox = document.getElementById('pl_cl_chips');
    if (chipsBox){
      chipsBox.innerHTML = '<div class="dz-chipbar">' +
        chipBtn('', '全部', rows.length, plState.clFilter === '') +
        types.map(function(t){ return chipBtn(t.value, t.label, counts[t.value] || 0, plState.clFilter === t.value); }).join('') +
      '</div>';
      chipsBox.onclick = function(e){
        var c = e.target.closest('.dz-chip');
        if (c){ plState.clFilter = c.getAttribute('data-st') || ''; renderChangeLog(plState.clData); }
      };
    }
    var list = plState.clFilter ? rows.filter(function(x){ return x.changeType === plState.clFilter; }) : rows;
    if (!list.length){ box.innerHTML = DZ.empty('该类型下暂无变更记录'); return; }
    box.innerHTML = '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>变更时间</th><th style="min-width:200px">文档</th><th>所属知识库</th>' +
      '<th>变更类型</th><th style="min-width:200px">变更摘要</th><th>操作人</th>' +
      '</tr></thead><tbody>' + list.map(function(c){
        return '<tr>' +
          '<td class="muted">' + DZ.esc(DZ.date(c.createdAt)) + '</td>' +
          '<td><b>' + DZ.esc(c.docTitle || '—') + '</b></td>' +
          '<td>' + DZ.esc(c.kbName || '—') + '</td>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(c.changeTypeLabel || '—') + '</span></td>' +
          '<td>' + DZ.esc(c.summary || '—') + '</td>' +
          '<td>' + DZ.esc(c.actorName || c.actor || '—') + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  async function loadCallLog(){
    var box = document.getElementById('pl_calllog');
    if (!box) return;
    box.innerHTML = DZ.skeleton(5);
    var r = await DZ.get(API.kbCallLog);
    if (isErr(r)){
      box.innerHTML = DZ.banner('bad', '调用日志获取失败：' + errMsg(r), function(){ loadCallLog(); });
      box.onclick = null;
      return;
    }
    plState.callData = r;
    renderCallLog(r);
  }

  function renderCallLog(r){
    var box = document.getElementById('pl_calllog');
    if (!box) return;
    var rows = (r && r.calls) || [];
    var kbs = [];
    var seen = {};
    rows.forEach(function(x){
      var k = x.kbName || '—';
      if (!seen[k]){ seen[k] = 0; kbs.push(k); }
      seen[k]++;
    });
    var chipsBox = document.getElementById('pl_call_chips');
    if (chipsBox){
      chipsBox.innerHTML = '<div class="dz-chipbar">' +
        chipBtn('', '全部', rows.length, plState.callFilter === '') +
        kbs.map(function(k){ return chipBtn(k, k, seen[k], plState.callFilter === k); }).join('') +
      '</div>';
      chipsBox.onclick = function(e){
        var c = e.target.closest('.dz-chip');
        if (c){ plState.callFilter = c.getAttribute('data-st') || ''; renderCallLog(plState.callData); }
      };
    }
    var list = plState.callFilter ? rows.filter(function(x){ return (x.kbName || '—') === plState.callFilter; }) : rows;
    if (!list.length){ box.innerHTML = DZ.empty('该知识库下暂无调用记录'); return; }
    box.innerHTML = '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>调用时间</th><th style="min-width:200px">文档</th><th>所属知识库</th>' +
      '<th>调用人</th><th>使用场景</th><th style="min-width:200px">查询内容</th>' +
      '</tr></thead><tbody>' + list.map(function(c){
        return '<tr>' +
          '<td class="muted">' + DZ.esc(DZ.date(c.createdAt)) + '</td>' +
          '<td><b>' + DZ.esc(c.docTitle || '—') + '</b></td>' +
          '<td>' + DZ.esc(c.kbName || '—') + '</td>' +
          '<td>' + DZ.esc(c.callerName || c.caller || '—') + '</td>' +
          '<td>' + DZ.esc(c.scene || '—') + '</td>' +
          '<td>' + DZ.esc(c.query || '—') + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* ==========================================================================
     C. 既有重建发布能力（发布总览 / 版本历史 / 发布文档清单 / 外部采集 / 分类映射）
     ========================================================================== */
  // 变更感知通道
  function renderChannels(){
    var box = document.getElementById('pl_channels');
    if (!box) return;
    box.innerHTML =
      '<ul class="dz-tl">' +
        '<li class="dz-tl-item"><div class="dz-tl-title">① 定时轮询知识源更新标识</div></li>' +
        '<li class="dz-tl-item"><div class="dz-tl-title">② 知识源变更推送</div></li>' +
        '<li class="dz-tl-item"><div class="dz-tl-title">③ 手动触发</div></li>' +
      '</ul>';
  }

  function loadOverview(){
    var box = document.getElementById('pl_overview');
    if (!box) return;
    box.innerHTML = '<div class="card">' + DZ.sectionTitle('当前/最近发布作业') + DZ.skeleton(4) + '</div>';
    DZ.get(API.pubStatus).then(function(data){
      if (isErr(data)){
        box.innerHTML = '<div class="card">' + DZ.sectionTitle('当前/最近发布作业') +
          DZ.banner('bad', '发布状态获取失败：' + errMsg(data), loadOverview) + '</div>';
        var g = document.getElementById('pl_gate'); if (g) g.innerHTML = DZ.empty('暂无质量校验数据');
        return;
      }
      plState.currentVersion = (data && data.currentVersion) || plState.currentVersion || '-';
      renderOverview(data);
    });
  }

  function stepsHtml(run){
    var idx = (typeof run.stageIndex === 'number') ? run.stageIndex : 0;
    var failed = run.status === 'failed';
    return '<ul class="dz-steps">' + STAGES.map(function(s, i){
      var cls = '';
      if (run.status === 'success') cls = 'done';
      else if (failed) cls = (i < idx ? 'done' : (i === idx ? 'bad' : ''));
      else cls = (i < idx ? 'done' : (i === idx ? 'on' : ''));
      return '<li class="dz-step ' + cls + '"><span class="dz-step-no">' + (i + 1) + '</span>' + DZ.esc(s) + '</li>';
    }).join('') + '</ul>';
  }

  function renderOverview(data){
    var run = data && data.run;
    var curEl = document.getElementById('pl_current');
    if (curEl) curEl.innerHTML = '当前版本 <b>' + DZ.esc(plState.currentVersion || '-') + '</b>';
    var box = document.getElementById('pl_overview');
    var gate = document.getElementById('pl_gate');
    if (!box) return;

    if (!run){
      box.innerHTML = '<div class="card">' + DZ.sectionTitle('当前/最近发布作业') +
        DZ.empty('暂无发布作业记录，可手动触发一次重建',
          '<button id="pl_empty_trigger" title="手动触发一次重建">手动触发重建</button>') + '</div>';
      DZ.on('#pl_empty_trigger', 'click', function(){ doTrigger(); });
      if (gate) gate.innerHTML = DZ.empty('暂无质量校验数据');
      return;
    }

    var running = run.status === 'running';
    var success = run.status === 'success';
    var failed = run.status === 'failed' || (!running && !success && !!run.error);
    var pct = running ? Math.min(99, Math.round((Number(run.elapsedMs || 0) / TOTAL_MS) * 100)) : 100;
    var logs = run.logs || [];

    var h = '<div class="card">' + DZ.sectionTitle('当前/最近发布作业');
    h += '<div class="dz-kpi-row">' +
      DZ.kpi('作业状态', statusText(run.status), (TRIGGER_LABEL[run.trigger] || run.trigger || '—'), success ? 'ok' : (failed ? 'bad' : running ? 'warn' : '')) +
      DZ.kpi('重建模式', MODE_LABEL[run.mode] || run.mode || '—', TRIGGER_LABEL[run.trigger] || '—') +
      DZ.kpi('变更文档', (run.changedDocs != null ? run.changedDocs : '—') + ' / ' + (run.totalDocs != null ? run.totalDocs : '—'), '变更 / 总文档') +
      DZ.kpi('耗时', fmtMs(running ? run.elapsedMs : run.durationMs), run.startedAt ? ('开始 ' + DZ.date(run.startedAt)) : '') +
    '</div>';
    h += stepsHtml(run);
    h += '<div class="row"><span class="muted">当前阶段：' + DZ.esc(run.stage || '—') + '</span>' +
      '<span class="dz-mini">' + pct + '%</span></div>';
    h += DZ.bar(pct);
    if (failed && run.error){
      h += DZ.banner('bad', '发布失败：' + run.error, function(){ doTrigger(); });
      h += '<div class="dz-actions"><button id="pl_retry" title="以相同模式重试发布">重试</button></div>';
    }
    if (run.changedDocumentList && run.changedDocumentList.length){
      h += '<h4>变更文档</h4><ul class="dz-tl">' + run.changedDocumentList.map(function(m){
        return '<li class="dz-tl-item"><div class="dz-tl-title">' + DZ.esc(m.title || '—') + '</div></li>';
      }).join('') + '</ul>';
    }
    if (logs.length){
      h += '<h4>执行日志</h4><ul class="dz-tl">' + logs.map(function(l){
        return '<li class="dz-tl-item"><div class="dz-tl-title">' + DZ.esc(l) + '</div></li>';
      }).join('') + '</ul>';
    }
    h += '</div>';
    box.innerHTML = h;

    if (failed){ DZ.on('#pl_retry', 'click', function(){ doTrigger(); }); }
    renderGate(gate, run, failed, success, running);
  }

  // 发布前质量校验（由作业状态与阶段日志派生）
  function renderGate(gate, run, failed, success, running){
    if (!gate) return;
    var logs = (run.logs || []).join(' ');
    var gateTouched = /质量校验/.test(logs) || success;
    var h = '';
    h += row('发布前校验', success ? DZ.badge('ok', '错误 0 · 告警 0')
      : (failed ? DZ.badge('bad', '未通过（阻断发布）') : DZ.badge('warn', running ? '校验中…' : '待执行')));
    h += row('权威正本对账', success ? DZ.badge('ok', '一致')
      : (failed ? DZ.badge('bad', '不一致') : DZ.badge('unk', '待重建完成')));
    h += row('内容哈希校验', gateTouched && success ? DZ.badge('ok', '全部匹配')
      : (failed ? DZ.badge('bad', '存在哈希不一致') : DZ.badge('warn', '进行中')));
    h += row('当前发布版本', DZ.esc(plState.currentVersion || '-'));
    gate.innerHTML = h;
  }

  function doTrigger(){
    var sel = document.getElementById('pl_mode');
    var mode = (sel && sel.value) || 'incremental';
    var btn = document.getElementById('pl_trigger_btn');
    if (btn){ btn.disabled = true; btn.textContent = '处理中…'; }
    DZ.post(API.pubCreate, {trigger:'manual', mode:mode}).then(function(r){
      if (btn){ btn.disabled = false; btn.textContent = '手动触发重建'; }
      if (isErr(r)){ DZ.toast('触发失败：' + errMsg(r), 'bad'); return; }
      DZ.toast('已触发「' + (MODE_LABEL[mode] || mode) + '」重建', 'ok');
      return DZ.delay(300).then(function(){ pollRun(r.runId); });
    });
  }

  function pollRun(runId){
    if (!runId){ return; }
    if (plTimer){ clearInterval(plTimer); plTimer = null; }
    var ticks = 0;
    function tick(){
      ticks++;
      DZ.get(API.pubRun(runId), {delay:false}).then(function(r){
        if (isErr(r)){ DZ.toast('作业查询失败：' + errMsg(r), 'bad'); if (plTimer){ clearInterval(plTimer); plTimer = null; } return; }
        if (r.status === 'success' && r.versionDir) plState.currentVersion = r.versionDir;
        renderOverview({currentVersion: plState.currentVersion, run: r});
        if (r.status && r.status !== 'running'){
          if (plTimer){ clearInterval(plTimer); plTimer = null; }
          DZ.toast(r.status === 'success' ? ('重建完成：' + (r.versionDir || '')) : '重建失败，请查看错误', r.status === 'success' ? 'ok' : 'bad');
          loadHistory(); loadManifest(); loadOverview();
        } else if (ticks >= 12){
          if (plTimer){ clearInterval(plTimer); plTimer = null; }
        }
      });
    }
    tick();
    plTimer = setInterval(tick, 900);
  }

  function loadHistory(){
    var box = document.getElementById('pl_history');
    if (!box) return;
    box.innerHTML = DZ.skeleton(4);
    DZ.get(API.pubHistory).then(function(r){
      if (isErr(r)){ box.innerHTML = DZ.banner('bad', '版本历史获取失败：' + errMsg(r), loadHistory); box.onclick = null; return; }
      var rows = (r && r.history) || [];
      if (!rows.length){ box.innerHTML = DZ.empty('暂无版本历史记录'); box.onclick = null; return; }
      box.innerHTML = '<div class="dz-table-wrap"><table><thead><tr>' +
        '<th>版本目录</th><th>生成时间</th><th>变更摘要</th><th>状态</th><th>操作</th>' +
        '</tr></thead><tbody>' + rows.map(function(v){
          var op = v.current
            ? '<span class="muted">当前版本</span>'
            : '<button class="ghost" data-act="rollback" data-vdir="' + DZ.esc(v.versionDir || '') + '" title="回滚到此版本">回滚到此版本</button>';
          return '<tr>' +
            '<td><b>' + DZ.esc(v.versionDir || '—') + '</b>' + (v.current ? ' ' + DZ.badge('ok', '当前') : '') + '</td>' +
            '<td class="muted">' + DZ.esc(DZ.date(v.finishedAt || v.startedAt)) + '</td>' +
            '<td>' + DZ.esc(v.diffSummary || '—') + '</td>' +
            '<td>' + DZ.statusBadge(v.status) + '</td>' +
            '<td>' + op + '</td>' +
          '</tr>';
        }).join('') + '</tbody></table></div>';
      box.onclick = function(e){
        var b = e.target.closest('button[data-act="rollback"]');
        if (b && b.dataset.vdir){ doRollback(b.dataset.vdir); }
      };
    });
  }

  function doRollback(vdir){
    if (!vdir) return;
    DZ.toast('正在回滚到 ' + vdir + ' …', 'warn');
    DZ.post(API.pubRollback, {versionDir: vdir}).then(function(r){
      if (isErr(r)){ DZ.toast('回滚失败：' + errMsg(r), 'bad'); return; }
      plState.currentVersion = (r && r.currentVersion) || vdir;
      DZ.toast('已回滚，当前版本：' + plState.currentVersion, 'ok');
      loadOverview(); loadHistory();
    });
  }

  function loadManifest(){
    var box = document.getElementById('pl_manifest');
    if (!box) return;
    box.innerHTML = DZ.skeleton(5);
    DZ.get(API.pubManifest).then(function(r){
      if (isErr(r)){ box.innerHTML = DZ.banner('bad', '发布文档清单获取失败：' + errMsg(r), loadManifest); box.onclick = null; return; }
      plState.manifestAll = (r && r.manifest) || [];
      renderManifest(box);
      box.onclick = function(e){
        var chip = e.target.closest('.dz-chip');
        if (chip && chip.dataset.st != null){ plState.manFilter = chip.dataset.st; renderManifest(box); }
      };
    });
  }

  function renderManifest(box){
    var all = plState.manifestAll || [];
    var counts = {all: all.length, published: 0, failed: 0};
    all.forEach(function(m){ var s = m.status || ''; if (counts[s] != null) counts[s]++; });
    var f = plState.manFilter;
    var rows = (f === 'all') ? all : all.filter(function(m){ return (m.status || '') === f; });

    var chips = [['all','全部'], ['published','已发布'], ['failed','构建失败']].map(function(kv){
      return chipBtn(kv[0], kv[1], counts[kv[0]] || 0, f === kv[0]);
    }).join('');

    var h = '<div class="dz-chipbar">' + chips + '</div>';
    if (!rows.length){
      box.innerHTML = h + DZ.empty('该状态下暂无文档，可切换过滤条件');
      return;
    }
    h += '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th style="min-width:260px">标题</th><th>内容摘要</th><th>状态</th><th>构建时间</th>' +
      '</tr></thead><tbody>' + rows.map(function(m){
        return '<tr>' +
          '<td><b>' + DZ.esc(m.title || '—') + '</b></td>' +
          '<td><code title="内容摘要">' + DZ.esc(shortHash(m.contentHash)) + '</code></td>' +
          '<td>' + manBadge(m.status) + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(m.builtAt)) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
    box.innerHTML = h;
  }

  function loadCollect(st){
    var box = document.getElementById('pl_collect');
    if (!box) return;
    st = (st == null) ? (plState.collectFilter || '') : st;
    plState.collectFilter = st;
    box.innerHTML = DZ.skeleton(4);

    var url = API.collectTasks + (st ? ('?status=' + encodeURIComponent(st)) : '');
    DZ.get(url).then(function(r){
      if (isErr(r)){ box.innerHTML = DZ.banner('bad', '采集任务获取失败：' + errMsg(r), function(){ loadCollect(st); }); box.onclick = null; return; }
      var tasks = (r && r.tasks) || [];
      if (st === ''){
        plState.collectAll = tasks.length;
        plState.collectCounts = tasks.reduce(function(a, t){ a[t.status] = (a[t.status] || 0) + 1; return a; }, {});
      }
      renderCollect(box, tasks);
      box.onclick = function(e){
        var chip = e.target.closest('.dz-chip');
        if (chip && chip.dataset.st != null){ loadCollect(chip.dataset.st); return; }
        var b = e.target.closest('button[data-act]');
        if (b){
          if (b.dataset.act === 'approve') doDecision(b.dataset.cid, 'approve');
          else if (b.dataset.act === 'reject') doDecision(b.dataset.cid, 'reject');
        }
      };
    });
  }

  function renderCollect(box, tasks){
    var f = plState.collectFilter || '';
    var cnt = plState.collectCounts || {};
    var h = '<div class="dz-chipbar">' +
      chipBtn('', '全部', plState.collectAll, f === '') +
      chipBtn('pending', '待审核', cnt.pending != null ? cnt.pending : 0, f === 'pending') +
      chipBtn('approved', '已通过', cnt.approved != null ? cnt.approved : 0, f === 'approved') +
      chipBtn('rejected', '已驳回', cnt.rejected != null ? cnt.rejected : 0, f === 'rejected') +
    '</div>';
    if (!tasks.length){
      box.innerHTML = h + DZ.empty('该状态下暂无采集任务，可点击「立即采集」拉取新任务');
      return;
    }
    h += '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th style="min-width:220px">标题</th><th>来源链接</th><th>内容类型</th><th>可信度</th><th>状态</th><th style="width:150px">操作</th>' +
      '</tr></thead><tbody>' + tasks.map(function(t){
        var acts;
        if (t.status === 'pending'){
          acts = '<button class="ghost" data-act="approve" data-cid="' + DZ.esc(t.collectId) + '" title="通过并生成待审提案">通过</button> ' +
                 '<button class="ghost" data-act="reject" data-cid="' + DZ.esc(t.collectId) + '" title="驳回该采集任务">驳回</button>';
        } else {
          acts = '<span class="muted">已处理</span>';
        }
        return '<tr>' +
          '<td><b>' + DZ.esc(t.title || '—') + '</b></td>' +
          '<td><a href="' + DZ.esc(t.sourceUrl || '#') + '" target="_blank" rel="noopener" title="打开来源链接">' + DZ.esc(shortUrl(t.sourceUrl)) + '</a></td>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(CTYPE_LABEL[t.contentType] || t.contentType || '—') + '</span></td>' +
          '<td>' + DZ.confidence(t.credibility) + '</td>' +
          '<td>' + collectBadge(t.status) + '</td>' +
          '<td style="white-space:nowrap">' + acts + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
    box.innerHTML = h;
  }

  function doCollectRun(){
    var btn = document.getElementById('pl_collect_run');
    if (btn){ btn.disabled = true; btn.textContent = '采集处理中…'; }
    DZ.post(API.collectRun, {}).then(function(r){
      if (btn){ btn.disabled = false; btn.textContent = '立即采集'; }
      if (isErr(r)){ DZ.toast('采集失败：' + errMsg(r), 'bad'); return; }
      DZ.toast('采集完成，新增 ' + ((r.newCollectIds || []).length) + ' 条待审核任务', 'ok');
      return DZ.delay(300).then(function(){ loadCollect(''); });
    });
  }

  function doDecision(cid, decision){
    if (!cid) return;
    DZ.post(API.collectDecision(cid), {decision: decision, comment: decision === 'approve' ? '演示审核通过，生成回流提案' : '演示驳回'}).then(function(r){
      if (isErr(r)){ DZ.toast((decision === 'approve' ? '通过' : '驳回') + '失败：' + errMsg(r), 'bad'); return; }
      if (decision === 'approve'){
        DZ.toast('已通过，已生成待审提案', 'ok');
        var hint = document.getElementById('pl_collect_hint');
        if (hint){
          hint.innerHTML = DZ.banner('', '已通过采集入库并生成待审提案，可在「安全治理」视图查看与审核。') +
            '<div class="dz-actions"><button id="pl_goto_issues" title="前往安全治理视图">前往「安全治理」查看提案</button></div>';
          DZ.on('#pl_goto_issues', 'click', function(){
            if (typeof window.showView === 'function') window.showView('issues');
            DZ.toast('已跳转到安全治理', 'ok');
          });
        }
      } else {
        DZ.toast('已驳回该采集任务', 'ok');
      }
      return DZ.delay(300).then(function(){ loadCollect(plState.collectFilter); });
    });
  }

  // 知识库分类映射（表格编辑）
  function loadMapping(){
    var box = document.getElementById('pl_mapping');
    if (!box) return;
    box.innerHTML = DZ.skeleton(3);
    DZ.get(API.catMapping).then(function(r){
      if (isErr(r)){ box.innerHTML = DZ.banner('bad', '分类映射获取失败：' + errMsg(r), loadMapping); box.onclick = null; return; }
      renderMapping((r && r.mappings) || []);
    });
  }

  function mapRowHtml(p, c){
    return '<tr class="pl-map-row">' +
      '<td><input data-f="prefix" value="' + DZ.esc(p || '') + '" placeholder="如 法规" title="类型前缀" aria-label="类型前缀"></td>' +
      '<td><input data-f="category" value="' + DZ.esc(c || '') + '" placeholder="如 合规法规" title="治理类目" aria-label="治理类目"></td>' +
      '<td><button class="ghost" data-act="del" title="删除该映射">删除</button></td>' +
    '</tr>';
  }

  function renderMapping(rows){
    var box = document.getElementById('pl_mapping');
    if (!box) return;
    var h = '<div class="dz-table-wrap"><table><thead><tr><th>类型前缀</th><th>治理类目</th><th>操作</th></tr></thead><tbody>';
    if (!rows.length){
      h += '<tr><td colspan="3" class="muted">暂无映射，可点击「新增一行」添加。</td></tr>';
    } else {
      h += rows.map(function(m){ return mapRowHtml(m.typePrefix, m.category); }).join('');
    }
    h += '</tbody></table></div>';
    box.innerHTML = h;
    box.onclick = function(e){
      var b = e.target.closest('button[data-act="del"]');
      if (b){ var tr = b.closest('tr'); if (tr) tr.parentNode.removeChild(tr); }
    };
  }

  function addMappingRow(){
    var tb = document.querySelector('#pl_mapping tbody');
    if (!tb) return;
    var placeholder = tb.querySelector('td[colspan]');
    if (placeholder) tb.removeChild(placeholder.parentNode);
    var tr = document.createElement('tr');
    tr.className = 'pl-map-row';
    tr.innerHTML = '<td><input data-f="prefix" placeholder="如 法规" title="类型前缀" aria-label="类型前缀"></td>' +
      '<td><input data-f="category" placeholder="如 合规法规" title="治理类目" aria-label="治理类目"></td>' +
      '<td><button class="ghost" data-act="del" title="删除该映射">删除</button></td>';
    tb.appendChild(tr);
  }

  function saveMapping(){
    var wrap = document.getElementById('pl_mapping');
    var st = document.getElementById('pl_map_status');
    var btn = document.getElementById('pl_map_save');
    if (!wrap) return;
    var items = [];
    Array.prototype.forEach.call(wrap.querySelectorAll('.pl-map-row'), function(rowEl){
      var p = rowEl.querySelector('[data-f="prefix"]');
      var c = rowEl.querySelector('[data-f="category"]');
      var pv = p ? p.value.trim() : '';
      var cv = c ? c.value.trim() : '';
      if (pv || cv) items.push({typePrefix: pv, category: cv});
    });
    if (btn) btn.disabled = true;
    if (st) st.textContent = '保存中…';
    DZ.put(API.catMapping, {items: items}).then(function(r){
      if (btn) btn.disabled = false;
      if (isErr(r)){ if (st) st.textContent = ''; DZ.toast('保存失败：' + errMsg(r), 'bad'); return; }
      if (st) st.textContent = '已保存 ' + (r.saved != null ? r.saved : items.length) + ' 条';
      DZ.toast('分类映射已保存（' + (r.saved != null ? r.saved : items.length) + ' 条）', 'ok');
      return DZ.delay(200).then(function(){ loadMapping(); });
    });
  }

  /* ==========================================================================
     视图注册（demo_common.js 在 showView 时触发）
     ========================================================================== */
  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['pipeline'] = function(){ pipelineInit(); };
})();
