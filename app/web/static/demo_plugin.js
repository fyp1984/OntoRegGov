/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   工具插件（智能体工具插件治理）
   · demo_plugin.js
   视图 id：plugin   容器：#plugin_root
   读：GET /api/plugin-settings · GET /api/plugins/invocations
   写：POST /api/plugin-settings/{id}/toggle（启停）、PUT /api/plugin-settings/{id}/config（配置）、
      POST /api/plugin-settings/install（装载）、POST /api/plugin-settings/{id}/uninstall（卸载）、
      POST /api/plugins/{id}/invoke（试调用）
   仅使用 window.DZ.* 与现有 class；颜色 / 圆角全部走现有 CSS 变量。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = {
    settings: '/api/plugin-settings',
    invocations: '/api/plugins/invocations',
    toggle: function (id) { return '/api/plugin-settings/' + encodeURIComponent(id) + '/toggle'; },
    config: function (id) { return '/api/plugin-settings/' + encodeURIComponent(id) + '/config'; },
    uninstall: function (id) { return '/api/plugin-settings/' + encodeURIComponent(id) + '/uninstall'; },
    install: '/api/plugin-settings/install',
    invoke: function (id) { return '/api/plugins/' + encodeURIComponent(id) + '/invoke'; }
  };

  // 能力英文键 → 中文能力名（与后端标签一致，避免英文上屏）
  var CAP_LABEL = {
    grading: '数据分级', classification: '数据分类', masking: '数据脱敏', scan: '敏感数据识别',
    watermark: '文档水印', ocr: '图像文字识别', dlp: '数据防泄漏'
  };

  // 页签：按功能拆分（插件清单 / 调用记录）
  var TABS = [
    { key: 'plugins', label: '插件清单' },
    { key: 'invocations', label: '调用记录' }
  ];

  var S = {
    plugins: null,        // null = 未加载
    remoteCatalog: [],
    summary: null,
    invocations: null,
    invLimit: 50,
    configOpen: null,
    invokeOpen: null,
    tab: 'plugins'        // 当前页签
  };

  function rootEl() { return document.getElementById('plugin_root'); }
  function esc(s) { return DZ.esc(s); }
  function val(id) { var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function capLabel(c) { return CAP_LABEL[c] || c || '—'; }
  function pluginById(id) { return (S.plugins || []).filter(function (p) { return p.pluginId === id; })[0] || null; }

  function onlineBadge(st) {
    var t = String(st == null ? '' : st);
    if (t === '在线' || t === 'active') return DZ.badge('ok', '在线');
    if (t === '降级' || t === 'degraded') return DZ.badge('warn', '降级');
    if (t === '离线' || t === 'offline') return DZ.badge('bad', '离线');
    return DZ.badge('unk', t || '未知');
  }
  function invStatusBadge(st) {
    var t = String(st || '');
    if (t === 'ok') return DZ.badge('ok', '成功');
    if (t === 'degraded') return DZ.badge('warn', '降级');
    if (t === 'failed' || t === 'error') return DZ.badge('bad', '失败');
    return DZ.badge('unk', '未知');
  }
  function metric(k, vHtml) {
    return '<div class="dz-metric"><span class="dz-metric-k">' + esc(k) + '</span>' +
      '<span class="dz-metric-v">' + vHtml + '</span></div>';
  }

  /* ---------------------------------------------------------- 外壳 */
  function shell() {
    var opts = [20, 50, 100].map(function (n) {
      return '<option value="' + n + '"' + (n === S.invLimit ? ' selected' : '') + '>' + n + '</option>';
    }).join('');
    // 顶部动作/筛选统一走扁平筛选行组件：控件同排一行，控件宽度由组件规范决定
    return DZ.filterBar([
      { label: '调用记录条数', html: '<select id="pl_inv_limit" title="调用记录条数" aria-label="调用记录条数">' + opts + '</select>' }
    ], {
      aria: '插件筛选',
      end: '<button class="ghost" id="pl_refresh" title="重新查询插件与调用记录" aria-label="查询">查询</button>'
    }) +
      '<div id="pl_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="pl_msg"></div>' +
      '<div id="pl_tabs"></div>' +
      '<div id="pl_pane" class="dz-pane"></div>';
  }

  // 页签内容壳：切换页签仅渲染当前内容
  function paneHtml(key) {
    if (key === 'invocations') {
      return '<div class="card"><h3>调用记录</h3><div id="pl_inv_list"></div></div>';
    }
    return '' +
      '<div class="card"><h3>插件清单</h3><div id="pl_list"></div></div>' +
      '<div id="pl_config_area"></div>' +
      '<div id="pl_invoke_area"></div>' +
      '<div class="card"><h3>插件装载</h3><div id="pl_install_area"></div></div>';
  }

  function renderPane() {
    var pane = document.getElementById('pl_pane');
    if (!pane) return;
    var guide = {
      plugins: '<b>插件清单</b>：查看已纳管插件与启停状态，可安装新插件并配置其能力。',
      invocations: '<b>调用记录</b>：查看插件被智能体调用的明细与结果。'
    }[S.tab] || '';
    pane.innerHTML = DZ.guide(guide) + paneHtml(S.tab);
    if (S.tab === 'invocations') {
      renderInvocationList();
    } else {
      renderPluginList();
      renderConfigArea();
      renderInvokeArea();
      renderInstallArea();
    }
  }

  function switchTab(key) {
    if (TABS.filter(function (t) { return t.key === key; }).length) S.tab = key;
    DZ.tabs('#pl_tabs', TABS, S.tab, switchTab);
    renderPane();
    if (S.tab === 'invocations') loadInvocations(false);
    else loadSettings(false);
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var rb = document.getElementById('pl_refresh');
    if (rb) rb.onclick = function () { loadSettings(true); loadInvocations(true); };
    var lim = document.getElementById('pl_inv_limit');
    if (lim) lim.onchange = function () { S.invLimit = Number(this.value) || 50; loadInvocations(true); };
    DZ.tabs('#pl_tabs', TABS, S.tab, switchTab);
    renderPane();
    loadSettings(false);
    loadInvocations(false);
  }

  /* ---------------------------------------------------------- 指标 / 清单 */
  function renderKpis(summary) {
    var s = summary || { total: null, enabled: null, disabled: null };
    DZ.render('#pl_kpis', '<div class="dz-kpi-row is-compact">' +
      DZ.kpi('插件总数', DZ.number(s.total), '已纳管', '') +
      DZ.kpi('已启用', DZ.number(s.enabled), '可被智能体调用', 'ok') +
      DZ.kpi('已停用', DZ.number(s.disabled), '暂不参与调用', 'warn') +
    '</div>');
  }

  function renderPluginList() {
    var box = document.getElementById('pl_list');
    if (!box) return;
    if (S.plugins === null) { box.innerHTML = DZ.skeleton(5); return; }
    if (!S.plugins.length) {
      box.innerHTML = DZ.empty('暂无已纳管插件', '<button class="ghost" id="pl_empty_refresh" title="查询">查询</button>');
      var b = document.getElementById('pl_empty_refresh');
      if (b) b.onclick = function () { loadSettings(true); };
      return;
    }
    box.innerHTML = '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th style="min-width:180px">插件</th><th>能力</th><th>运行状态</th>' +
      '<th>装载方式</th><th style="width:80px">启用</th><th style="min-width:230px">操作</th></tr></thead>' +
      '<tbody>' + S.plugins.map(function (p) {
        var builtin = p.kind === 'builtin';
        return '<tr data-plugin="' + esc(p.pluginId) + '">' +
          '<td><b>' + esc(p.name) + '</b><br><span class="muted">' + esc(p.vendor || '—') + '</span></td>' +
          '<td>' + DZ.pill(p.capabilityLabel || capLabel(p.capability)) + '</td>' +
          '<td>' + onlineBadge(p.status) + '</td>' +
          '<td>' + esc(p.kindLabel || p.kind || '—') + '</td>' +
          '<td><input type="checkbox" data-toggle="' + esc(p.pluginId) + '"' + (p.enabled ? ' checked' : '') +
            ' title="启用 / 停用该插件" aria-label="启用或停用 ' + esc(p.name) + '"></td>' +
          '<td><div class="dz-actions" style="margin:0;justify-content:flex-start">' +
            '<button class="ghost" data-config="' + esc(p.pluginId) + '" title="配置该插件" aria-label="配置 ' + esc(p.name) + '">配置</button>' +
            '<button class="ghost" data-invoke="' + esc(p.pluginId) + '" title="试调用该插件" aria-label="试调用 ' + esc(p.name) + '">试调用</button>' +
            '<button class="ghost" data-uninstall="' + esc(p.pluginId) + '"' + (builtin ? ' disabled' : '') +
              ' title="' + (builtin ? '内置插件不可卸载' : '卸载该插件') + '" aria-label="卸载 ' + esc(p.name) + '">卸载</button>' +
          '</div></td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';

    box.querySelectorAll('[data-toggle]').forEach(function (n) {
      n.onchange = function () { doToggle(n.getAttribute('data-toggle'), n.checked, n); };
    });
    box.querySelectorAll('[data-config]').forEach(function (b) {
      b.onclick = function () {
        S.configOpen = b.getAttribute('data-config');
        S.invokeOpen = null;
        renderConfigArea(); renderInvokeArea();
        var a = document.getElementById('pl_config_area');
        if (a && a.scrollIntoView) { try { a.scrollIntoView({ block: 'nearest' }); } catch (e) {} }
      };
    });
    box.querySelectorAll('[data-invoke]').forEach(function (b) {
      b.onclick = function () {
        S.invokeOpen = b.getAttribute('data-invoke');
        S.configOpen = null;
        renderConfigArea(); renderInvokeArea();
        var a = document.getElementById('pl_invoke_area');
        if (a && a.scrollIntoView) { try { a.scrollIntoView({ block: 'nearest' }); } catch (e) {} }
      };
    });
    box.querySelectorAll('[data-uninstall]').forEach(function (b) {
      b.onclick = function () {
        if (b.disabled) return;
        doUninstall(b.getAttribute('data-uninstall'), b);
      };
    });
  }

  /* ---------------------------------------------------------- 启停 */
  function doToggle(id, checked, node) {
    if (node) node.disabled = true;
    DZ.post(API.toggle(id), { enabled: checked }).then(function (res) {
      if (!res || res.error) {
        if (node) { node.checked = !checked; node.disabled = false; }
        DZ.toast('操作失败：' + ((res && res.error && res.error.message) || '接口不可达'), 'bad');
        return;
      }
      DZ.toast(checked ? '插件已启用' : '插件已停用', 'ok');
      loadSettings(true);
    });
  }

  /* ---------------------------------------------------------- 卸载 */
  function doUninstall(id, btn) {
    var p = pluginById(id);
    if (p && p.kind === 'builtin') { DZ.toast('内置插件不可卸载，可关闭其启用开关', 'warn'); return; }
    var old = btn.textContent;
    btn.disabled = true; btn.textContent = '处理中…';
    DZ.post(API.uninstall(id), {}).then(function (res) {
      if (!res || res.error) {
        btn.disabled = false; btn.textContent = old;
        DZ.toast('卸载失败：' + ((res && res.error && res.error.message) || '接口不可达'), 'bad');
        return;
      }
      DZ.toast('插件已卸载', 'ok');
      if (S.configOpen === id) S.configOpen = null;
      if (S.invokeOpen === id) S.invokeOpen = null;
      loadSettings(true);
      loadInvocations(true);
    });
  }

  /* ---------------------------------------------------------- 逐插件配置（按配置项动态渲染） */
  function renderConfigArea() {
    var area = document.getElementById('pl_config_area');
    if (!area) return;
    if (!S.configOpen) { area.innerHTML = ''; return; }
    var p = pluginById(S.configOpen);
    if (!p) { area.innerHTML = ''; return; }
    var schema = p.configSchema || [];
    var cfg = p.config || {};
    var fields = schema.map(function (f) { return '<div>' + fieldHtml(f, cfg[f.key]) + '</div>'; }).join('');
    area.innerHTML = '<div class="card"><h3>配置插件：' + esc(p.name) + ' ' + onlineBadge(p.status) + '</h3>' +
      (schema.length
        ? '<div class="grid2">' + fields + '</div>'
        : '<div class="muted">该插件暂无可配置项。</div>') +
      '<div id="pl_cfg_msg"></div>' +
      '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
        '<button id="pl_cfg_save" title="保存插件配置" aria-label="保存插件配置">保存配置</button>' +
        '<button class="ghost" id="pl_cfg_close" title="收起配置面板" aria-label="收起">收起</button>' +
      '</div></div>';
    var s = document.getElementById('pl_cfg_save');
    if (s) s.onclick = saveConfig;
    var c = document.getElementById('pl_cfg_close');
    if (c) c.onclick = function () { S.configOpen = null; renderConfigArea(); };
  }

  function fieldHtml(f, v) {
    var key = esc(f.key);
    var label = esc(f.label);
    if (f.type === 'bool') {
      return '<label class="pick" style="margin-top:22px"><input type="checkbox" data-cfg="' + key + '"' +
        (v ? ' checked' : '') + ' aria-label="' + label + '"> <span class="pick-name">' + label + '</span></label>';
    }
    if (f.type === 'select') {
      var opts = (f.options || []).map(function (o) {
        return '<option value="' + esc(o) + '"' + (o === v ? ' selected' : '') + '>' + esc(o) + '</option>';
      }).join('');
      return '<label>' + label + '</label><select data-cfg="' + key + '" aria-label="' + label + '">' + opts + '</select>';
    }
    if (f.type === 'number') {
      var attrs = '';
      if (f.min != null) attrs += ' min="' + esc(f.min) + '"';
      if (f.max != null) attrs += ' max="' + esc(f.max) + '"';
      if (f.step != null) attrs += ' step="' + esc(f.step) + '"';
      return '<label>' + label + '</label><input type="number"' + attrs + ' data-cfg="' + key +
        '" value="' + esc(v == null ? '' : v) + '" aria-label="' + label + '">';
    }
    return '<label>' + label + '</label><input type="text" data-cfg="' + key +
      '" value="' + esc(v == null ? '' : v) + '" aria-label="' + label + '">';
  }

  function saveConfig() {
    var p = pluginById(S.configOpen);
    if (!p) return;
    var cfg = {};
    document.querySelectorAll('#pl_config_area [data-cfg]').forEach(function (n) {
      var k = n.getAttribute('data-cfg');
      if (n.type === 'checkbox') cfg[k] = n.checked;
      else if (n.type === 'number') cfg[k] = n.value === '' ? '' : Number(n.value);
      else cfg[k] = n.value;
    });
    var msg = document.getElementById('pl_cfg_msg');
    var btn = document.getElementById('pl_cfg_save');
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    DZ.put(API.config(p.pluginId), { config: cfg }).then(function (res) {
      if (btn) { btn.disabled = false; btn.textContent = '保存配置'; }
      if (res && res.error) {
        if (msg) msg.innerHTML = DZ.banner('bad', res.error.message || '保存失败', saveConfig);
        return;
      }
      DZ.toast('插件配置已保存', 'ok');
      S.configOpen = null;
      loadSettings(true);
    });
  }

  /* ---------------------------------------------------------- 试调用 */
  function renderInvokeArea() {
    var area = document.getElementById('pl_invoke_area');
    if (!area) return;
    if (!S.invokeOpen) { area.innerHTML = ''; return; }
    var p = pluginById(S.invokeOpen);
    if (!p) { area.innerHTML = ''; return; }
    area.innerHTML = '<div class="card"><h3>试调用：' + esc(p.name) + ' ' + onlineBadge(p.status) + '</h3>' +
      '<div class="grid2">' +
        '<div>' +
          '<label for="pl_iv_task">关联任务（可选）</label>' +
          '<input id="pl_iv_task" placeholder="例如：2026年四季度自查" title="关联任务" aria-label="关联任务">' +
          '<label for="pl_iv_input">调用输入（键值形式）</label>' +
          '<textarea id="pl_iv_input" rows="4" title="调用输入" aria-label="调用输入">' +
            esc('{"文本": "示例数据：客户姓名 张三"}') +
          '</textarea>' +
          '<div class="dz-actions" style="justify-content:flex-start;margin-top:10px">' +
            '<button id="pl_iv_run" title="执行试调用" aria-label="执行试调用">执行试调用</button>' +
            '<button class="ghost" id="pl_iv_close" title="收起试调用面板" aria-label="收起">收起</button>' +
          '</div>' +
        '</div>' +
        '<div id="pl_iv_result"><div class="muted">点击“执行试调用”，将展示调用结论、能力与耗时。</div></div>' +
      '</div></div>';
    var run = document.getElementById('pl_iv_run');
    if (run) run.onclick = function () { doInvoke(p); };
    var c = document.getElementById('pl_iv_close');
    if (c) c.onclick = function () { S.invokeOpen = null; renderInvokeArea(); };
  }

  function doInvoke(p) {
    var btn = document.getElementById('pl_iv_run');
    var box = document.getElementById('pl_iv_result');
    var taskId = val('pl_iv_task') || null;
    var raw = val('pl_iv_input');
    var input;
    try { input = raw ? JSON.parse(raw) : {}; }
    catch (e) {
      if (box) box.innerHTML = DZ.banner('bad', '调用输入不是合法的键值形式');
      return;
    }
    if (btn) { btn.disabled = true; btn.textContent = '处理中…'; }
    if (box) box.innerHTML = '<span class="muted">处理中…</span>';
    DZ.post(API.invoke(p.pluginId), { taskId: taskId, input: input }).then(function (res) {
      if (btn) { btn.disabled = false; btn.textContent = '执行试调用'; }
      if (res && res.error) {
        if (box) box.innerHTML = DZ.banner('bad', res.error.message || '调用失败', function () { doInvoke(p); });
        return;
      }
      renderInvokeResult(res, box);
      loadInvocations(true);
    });
  }

  // 把后端返回的英文键名一律翻译为中文文案后再渲染
  function renderInvokeResult(res, box) {
    if (!box) return;
    var out = res.output || {};
    var degraded = res.status === 'degraded' || out.routedToHuman === true;
    var html = '';
    if (degraded) html += DZ.banner('warn', '该插件当前不可用，本次调用已转为人工复核，主流程不阻断。');
    html += metric('调用结论', degraded ? DZ.badge('warn', '已转人工复核') : DZ.badge('ok', '成功'));
    html += metric('耗时', esc(DZ.number(res.latencyMs)) + ' 毫秒');
    if (out.capability) html += metric('能力', esc(capLabel(out.capability)));
    if (out.result) html += metric('执行结果', out.result === 'ok' ? '成功' : esc(out.result));
    if (out.message) html += metric('说明', esc(out.message));
    html += '<div class="dz-actions" style="justify-content:flex-start;margin-top:12px">' +
      '<button class="ghost" id="pl_goto_inv" title="前往调用记录页签">查看调用记录</button></div>';
    box.innerHTML = html;
    var g = document.getElementById('pl_goto_inv');
    if (g) g.onclick = function () { switchTab('invocations'); };
  }

  /* ---------------------------------------------------------- 装载（用户上传 / 从服务端下载） */
  function capOptions() {
    return Object.keys(CAP_LABEL).map(function (k) {
      return '<option value="' + esc(k) + '">' + esc(CAP_LABEL[k]) + '</option>';
    }).join('');
  }

  function renderInstallArea() {
    var area = document.getElementById('pl_install_area');
    if (!area) return;
    var cat = S.remoteCatalog || [];
    area.innerHTML =
      DZ.sectionTitle('从服务端下载') +
      (cat.length
        ? '<div class="dz-table-wrap"><table><thead><tr><th style="min-width:200px">插件</th><th>能力</th>' +
            '<th>版本</th><th style="min-width:200px">说明</th><th>操作</th></tr></thead><tbody>' +
            cat.map(function (c) {
              return '<tr>' +
                '<td><b>' + esc(c.name) + '</b></td>' +
                '<td>' + DZ.pill(capLabel(c.capability)) + '</td>' +
                '<td>' + esc(c.version || '—') + '</td>' +
                '<td class="muted">' + esc(c.description || '—') + '</td>' +
                '<td><button class="ghost" data-remote="' + esc(c.catalogId) + '" title="下载并装载该插件" ' +
                  'aria-label="下载并装载 ' + esc(c.name) + '">下载并装载</button></td>' +
              '</tr>';
            }).join('') + '</tbody></table></div>'
        : DZ.empty('服务端暂无可下载插件')) +
      DZ.sectionTitle('用户上传') +
      '<div class="form-narrow">' +
        '<label for="pl_up_name">插件名称（必填）</label>' +
        '<input id="pl_up_name" placeholder="例如：自定义脱敏插件" title="插件名称" aria-label="插件名称">' +
        '<label for="pl_up_cap">能力（决定配置项）</label>' +
        '<select id="pl_up_cap" title="插件能力" aria-label="插件能力">' + capOptions() + '</select>' +
        '<label for="pl_up_ver">版本</label>' +
        '<input id="pl_up_ver" placeholder="例如：1.0" title="版本" aria-label="版本">' +
        '<div id="pl_up_msg"></div>' +
        '<div class="dz-actions" style="justify-content:flex-start;margin-top:14px">' +
          '<button id="pl_up_submit" title="上传并装载" aria-label="上传并装载">上传并装载</button>' +
        '</div>' +
      '</div>';

    area.querySelectorAll('[data-remote]').forEach(function (b) {
      b.onclick = function () { installRemote(b.getAttribute('data-remote'), b); };
    });
    var sub = document.getElementById('pl_up_submit');
    if (sub) sub.onclick = installUploaded;
  }

  function installRemote(catalogId, btn) {
    var item = (S.remoteCatalog || []).filter(function (c) { return c.catalogId === catalogId; })[0];
    if (!item) return;
    var old = btn.textContent;
    btn.disabled = true; btn.textContent = '处理中…';
    DZ.post(API.install, { kind: 'remote', capability: item.capability, name: item.name, catalogId: item.catalogId })
      .then(function (res) {
        btn.disabled = false; btn.textContent = old;
        if (!res || res.error) {
          DZ.toast('装载失败：' + ((res && res.error && res.error.message) || '接口不可达'), 'bad');
          return;
        }
        DZ.toast('插件已下载并装载', 'ok');
        loadSettings(true);
      });
  }

  function installUploaded() {
    var msg = document.getElementById('pl_up_msg');
    var btn = document.getElementById('pl_up_submit');
    var name = val('pl_up_name');
    if (!name) { if (msg) msg.innerHTML = DZ.banner('bad', '请填写插件名称'); return; }
    var body = {
      kind: 'uploaded',
      capability: val('pl_up_cap') || 'grading',
      name: name,
      version: val('pl_up_ver')
    };
    btn.disabled = true; btn.textContent = '处理中…';
    DZ.post(API.install, body).then(function (res) {
      btn.disabled = false; btn.textContent = '上传并装载';
      if (!res || res.error) {
        if (msg) msg.innerHTML = DZ.banner('bad', (res && res.error && res.error.message) || '装载失败', installUploaded);
        return;
      }
      DZ.toast('插件已上传并装载', 'ok');
      var ni = document.getElementById('pl_up_name'); if (ni) ni.value = '';
      var nv = document.getElementById('pl_up_ver'); if (nv) nv.value = '';
      if (msg) msg.innerHTML = '';
      loadSettings(true);
    });
  }

  /* ---------------------------------------------------------- 调用记录 */
  function renderInvocationList() {
    var box = document.getElementById('pl_inv_list');
    if (!box) return;
    if (S.invocations === null) { box.innerHTML = DZ.skeleton(4); return; }
    if (!S.invocations.length) { box.innerHTML = DZ.empty('暂无调用记录'); return; }
    box.innerHTML = '<div class="dz-table-wrap"><table>' +
      '<thead><tr><th>时间</th><th>调用方</th><th>插件</th><th>关联任务</th><th>结论</th><th>耗时</th></tr></thead><tbody>' +
      S.invocations.map(function (r) {
        var p = pluginById(r.pluginId);
        return '<tr>' +
          '<td>' + esc(DZ.date(r.createdAt)) + '</td>' +
          '<td>' + esc(r.actor || '—') + '</td>' +
          '<td>' + esc(p ? p.name : (r.pluginId || '—')) + '</td>' +
          '<td>' + esc(r.taskId || '—') + '</td>' +
          '<td>' + invStatusBadge(r.status) + '</td>' +
          '<td>' + esc(DZ.number(r.latencyMs)) + ' 毫秒</td>' +
        '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* ---------------------------------------------------------- 取数 */
  function loadSettings(force) {
    if (S.plugins !== null && !force) {
      renderKpis(S.summary); renderPluginList(); renderConfigArea(); renderInvokeArea(); renderInstallArea();
      return;
    }
    S.plugins = null;
    var box = document.getElementById('pl_list');
    if (box) box.innerHTML = DZ.skeleton(5);
    DZ.get(API.settings).then(function (res) {
      if (res && res.error) {
        var b = document.getElementById('pl_list');
        if (b) b.innerHTML = DZ.banner('bad', res.error.message || '插件加载失败', function () { loadSettings(true); });
        return;
      }
      S.plugins = (res && Array.isArray(res.plugins)) ? res.plugins : [];
      S.remoteCatalog = (res && Array.isArray(res.remoteCatalog)) ? res.remoteCatalog : [];
      S.summary = (res && res.summary) || null;
      if (S.configOpen && !pluginById(S.configOpen)) S.configOpen = null;
      if (S.invokeOpen && !pluginById(S.invokeOpen)) S.invokeOpen = null;
      renderKpis(S.summary);
      renderPluginList();
      renderConfigArea();
      renderInvokeArea();
      renderInstallArea();
    });
  }

  function loadInvocations(force) {
    if (S.invocations !== null && !force) { renderInvocationList(); return; }
    S.invocations = null;
    var box = document.getElementById('pl_inv_list');
    if (box) box.innerHTML = DZ.skeleton(4);
    DZ.get(API.invocations + '?limit=' + encodeURIComponent(S.invLimit)).then(function (res) {
      if (res && res.error) {
        var b = document.getElementById('pl_inv_list');
        if (b) b.innerHTML = DZ.banner('bad', res.error.message || '调用记录加载失败', function () { loadInvocations(true); });
        return;
      }
      S.invocations = (res && Array.isArray(res.invocations)) ? res.invocations : [];
      renderInvocationList();
    });
  }

  /* ---------------------------------------------------------- 视图装载 */
  function init() {
    var r = rootEl();
    if (r) r.innerHTML = DZ.skeleton(6);
    mount();
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['plugin'] = init;
})();
