const $ = s => document.querySelector(s);
// 当前系统暂不做权限控制与身份认证，写操作统一以固定操作者标识落审计。
const ACTOR = 'ui-user';
const api = async (p, opt) => {
  const r = await fetch(p, opt);
  return r.json();
};
document.querySelectorAll('#nav a').forEach(a => a.onclick = () => {
  document.querySelectorAll('#nav a').forEach(x => x.classList.remove('active'));
  a.classList.add('active');
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.getElementById(a.dataset.v).classList.remove('hidden');
  if (a.dataset.v === 'kbdash') kbLoadTree();
  if (a.dataset.v === 'kbproc') kbProcReset();
  if (a.dataset.v === 'checkslib') loadChecks();
  if (a.dataset.v === 'selfcheck') scInit();
  if (a.dataset.v === 'ledger') loadLedger();
  if (a.dataset.v === 'assess') loadAssets();
  if (a.dataset.v === 'llmset') loadLlmset();
});

// ---------- 合规自查（InspectionRun/CheckResult）----------
let scCurrent = null;      // 当前检查项详情
let scLastRun = {};         // key=target|check -> {runId, result}
async function scInit() {
  const [assets, checks] = await Promise.all([
    api('/api/entities?type=DataAsset&status=published'),
    api('/api/checks?priority=P0'),
  ]);
  $('#sc_target').innerHTML = assets.entities.map(x=>`<option value="${x.id}">${x.label}</option>`).join('');
  $('#sc_check').innerHTML = checks.checks.map(c=>`<option value="${c.checkCode}">${c.checkCode} ${c.title}</option>`).join('');
  await scLoadCheck();
}
async function scLoadCheck() {
  const code = $('#sc_check').value || '1.1';
  scCurrent = await api('/api/checks/' + code);
  const lvColor = {L1:'#1B4FE4',L2:'#3a6bf0',L3:'#6d90f5',L4:'#e08a00',L5:'#2a9d5c'};
  const el = (scCurrent.elements||[]).map((e,i)=>{
    const lvs = (e.focusLevels||'').split(',').filter(Boolean);
    return `<tr><td>${e.code}</td><td>${e.text}<br><span class="muted">口径：${e.criteria||''}</span></td>
      <td>${lvs.map(l=>`<span style="color:${lvColor[l]}" class="pill">${l}</span>`).join(' ')}</td>
      <td><label><input type="checkbox" id="el_l1_${i}" ${lvs.includes('L4')?'':'checked'}> 制度具备</label>
          <br><select id="el_l4_${i}"><option value="provided">证据已提供</option><option value="missing">证据缺失</option></select></td></tr>`;
  }).join('');
  const ev = (scCurrent.methodSteps||[]).filter(s=>s.stepKind==='evidence')
    .map(s=>`<li>[证据${s.stepNo}] ${s.action} — <span class="muted">${s.focus||''}</span></li>`).join('');
  const mt = (scCurrent.metrics||[]).map((m,i)=>
    `<tr><td>${m.name}</td><td><span class="muted">${m.dataSource||''}</span></td><td>${m.threshold}</td>
      <td><input id="mt_${i}" placeholder="实际值" style="width:90px"></td></tr>`).join('');
  $('#sc_form').innerHTML = `
    <h4>${scCurrent.checkCode} ${scCurrent.title} <span class="pill">${scCurrent.priority}</span></h4>
    <details open><summary>逐要素录入（L1制度 / L4证据）</summary><table>
      <tr><th>要素</th><th>检查内容·口径</th><th>关注层级</th><th>录入</th></tr>${el}</table></details>
    <details><summary>对照证据要求（method.evidence_steps）</summary><ul>${ev||'<li>—</li>'}</ul></details>
    <details><summary>L5 效果·度量实际值（后端阈值判定）</summary><table>
      <tr><th>度量</th><th>数据来源</th><th>阈值</th><th>实际值</th></tr>${mt||'<tr><td colspan=4>本检查无度量</td></tr>'}</table></details>`;
}
async function scSubmit() {
  if (!scCurrent) return alert('先载入检查项');
  const els = scCurrent.elements||[];
  const elements = els.map((e,i)=>({
    code: e.code,
    l1_ok: $(`#el_l1_${i}`).checked,
    l4_evidence: $(`#el_l4_${i}`).value,
    note: e.text,
  }));
  const metrics = (scCurrent.metrics||[]).map((m,i)=>({
    metricId: m.name, threshold: m.threshold,
    actual: $(`#mt_${i}`).value.trim(),
  }));
  const target = $('#sc_target').value;
  const actor = ACTOR;
  const run = await api('/api/inspection/runs', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({inspectedTarget: target, inspector: actor, actor})});
  const res = await api(`/api/inspection/runs/${run.runId}/results`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({checkCode: scCurrent.checkCode, elements, metrics, actor})});
  const key = target + '|' + scCurrent.checkCode;
  const prev = scLastRun[key];
  scLastRun[key] = {runId: run.runId, result: res.result};
  scRenderResult(res, prev, run.runId, key);
}
function scBadge(r){return `<span class="badge b-${r==='pass'?'ok':r==='partial'?'warn':'bad'}">${r}</span>`;}
function scRenderResult(res, prev, runId, key) {
  const w = res.why||{};
  const elRows = (w.elements||[]).map(e=>
    `<tr><td>${e.code}</td><td>${scBadge(e.result)}</td><td>${e.why}</td></tr>`).join('');
  const mtRows = (w.metrics||[]).map(m=>
    `<tr><td>${m.metricId||''}</td><td>${m.threshold||''}</td><td>${m.actual??'—'}</td>
      <td>${scBadge(m.status==='pass'?'pass':m.status==='fail'?'fail':m.status)}</td></tr>`).join('');
  const fp = (scCurrent.findings||[]).map(f=>
    `<li><b>问题</b>${f.problem}<br><span class="muted">根因：${f.rootCause}；整改：${f.remediation}</span></li>`).join('');
  let cmp = '';
  if (prev && prev.result !== res.result)
    cmp = `<p class="muted">重检对比：${prev.result} → <b>${res.result}</b>（run ${prev.runId} → ${runId}）</p>`;
  else if (prev)
    cmp = `<p class="muted">本对象+该检查已跑过 ${prev.result}（run ${prev.runId}）；本次仍 ${res.result}。</p>`;
  $('#sc_result').innerHTML = `
    <p>结论：${scBadge(res.result)}　runId=${runId}　提案=${res.proposalId||'（无）'}</p>${cmp}
    <table><tr><th>要素</th><th>判定</th><th>why</th></tr>${elRows||'<tr><td colspan=3>—</td></tr>'}</table>
    <details open><summary>L5 度量判定（阈值对照）</summary><table>
      <tr><th>度量</th><th>阈值</th><th>实际</th><th>判定</th></tr>${mtRows||'<tr><td colspan=4>—</td></tr>'}</table></details>
    ${(res.result==='fail'||res.result==='partial')?`<details open><summary>常见问题/根因/整改（FindingPattern）</summary><ul>${fp||'<li>—</li>'}</ul></details>`:''}
    <p><button onclick="scProposal('${runId}')">一键发起知识缺口提案</button>
       <button class="ghost" onclick="scSubmit()">对同一对象+检查重检</button></p>`;
}
async function scProposal(runId) {
  const r = await api('/api/proposals', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reason: `检查项 ${scCurrent.checkCode}（${scCurrent.title}）自查存在知识缺口，需专家补全证据要求/判定规则/阈值`,
      targetKind: 'EvidenceRequirement', raisedFrom: runId,
      payload: {checkCode: scCurrent.checkCode, runId}, actor: ACTOR})});
  alert('已发起提案 ' + (r.id||JSON.stringify(r)) + '，请到「待审核队列」查看。');
}

// ---------- 检查台账（多人分工 · 周期复查 · 证据 · 签署）----------
const lgBadge = r => `<span class="badge b-${r==='pass'?'ok':r==='partial'?'warn':r==='fail'?'bad':'unk'}">${r==='pass'?'符合':r==='partial'?'部分':r==='fail'?'不符合':'未填'}</span>`;
async function loadLedger() {
  const d = await api('/api/inspection/ledger');
  $('#lg_plans').innerHTML = '<b>计划：</b>' + (d.plans||[]).map(p =>
    `<span class="pill">${p.name}（${p.cycle}·${p.status}）</span>`).join('') || '（暂无计划）';
  $('#lg_table').innerHTML = '<table><tr><th>运行</th><th>计划</th><th>被查对象</th><th>检查人(多人)</th><th>时间</th><th>结果汇总</th><th>证据</th><th>签署</th><th>下次复查</th></tr>' +
    (d.entries||[]).map(e=>{
      const c = e.results||{};
      const s = e.signoff ? `<span class="badge b-${e.signoff.decision==='approved'?'ok':'warn'}">${e.signoff.decision==='approved'?'已复核':'已退回'}</span> ${e.signoff.signer}(${e.signoff.role})` : '未签署';
      return `<tr>
        <td><code>${e.runId}</code></td><td>${e.planName||''}</td><td>${e.inspectedTarget||''}</td>
        <td>${[(e.inspector||''),...(e.assignees||[])].filter(Boolean).join('、')}</td>
        <td>${(e.ranAt||'').slice(0,16)}</td>
        <td>${lgBadge(e.results.fail?'fail':e.results.partial?'partial':e.results.pass?'pass':'unk')}
            <span class="muted">${c.pass||0}符/${c.partial||0}部/${c.fail||0}不</span></td>
        <td>${e.evidenceCount||0} 份</td><td>${s}</td>
        <td>${e.nextRecheck?`<b>${e.nextRecheck}</b>`:'—'}</td></tr>`;
    }).join('') + '</table>' || '<p class="muted">暂无运行记录。请到「合规自查」提交一次检查。</p>';
}
async function planCreate() {
  const r = await api('/api/inspection/plans', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: $('#lg_name').value, scope: $('#lg_scope').value, cycle: $('#lg_cycle').value,
      owner: $('#lg_owner').value,
      checks: $('#lg_checks').value.split(',').map(s=>s.trim()).filter(Boolean),
      actor: ACTOR})});
  if (r.error) return alert(JSON.stringify(r.error));
  alert('已创建计划 ' + r.planId); loadLedger();
}
async function lgUploadEv() {
  const run = $('#lg_runid').value.trim();
  const f = $('#lg_evfile').files[0];
  if (!run || !f) return alert('填运行ID并选择文件');
  const fd = new FormData();
  fd.append('file', f); fd.append('checkCode', $('#lg_evck').value.trim());
  fd.append('uploadedBy', ACTOR);
  const r = await api(`/api/inspection/runs/${run}/evidence`, {method:'POST', body: fd});
  if (r.error) return alert(JSON.stringify(r.error));
  alert('证据已归档 ' + r.evidenceId + '（' + r.fileName + '）'); loadLedger();
}
async function lgShowEv() {
  const run = $('#lg_runid').value.trim();
  const d = await api(`/api/inspection/runs/${run}/evidence`);
  $('#lg_evout').innerHTML = '<table><tr><th>证据ID</th><th>检查项</th><th>文件</th><th>上传人</th><th>时间</th></tr>' +
    (d.evidence||[]).map(x=>`<tr><td><code>${x.id}</code></td><td>${x.checkCode||''}</td><td>${x.fileName}</td><td>${x.uploadedBy||''}</td><td>${(x.uploadedAt||'').slice(0,16)}</td></tr>`).join('') + '</table>';
}
async function lgSignoff() {
  const run = $('#lg_runid2').value.trim();
  if (!run) return alert('填运行ID');
  const r = await api(`/api/inspection/runs/${run}/signoff`, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({signer: $('#lg_signer').value || ACTOR, role: $('#lg_role').value,
      decision: $('#lg_decision').value, actor: ACTOR})});
  if (r.error) return alert(JSON.stringify(r.error));
  alert('已签署 ' + r.signoffId); loadLedger();
}


async function loadChecks() {
  const doc = $('#ck_doc').value, dom = $('#ck_domain').value, pri = $('#ck_pri').value, kw = $('#ck_kw').value.trim();
  let url = '/api/checks?';
  if (doc) url += '&doc=' + doc;
  if (dom) url += '&domain=' + dom;
  if (pri) url += '&priority=' + pri;
  if (kw) url += '&keyword=' + encodeURIComponent(kw);
  const d = await api(url);
  const docLabel = {jg24:'金规〔2024〕24号', jg93:'金办发〔2025〕93号', pboc3:'人行令〔2025〕第3号', jf8:'金发〔2026〕8号'};
  $('#ck_meta').textContent = `共 ${d.total} 项（筛选 ${d.filtered}）｜按文号 ` +
    JSON.stringify(Object.fromEntries(Object.entries(d.byDoc||{}).map(([k,v])=>[docLabel[k]||k,v]))) +
    '｜领域 ' + JSON.stringify(d.byDomain) + '｜优先级 ' + JSON.stringify(d.byPriority);
  $('#ck_list').innerHTML = '<table><tr><th>编号</th><th>标题</th><th>优先级</th><th>领域</th><th>文号</th></tr>' +
    d.checks.map(c =>
      `<tr style="cursor:pointer" onclick="showCheck('${c.checkCode}')">
        <td><b>${c.checkCode}</b></td><td>${c.title}</td>
        <td><span class="pill">${c.priority}</span></td><td>${c.domainLabel||c.domain}</td>
        <td><span class="muted">${docLabel[c.docKey]||c.docKey||''}</span></td></tr>`).join('') + '</table>';
}
async function showCheck(code) {
  const c = await api('/api/checks/' + code);
  const lvColor = {L1:'#1B4FE4',L2:'#3a6bf0',L3:'#6d90f5',L4:'#e08a00',L5:'#2a9d5c'};
  const el = (c.elements||[]).map(e =>
    `<tr><td>${e.code}</td><td>${e.text}</td>
      <td>${(e.focusLevels||'').split(',').filter(Boolean).map(l=>`<span style="color:${lvColor[l]}" class="pill">${l}</span>`).join(' ')}</td></tr>`).join('');
  const steps = (c.methodSteps||[]).map(s=>`<li><b>[${s.stepKind==='evidence'?'查证据':'查制度'}${s.stepNo}]</b> ${s.action||s.focus} ${s.focus&&s.stepKind==='evidence'?('— '+s.focus):''}</li>`).join('');
  const v = c.verdict||{};
  const vd = k => (JSON.parse(v[k]||'[]')).map(x=>`<li>${x}</li>`).join('');
  const fp = (c.findings||[]).map(f=>`<li><b>问题</b>${f.problem}<br><span class="muted">根因：${f.rootCause}；整改：${f.remediation}</span></li>`).join('');
  const rel = (c.related||[]).map(r=>`<li>${r.ref}（关联）</li>`).join('');
  const sc = (c.suggestedControls||[]).map(s=>{
    const badge = s.status==='provisional'
      ? `<span class="badge b-warn">暂定对应·待CT确认</span>`
      : `<span class="badge b-unk">待对齐（10工程v1.5）</span>`;
    return `<li>[${s.layer}] <b>${s.name}</b> ${badge}<br>
      <span class="muted">${s.type||''}${s.baseControlTitle?'｜暂定对应底座：'+s.baseControlTitle:''}</span></li>`;
  }).join('');
  $('#ck_detail').innerHTML = `
    <h4>${c.checkCode} ${c.title} <span class="pill">${c.priority}</span> ${c.domainLabel||c.domain}</h4>
    <p class="muted">依据 ${c.regulation}（${c.articleNo}）｜挂接法条：${(c.citesClause||[]).join(', ')}</p>
    <details open><summary>条文原文</summary><p>${c.articleText||'（同前条，见法条）'}</p></details>
    <details open><summary>检查清单（要素·关注层级色标）</summary><table>${el}</table></details>
    <details><summary>检查方法（查制度·查证据${c.tip?'；杀手锏：'+c.tip:''}）</summary><ol>${steps}</ol></details>
    <details><summary>三档判定要点</summary>
      <p><b>通过：</b><ul>${vd('verdictPass')}</ul></p>
      <p><b>部分符合：</b><ul>${vd('verdictPartial')}</ul></p>
      <p><b>不符合：</b><ul>${vd('verdictFail')}</ul></p></details>
    <details><summary>常见问题/根因/整改</summary><ul>${fp||'<li>—</li>'}</ul></details>
    <details><summary>关联检查项</summary><ul>${rel||'<li>—</li>'}</ul>
      <p class="muted">${c.relatedRaw||''}</p></details>
    <details open><summary>建议控制措施（占位·待 10 工程 v1.5 CT 编码对齐）</summary>
      <p class="muted">以下为检查侧控制需求占位，<b>非已落实/已对齐权威控制</b>；权威控制词汇唯一事实源=10 工程 v1.5。</p>
      <ul>${sc||'<li>—</li>'}</ul></details>`;
}

// ---------- 知识库能力开放（O6 / M11）：查阅·Wiki / 检索 / 加工 ----------
// 平台原生页面承载知识库平台四类能力，统一走 /api/kb/* 取数适配器（统一信封 + 降级链），
// 页面只展示 source/fetchedAt 做"来源可辨"，不做分支渲染；知识库平台零改造。
const SRC_LABEL = {weknora:'知识库实时', canonical:'正本图', db:'结构化投影', sqlite:'运行台账', none:'来源不可用'};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function srcBar(env, extra){
  const s = (env && env.source) || 'none';
  const ok = s !== 'none';
  const t = ((env && env.fetchedAt) || '').replace('T',' ');
  return `<span class="badge b-${ok?'ok':'bad'}">${SRC_LABEL[s]||s}</span>
    <span class="muted">取数 ${t||'—'}${extra?'｜'+extra:''}</span>`;
}

// Wiki 目录树（按业务分类聚合）
let kbTreeEnv = null;
async function kbLoadTree(force){
  const box = $('#kw_tree');
  if (!box) return;
  if (force) kbTreeEnv = null;
  if (!kbTreeEnv){
    box.innerHTML = '<p class="muted">加载中…</p>';
    kbTreeEnv = await api('/api/kb/wiki/tree?limit=500').catch(()=>null);
    const sb = $('#kw_src'); if (sb) sb.innerHTML = kbTreeEnv ? srcBar(kbTreeEnv) : '';
  }
  kbTreeFilter();
}
function kbTreeFilter(){
  const box = $('#kw_tree');
  if (!box || !kbTreeEnv) return;
  const kw = (($('#kw_filter')||{}).value || '').trim().toLowerCase();
  const tree = (kbTreeEnv.content && kbTreeEnv.content.tree) || [];
  if (!tree.length){ box.innerHTML = '<p class="muted">知识库暂无可用页面（或知识库不可达，已降级）。</p>'; return; }
  const hit = (p, cat) => !kw || (p.name||'').toLowerCase().includes(kw)
    || (p.title||'').toLowerCase().includes(kw) || (cat||'').toLowerCase().includes(kw);
  const html = tree.map(g=>{
    const pages = (g.pages||[]).filter(p => hit(p, g.category));
    if (!pages.length) return '';
    return `<details open><summary>${esc(g.category)} <span class="muted">${g.count}</span></summary>
      <ul class="treelist">${pages.map(p=>
        `<li><a onclick="kbOpenPage('${p.pageId}')">${esc(p.name||p.title)}</a></li>`).join('')}</ul></details>`;
  }).join('');
  box.innerHTML = html || '<p class="muted">无匹配页面。</p>';
}
async function kbOpenPage(pageId){
  const box = $('#kw_page');
  if (!box) return;
  box.innerHTML = '<p class="muted">加载中…</p>';
  const env = await api('/api/kb/wiki/'+encodeURIComponent(pageId)).catch(()=>null);
  if (!env || !env.content){ box.innerHTML = '<p class="muted">页面不可用（或知识库不可达）。</p>'; return; }
  const p = env.content;
  const sb = $('#kw_psrc'); if (sb) sb.innerHTML = srcBar(env, '分块 '+(p.chunkCount||0));
  const paras = String(p.content||'').split(/\n{2,}/).map(x=>x.trim()).filter(Boolean)
    .map(x=>`<p>${esc(x).replace(/\n/g,'<br>')}</p>`).join('');
  box.innerHTML = `<h4>${esc(p.title)}</h4>
    <p class="muted">${esc(p.type||'')}${p.folder?'｜'+esc(p.folder):''}｜更新 ${esc((p.updatedAt||'').replace('T',' '))}</p>
    ${paras||'<p class="muted">页面无正文内容。</p>'}`;
}

// 知识检索（融合检索，来源可辨）
const KBT = {case:'案例', law:'法规', standard:'标准', term:'术语', control:'控制', organization:'组织', solution:'方案', topic:'专题', guide:'指引', check:'检查项'};
async function kbSearch(){
  const q = ($('#kb_q').value||'').trim();
  if (!q){ $('#kb_res').innerHTML = '<p class="muted">请输入关键词</p>'; $('#kb_src').innerHTML = ''; return; }
  const env = await api('/api/kb/search?q='+encodeURIComponent(q)+'&limit=20').catch(()=>null);
  if (!env || !env.content){ $('#kb_src').innerHTML=''; $('#kb_res').innerHTML = '<p class="muted">检索不可用。</p>'; return; }
  const r = env.content;
  $('#kb_src').innerHTML = srcBar(env);
  $('#kb_res').innerHTML = r.total
    ? `<p class="muted">命中 ${r.total} 条（点击查看详情）</p>` + r.results.map(x=>
        `<div class="row kbhit" onclick="showKbDetail('${x.id}')">
          <span class="badge">${KBT[x.type]||x.type}</span>
          <span>${esc(x.label||x.id)}</span><span class="muted">${esc(x.id)}</span></div>`).join('')
    : '<p class="muted">无命中，换个关键词试试。</p>';
}
async function showKbDetail(id) {
  const d = await api('/api/entity/'+id);
  if (!d || d.error || !d.id) { $('#kb_detail').innerHTML = '<p class="muted">详情不可用：'+esc((d&&d.error&&d.error.message)||'')+'</p>'; return; }
  $('#kb_detail').innerHTML = `<div class="card">
    <div class="row"><span class="badge">${KBT[d.type]||d.type}</span>
      <span class="muted">${esc(d.id)}</span>
      <span class="muted" style="margin-left:auto">级别 ${esc(d.level||'-')} · 状态 ${esc(d.status||'-')}</span></div>
    <h3>${esc(d.title||d.label||d.id)}</h3>
    ${d.title_en?`<p class="muted">${esc(d.title_en)}</p>`:''}
    <p>${esc(d.summary||'')}</p>
    ${(d.aliases||[]).length?`<p class="muted">别名：${d.aliases.map(esc).join(' · ')}</p>`:''}
    ${(d.tags||[]).length?`<p class="muted">标签：${d.tags.map(t=>'#'+esc(t)).join(' ')}</p>`:''}
    ${d.official_url?`<p class="muted"><a href="${esc(d.official_url)}" target="_blank">官方来源：${esc(d.official_url)}</a></p>`:''}
    ${(d.relations||[]).length?`<p class="muted">关系：${d.relations.map(r=>esc(r.p)+'→'+esc(r.slug)).join(' · ')}</p>`:''}
  </div>`;
}

// 知识加工（仅 /admin）：投递 → 轮询加工进度；平台不直写知识库库表
let kbProcId = null, kbProcTimer = null;
function kbProcReset(){ /* 进入加工页时无需预载，等待用户投递 */ }
async function kbIngestFile(input){
  const f = input.files && input.files[0];
  if (!f) return;
  const text = await f.text();
  const t = $('#kp_title');
  if (t && !t.value) t.value = f.name.replace(/\.[^.]+$/,'');
  const c = $('#kp_content');
  if (c) c.value = text;
}
async function kbIngestSubmit(){
  const title = ($('#kp_title').value||'').trim();
  const content = ($('#kp_content').value||'').trim();
  const out = $('#kp_out');
  if (!title || !content){ out.innerHTML = '<p class="muted">标题与正文均不能为空。</p>'; return; }
  out.innerHTML = '<p class="muted">投递中…</p>';
  const env = await api('/api/kb/ingest', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title, content, actor:'ui-admin'})}).catch(()=>null);
  if (!env || env.error){
    out.innerHTML = '<p class="muted">投递失败：'+esc((env&&env.error&&env.error.message)||'接口不可达')+'</p>';
    return;
  }
  const c = env.content || {};
  kbProcId = c.knowledgeId || '';
  out.innerHTML = `<p>${srcBar(env)}</p>
    <p>已投递：<b>${esc(c.title||title)}</b>　knowledgeId=<code>${esc(kbProcId||'—')}</code></p>
    <p class="muted">投递后由知识库平台自行解析 / 分块 / 向量化，平台只回显进度（不直写知识库）。</p>`;
  $('#kp_status').innerHTML = kbProcId ? '<p class="muted">读取加工进度…</p>'
    : '<p class="muted">未取得 knowledgeId，进度暂不可查（可在「知识库」刷新查看）。</p>';
  if (kbProcId) kbPollStatus();
}
async function kbPollStatus(){
  if (!kbProcId) return;
  clearTimeout(kbProcTimer);
  const env = await api('/api/kb/ingest/'+encodeURIComponent(kbProcId)).catch(()=>null);
  const box = $('#kp_status');
  if (!env || !env.content){ box.innerHTML = '<p class="muted">进度读取失败（知识库不可达）。</p>'; return; }
  const s = env.content;
  box.innerHTML = `<p>${srcBar(env)}</p>
    <table><tr><th>标题</th><th>解析状态</th><th>启用状态</th><th>分块数</th><th>向量数</th><th>加工</th><th>更新时间</th></tr>
    <tr><td>${esc(s.title||'')}</td><td>${esc(s.parseStatus||'')}</td><td>${esc(s.enableStatus||'')}</td>
      <td>${s.chunkCount||0}</td><td>${s.embeddingCount||0}</td>
      <td>${s.ready?'<span class="badge b-ok">已完成</span>':'<span class="badge b-warn">加工中</span>'}</td>
      <td>${esc((s.updatedAt||'').replace('T',' '))}</td></tr></table>`;
  if (!s.ready) kbProcTimer = setTimeout(kbPollStatus, 3000);   // 未完成则继续轮询
}

async function loadAssets() {
  const a = await api('/api/entities?type=DataAsset&status=published');
  $('#asset_sel').innerHTML = a.entities.map(x=>`<option value="${x.id}">${x.label}</option>`).join('');
}
let lastRuns = {};
async function runAssess() {
  const aid = $('#asset_sel').value;
  const r = await api('/api/assessments', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({assetId: aid, actor: ACTOR})});
  lastRuns[aid] = r.runId;
  renderAssess(r);
}
function badge(res){return `<span class="badge b-${res==='conform'?'ok':res==='partial'?'warn':res==='nonconform'?'bad':'unk'}">${res}</span>`;}
function renderAssess(r) {
  $('#assess_out').innerHTML = `<p>总评：<b>${r.overall}</b>　runId=${r.runId}</p>
    <table><tr><th>义务</th><th>控制</th><th>结果</th><th>说明</th></tr>
    ${r.checkItems.map(i=>`<tr><td>${i.obligationCode}</td><td>${i.controlCode||'—'}</td><td>${badge(i.result)}</td>
      <td>${i.why.detail||''}</td></tr>`).join('')}</table>
    ${r.proposals&&r.proposals.length?`<p class="muted">自动生成缺口提案：${r.proposals.map(p=>p.id).join(', ')}</p>`:''}`;
}
async function compareAssess() {
  const aid = $('#asset_sel').value;
  const a = await api('/api/entities?type=Assessment&status=published').catch(()=>({entities:[]}));
  // 取该资产最近两次评估
  const list = await fetch('/api/export/turtle').then(()=>null).catch(()=>null);
  alert('请在两次运行评估后对比；最近 runId：'+JSON.stringify(lastRuns));
}

// ---------- LLM 配置（v1.12.0：前端可配置，UI 优先、env 兜底，免重启生效）----------
async function loadLlmset() {
  const st = await api('/api/settings/llm').catch(() => null);
  if (!st) { $('#llm_status').innerHTML = '配置读取失败：' + (st ? '' : 'API 不可达'); return; }
  $('#llm_base').value = st.base_url || '';
  $('#llm_model').value = st.model || '';
  const keyInfo = st.api_key_set ? ('已设置（' + st.api_key_masked + '）') : '未设置（自动降级规则抽取）';
  $('#llm_status').innerHTML = '当前 Key：' + keyInfo +
    ' · 生效来源：' + (st.source === 'db' ? '前端配置（UI）' : '环境变量（env）') +
    (st.ui_configured ? ' · 前端已配置' : '');
}

async function llmSave() {
  const body = {};
  const base = $('#llm_base').value.trim();
  const key = $('#llm_key').value.trim();
  const model = $('#llm_model').value.trim();
  if (base || $('#llm_base').value === '') body.base_url = base;
  if (key) body.api_key = key;
  if (model || $('#llm_model').value === '') body.model = model;
  if (!Object.keys(body).length) { $('#llm_status').innerHTML = '没有可保存的改动。'; return; }
  const st = await api('/api/settings/llm', {method: 'PUT',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}).catch(() => null);
  if (!st) { $('#llm_status').innerHTML = '保存失败：API 不可达。'; return; }
  $('#llm_key').value = '';
  $('#llm_status').innerHTML = '✓ 已保存并生效。当前 Key：' +
    (st.api_key_set ? '已设置（' + st.api_key_masked + '）' : '未设置') +
    ' · Model：' + st.model + ' · 来源：' + (st.source === 'db' ? '前端配置（UI）' : '环境变量');
}

async function llmTest() {
  const body = {};
  const base = $('#llm_base').value.trim();
  const key = $('#llm_key').value.trim();
  const model = $('#llm_model').value.trim();
  if (base) body.base_url = base;
  if (key) body.api_key = key;
  if (model) body.model = model;
  $('#llm_status').innerHTML = '测试中…';
  const st = await api('/api/settings/llm/test', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}).catch(() => null);
  $('#llm_status').innerHTML = (st && st.ok ? '✓ ' : '✗ ') + (st ? st.detail : '测试失败：API 不可达');
}

// ---------- 首屏默认视图（知识库目录）----------
if ($('#kw_tree')) kbLoadTree();
