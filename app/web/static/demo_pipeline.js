/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo：知识发布
   承载视图：
     - pipeline → 容器 #pipeline_root（K5/G1.2/K4/G2.8 知识发布 / 知识治理）
   依赖：demo_common.js 提供的全局 window.DZ（严格只用 DZ.*），样式只用 dz- 前缀。
   契约：/tmp/onto_demo_contract.md §5.2 接口；后端字段以 app/demo/router.py 真实返回为准。
   ============================================================ */
(function(){
  'use strict';

  // 本轮仅使用 demo_common.js 注入的公共层
  var DZ = window.DZ;
  if (!DZ){ return; }

  // ---------- 视图容器与接口路径 ----------
  var ROOT_P = '#pipeline_root';
  var API = {
    pubStatus:     '/api/kb/publish/status',
    pubHistory:    '/api/kb/publish/history',
    pubCreate:     '/api/kb/publish',
    pubRun:        function(id){ return '/api/kb/publish/run/' + encodeURIComponent(id); },
    pubRollback:   '/api/kb/publish/rollback',
    manifest:      '/api/kb/publish/manifest',
    catMapping:    '/api/kb/category-mapping',
    collectTasks:  '/api/kb/collect/tasks',
    collectRun:    '/api/kb/collect/run',
    collectDecision: function(id){ return '/api/kb/collect/' + encodeURIComponent(id) + '/decision'; }
  };

  // 发布四阶段（与后端阶段序列对应，总时长约 6400ms）
  var STAGES = ['变更感知', '增量重建', '质量校验', '整版发布'];
  var TOTAL_MS = 6400;

  var TRIGGER_LABEL = {manual:'手动触发', schedule:'定时轮询', inbound:'变更推送'};
  var MODE_LABEL = {incremental:'增量', full:'全量'};
  var CTYPE_LABEL = {notice:'通知公告', guideline:'指引', standard:'标准', law:'法规', policy:'政策'};

  // ---------- 模块内状态 ----------
  var plState = {
    currentVersion: '',
    manifestAll: [],
    manFilter: 'all',
    collectFilter: '',
    collectCounts: {},
    collectAll: null,
    tab: 'overview'
  };
  var plTimer = null;   // 发布作业轮询计时器

  // 页签定义：把原先纵向堆叠的多个板块按治理动作分组（触发/变更清单/版本/采集/映射），
  // 单页不再拥挤，每个页签只呈现一件事。
  var PL_TABS = [
    { key: 'overview', label: '发布总览' },
    { key: 'manifest', label: '变更清单' },
    { key: 'history',  label: '版本历史' },
    { key: 'collect',  label: '外部采集' },
    { key: 'mapping',  label: '分类映射' }
  ];

  // ---------- 通用小工具 ----------
  function isErr(r){ return !!(r && r.error); }
  function errMsg(r){ return (r && r.error && r.error.message) || '接口返回异常'; }
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
  function row(k, v){
    return '<div class="dz-metric"><span class="dz-metric-k">' + DZ.esc(k) + '</span>' +
      '<span class="dz-metric-v">' + v + '</span></div>';
  }

  /* ==========================================================================
     A. 知识发布视图
     ========================================================================== */
  function pipelineShell(){
    return '' +
      '<div class="dz-toolbar dz-toolbar--single">' +
        '<button id="pl_trigger_btn" title="手动触发一次重建发布" aria-label="手动触发重建">手动触发重建</button>' +
        '<select id="pl_mode" title="选择重建模式" aria-label="重建模式">' +
          '<option value="incremental">增量重建</option>' +
          '<option value="full">全量重建</option>' +
        '</select>' +
        '<button class="ghost" id="pl_refresh" title="刷新知识发布数据" aria-label="刷新">刷新</button>' +
        '<span class="muted dz-toolbar-note" id="pl_current">当前版本 —</span>' +
      '</div>' +
      '<div id="pl_tabs"></div>' +
      // 页签一：发布总览（作业总览 + 质量校验 + 变更感知）
      '<div class="dz-pane" data-pane="overview">' +
        '<div id="pl_overview"></div>' +
        '<div class="grid2">' +
          '<div class="card"><h3>发布前质量校验</h3><div id="pl_gate"></div></div>' +
          '<div class="card"><h3>变更感知（三种触发）</h3><div id="pl_channels"></div></div>' +
        '</div>' +
      '</div>' +
      // 页签二：变更清单
      '<div class="dz-pane" data-pane="manifest" hidden>' +
        '<div class="card"><h3>文档变更清单</h3><div id="pl_manifest"></div></div>' +
      '</div>' +
      // 页签三：版本历史与回滚
      '<div class="dz-pane" data-pane="history" hidden>' +
        '<div class="card"><h3>版本历史与回滚</h3><div id="pl_history"></div></div>' +
      '</div>' +
      // 页签四：外部采集与入库审核
      '<div class="dz-pane" data-pane="collect" hidden>' +
        '<div class="card"><h3>外部采集与入库审核</h3>' +
          '<div class="dz-toolbar">' +
            '<button id="pl_collect_run" title="立即执行一次外部采集" aria-label="立即采集">立即采集</button>' +
            '<span class="muted">来源链接 / 发布机构 / 内容类型 / 可信度 / 状态</span>' +
          '</div>' +
          '<div id="pl_collect_hint"></div>' +
          '<div id="pl_collect"></div>' +
        '</div>' +
      '</div>' +
      // 页签五：知识库分类映射
      '<div class="dz-pane" data-pane="mapping" hidden>' +
        '<div class="card"><h3>知识库分类映射</h3>' +
          '<p class="muted">知识库类型前缀映射到治理类目；保存后写入演示库。</p>' +
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
    DZ.tabs('#pl_tabs', PL_TABS.map(function(t){ return { key: t.key, label: t.label }; }), plState.tab, function(key){
      switchPlTab(key);
    });
  }

  function switchPlTab(key){
    plState.tab = key;
    var root = document.querySelector(ROOT_P);
    if (!root) return;
    var panes = root.querySelectorAll('.dz-pane');
    Array.prototype.forEach.call(panes, function(p){ p.hidden = (p.getAttribute('data-pane') !== key); });
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
    loadOverview();
    loadHistory();
    loadManifest();
    loadCollect('');
    loadMapping();
  }

  function bindPipeline(){
    DZ.on('#pl_trigger_btn', 'click', function(){ doTrigger(); });
    DZ.on('#pl_refresh', 'click', function(){
      loadOverview(); loadHistory(); loadManifest(); loadCollect(plState.collectFilter); loadMapping();
      DZ.toast('已刷新知识发布数据', 'ok');
    });
    DZ.on('#pl_collect_run', 'click', function(){ doCollectRun(); });
    DZ.on('#pl_map_add', 'click', function(){ addMappingRow(); });
    DZ.on('#pl_map_save', 'click', function(){ saveMapping(); });
  }

  // ---------- 变更感知三种触发（静态说明 + 红线） ----------
  function renderChannels(){
    var box = document.getElementById('pl_channels');
    if (!box) return;
    box.innerHTML =
      '<ul class="dz-tl">' +
        '<li class="dz-tl-item"><div class="dz-tl-title">① 定时轮询知识源更新标识</div>' +
          '<div class="dz-tl-time">定时扫描知识源的更新标识，命中变更即加入待重建集合</div></li>' +
        '<li class="dz-tl-item"><div class="dz-tl-title">② 知识源变更推送</div>' +
          '<div class="dz-tl-time">知识源变更推送到达后即时标记待重建</div></li>' +
        '<li class="dz-tl-item"><div class="dz-tl-title">③ 手动触发</div>' +
          '<div class="dz-tl-time">运维人员在设置页手动触发一次重建</div></li>' +
      '</ul>';
  }

  // ---------- 作业总览 ----------
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
      DZ.kpi('重建模式', MODE_LABEL[run.mode] || run.mode || '—', '作业编号 ' + (run.runId || '—')) +
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
        return '<li class="dz-tl-item"><div class="dz-tl-title">' + DZ.esc(m.title || m.docKey) + '</div>' +
          '<div class="dz-tl-time">' + DZ.esc(m.docKey || '') + '</div></li>';
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

  // ---------- 质量校验（由作业状态与阶段日志派生） ----------
  function renderGate(gate, run, failed, success, running){
    if (!gate) return;
    var logs = (run.logs || []).join(' ');
    var gateTouched = /质量校验/.test(logs) || success;
    var h = '';
    h += row('发布前严格校验', success ? DZ.badge('ok', '错误 0 · 告警 0')
      : (failed ? DZ.badge('bad', '未通过（阻断发布）') : DZ.badge('warn', running ? '校验中…' : '待执行')));
    h += row('权威正本对账', success ? DZ.badge('ok', '一致')
      : (failed ? DZ.badge('bad', '不一致') : DZ.badge('unk', '待重建完成')));
    h += row('内容哈希校验', gateTouched && success ? DZ.badge('ok', '全部匹配')
      : (failed ? DZ.badge('bad', '存在哈希不一致') : DZ.badge('warn', '进行中')));
    h += row('当前发布版本', DZ.esc(plState.currentVersion || '-'));
    gate.innerHTML = h;
  }

  // ---------- 手动触发重建（含增量/全量选择） ----------
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

  // ---------- 轮询作业详情直到完成 ----------
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

  // ---------- 版本历史与回滚 ----------
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

  // ---------- 文档变更清单 ----------
  function loadManifest(){
    var box = document.getElementById('pl_manifest');
    if (!box) return;
    box.innerHTML = DZ.skeleton(5);
    DZ.get(API.manifest).then(function(r){
      if (isErr(r)){ box.innerHTML = DZ.banner('bad', '变更清单获取失败：' + errMsg(r), loadManifest); box.onclick = null; return; }
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
      var k = kv[0];
      return '<button class="dz-chip' + (f === k ? ' on' : '') + '" data-st="' + k + '" title="按状态过滤变更清单">' +
        kv[1] + ' ' + (counts[k] || 0) + '</button>';
    }).join('');

    var h = '<div class="dz-chipbar">' + chips + '</div>';
    if (!rows.length){
      box.innerHTML = h + DZ.empty('该状态下暂无变更文档，可切换过滤条件');
      return;
    }
    h += '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>文档编号</th><th>文档标识</th><th>标题</th><th>内容哈希</th><th>状态</th><th>构建时间</th>' +
      '</tr></thead><tbody>' + rows.map(function(m){
        return '<tr>' +
          '<td class="muted">' + DZ.esc(m.docId || '—') + '</td>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(m.docKey || '—') + '</span></td>' +
          '<td>' + DZ.esc(m.title || '—') + '</td>' +
          '<td><code title="' + DZ.esc(m.contentHash || '') + '">' + DZ.esc(shortHash(m.contentHash)) + '</code></td>' +
          '<td>' + manBadge(m.status) + '</td>' +
          '<td class="muted">' + DZ.esc(DZ.date(m.builtAt)) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
    box.innerHTML = h;
  }

  // ---------- 外部采集与入库审核 ----------
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
    function chip(k, label, n){
      return '<button class="dz-chip' + (f === k ? ' on' : '') + '" data-st="' + k + '" title="按状态过滤采集任务">' +
        label + (n != null ? ' ' + n : '') + '</button>';
    }
    var h = '<div class="dz-chipbar">' +
      chip('', '全部', plState.collectAll) +
      chip('pending', '待审核', cnt.pending != null ? cnt.pending : null) +
      chip('approved', '已通过', cnt.approved != null ? cnt.approved : null) +
      chip('rejected', '已驳回', cnt.rejected != null ? cnt.rejected : null) +
    '</div>';
    if (!tasks.length){
      box.innerHTML = h + DZ.empty('该状态下暂无采集任务，可点击「立即采集」拉取新任务');
      return;
    }
    h += '<div class="dz-table-wrap"><table><thead><tr>' +
      '<th>标题</th><th>来源链接</th><th>发布机构</th><th>内容类型</th><th>可信度</th><th>状态</th><th>操作</th>' +
      '</tr></thead><tbody>' + tasks.map(function(t){
        var acts;
        if (t.status === 'pending'){
          acts = '<button class="ghost" data-act="approve" data-cid="' + DZ.esc(t.collectId) + '" title="通过并生成待审提案">通过</button> ' +
                 '<button class="ghost" data-act="reject" data-cid="' + DZ.esc(t.collectId) + '" title="驳回该采集任务">驳回</button>';
        } else if (t.proposalId){
          acts = '<span class="muted" title="关联提案">提案 ' + DZ.esc(t.proposalId) + '</span>';
        } else {
          acts = '<span class="muted">已处理</span>';
        }
        return '<tr>' +
          '<td>' + DZ.esc(t.title || '—') + '</td>' +
          '<td><a href="' + DZ.esc(t.sourceUrl || '#') + '" target="_blank" rel="noopener" title="打开来源链接">' + DZ.esc(shortUrl(t.sourceUrl)) + '</a></td>' +
          '<td>' + DZ.esc(t.issuingBody || '—') + '</td>' +
          '<td><span class="dz-tag-soft">' + DZ.esc(CTYPE_LABEL[t.contentType] || t.contentType || '—') + '</span></td>' +
          '<td>' + DZ.confidence(t.credibility) + '</td>' +
          '<td>' + collectBadge(t.status) + '</td>' +
          '<td>' + acts + '</td>' +
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
        DZ.toast('已通过，已生成待审提案 ' + (r.proposalId || ''), 'ok');
        var hint = document.getElementById('pl_collect_hint');
        if (hint){
          hint.innerHTML = DZ.banner('', '已通过采集入库并生成待审提案 ' + (r.proposalId || '') + '，可在「整改与复检」视图查看与审核。') +
            '<div class="dz-actions"><button id="pl_goto_rem" title="前往整改与复检视图">前往「整改与复检」查看提案</button></div>';
          DZ.on('#pl_goto_rem', 'click', function(){
            if (typeof window.showView === 'function') window.showView('rem');
            DZ.toast('已跳转到整改与复检', 'ok');
          });
        }
      } else {
        DZ.toast('已驳回该采集任务', 'ok');
      }
      return DZ.delay(300).then(function(){ loadCollect(plState.collectFilter); });
    });
  }

  // ---------- 知识库分类映射（表格编辑） ----------
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
      '<td><input data-f="prefix" value="' + DZ.esc(p || '') + '" placeholder="如 jg24" title="类型前缀" aria-label="类型前缀"></td>' +
      '<td><input data-f="category" value="' + DZ.esc(c || '') + '" placeholder="如 监管规则" title="治理类目" aria-label="治理类目"></td>' +
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
    tr.innerHTML = '<td><input data-f="prefix" placeholder="如 jg24" title="类型前缀" aria-label="类型前缀"></td>' +
      '<td><input data-f="category" placeholder="如 监管规则" title="治理类目" aria-label="治理类目"></td>' +
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
