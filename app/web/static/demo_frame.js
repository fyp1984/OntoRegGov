/* ============================================================
   金融行业数据安全知识库和智能体平台 · 全量功能 Demo
   治理框架（三层治理：管理域 / 技术域 / 平台域 + 六环节闭合链）
   · demo_frame.js
   视图 id：frame   容器：#frame_root
   仅使用 window.DZ.* 与现有 dz- class；颜色 / 圆角全部走现有 CSS 变量。
   数据来源：GET /api/governance/frame（静态只读演示数据）。
   ============================================================ */
(function () {
  'use strict';

  var DZ = window.DZ;
  if (!DZ) return;

  var API = { frame: '/api/governance/frame' };

  // 模块状态（视图可重入）
  var S = { data: null };

  function rootEl() { return document.getElementById('frame_root'); }

  function shell() {
    return '' +
      '<div class="dz-toolbar">' +
        '<button class="ghost" id="frame_refresh" title="重新拉取治理框架数据" aria-label="刷新治理框架">刷新</button>' +
        '<span class="muted">三层治理各管一段：管理域管要求，技术域管控制，平台域管留痕。</span>' +
      '</div>' +
      '<div id="frame_kpis">' + DZ.skeleton(2) + '</div>' +
      '<div id="frame_domains">' + DZ.skeleton(3) + '</div>' +
      '<div class="card"><h3>闭合链：从问题到整改验收</h3><div id="frame_chain">' + DZ.skeleton(1) + '</div></div>';
  }

  function mount() {
    var r = rootEl();
    if (!r) return;
    r.innerHTML = shell();
    var btn = document.getElementById('frame_refresh');
    if (btn) btn.onclick = function () { load(true); };
    load(false);
  }

  function renderKpis(summary) {
    DZ.render('#frame_kpis', '<div class="dz-kpi-row">' +
      DZ.kpi('治理域', DZ.number(summary && summary.domains), '管理 / 技术 / 平台', '') +
      DZ.kpi('闭合环节', DZ.number(summary && summary.chain), '从问题到整改验收', '') +
    '</div>');
  }

  function renderDomains(domains) {
    var box = document.getElementById('frame_domains');
    if (!box) return;
    if (!domains.length) { box.innerHTML = DZ.empty('暂无治理域'); return; }
    box.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px">' +
      domains.map(function (d) {
        var rows = (d.items || []).map(function (it) {
          return '<div class="dz-metric">' +
            '<span class="dz-metric-k">' + DZ.esc(it.code) + '</span>' +
            '<span class="dz-metric-v" style="font-weight:500;text-align:right">' + DZ.esc(it.text) + '</span>' +
          '</div>';
        }).join('');
        return '<div class="card">' +
          '<h3>域 ' + DZ.esc(d.no) + ' · ' + DZ.esc(d.name) + '</h3>' +
          '<div class="dz-cite"><div>' + DZ.esc(d.summary || '—') + '</div></div>' +
          '<div style="margin-top:6px">' + rows + '</div>' +
        '</div>';
      }).join('') + '</div>';
  }

  function renderChain(chain) {
    var box = document.getElementById('frame_chain');
    if (!box) return;
    if (!chain.length) { box.innerHTML = DZ.empty('暂无闭合环节'); return; }
    box.innerHTML = '<div class="dz-flow" role="list" aria-label="闭合链">' +
      chain.map(function (c, i) {
        return (i ? '<span class="dz-arrow" aria-hidden="true">→</span>' : '') +
          '<div class="dz-node on" role="listitem" title="第 ' + DZ.esc(c.no) + ' 环：' + DZ.esc(c.name) + '">' +
            '<div class="dz-node-title">' + DZ.esc(c.name) + '</div>' +
            '<div class="dz-mini">' + DZ.esc(c.desc) + '</div>' +
          '</div>';
      }).join('') + '</div>' +
      '<div class="muted">每一环都要留下上一环的结果，下一环才接得住；最后一环回到下一轮。</div>';
  }

  async function load(force) {
    if (S.data && !force) {
      renderKpis(S.data.summary);
      renderDomains(S.data.domains || []);
      renderChain(S.data.chain || []);
      return;
    }
    S.data = null;
    var box = document.getElementById('frame_domains');
    if (box) box.innerHTML = DZ.skeleton(3);
    var res = await DZ.get(API.frame);
    if (!res || res.error) {
      var msg = (res && res.error && res.error.message) || '治理框架数据加载失败';
      DZ.render('#frame_kpis', DZ.banner('bad', msg, function () { load(true); }));
      DZ.render('#frame_domains', DZ.empty('治理框架数据不可读'));
      DZ.render('#frame_chain', DZ.empty('闭合链数据不可读'));
      return;
    }
    S.data = res;
    renderKpis(res.summary || {});
    renderDomains(Array.isArray(res.domains) ? res.domains : []);
    renderChain(Array.isArray(res.chain) ? res.chain : []);
  }

  window.DEMO_VIEW_INIT = window.DEMO_VIEW_INIT || {};
  window.DEMO_VIEW_INIT['frame'] = mount;
})();
