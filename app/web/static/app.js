const $ = s => document.querySelector(s);
// 当前系统暂不做权限控制与身份认证，写操作统一以固定操作者标识落审计。
const ACTOR = 'ui-user';
const api = async (p, opt) => {
  const r = await fetch(p, opt);
  return r.json();
};
// 视图切换（左侧菜单 + 左下角设置齿轮共用）
function showView(id){
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  const el = document.getElementById(id);
  if (el) el.classList.remove('hidden');
  document.querySelectorAll('#nav a').forEach(x => x.classList.toggle('active', x.dataset.v === id));
  const gear = $('#settings_gear');
  if (gear) gear.classList.toggle('active', id === 'settings');
  if (id === 'kbdash') kbSiteShow();
  if (id === 'checkslib') loadChecks();
  if (id === 'selfcheck') scInit();
  if (id === 'settings') loadSettings();
}
document.querySelectorAll('#nav a').forEach(a => a.onclick = () => showView(a.dataset.v));

// 左下角齿轮：开关设置视图
function openSettings(){
  const cur = document.getElementById('settings');
  showView(cur && cur.classList.contains('hidden') ? 'settings' : 'kbdash');
}

// ---------- 左侧菜单折叠（收缩 / 打开）----------
function navToggle(){
  document.querySelector('.wrap').classList.toggle('nav-collapsed');
}

// ---------- 合规自查（InspectionRun/CheckResult）----------
let scCurrent = null;      // 当前检查项详情
let scLastRun = {};         // key=target|check -> {runId, result}
let scLastRunId = null;     // 最近一次提交生成的运行ID（供生成自查报告）
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
  scLastRunId = runId;
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
       <button class="ghost" onclick="scSubmit()">对同一对象+检查重检</button>
       <button class="ghost" onclick="scReport()">生成合规自查报告</button></p>`;
}

// 合规自查报告（PRD M4.5/O5）：差距 + 整改建议 + 专家意见；确定性派生，同输入同输出
const SC_V = {pass:'符合', partial:'部分符合', fail:'不符合'};
async function scReport(){
  if (!scLastRunId) return alert('请先提交一次自查，再生成报告');
  const rep = await api('/api/inspection/runs/' + scLastRunId + '/report').catch(()=>null);
  if (!rep || rep.error){ $('#sc_report_out').innerHTML = '<p class="muted">报告生成失败：' + esc((rep&&rep.error&&rep.error.message)||'接口不可达') + '</p>'; return; }
  const s = rep.summary || {};
  const vb = r => `<span class="badge b-${r==='pass'?'ok':r==='partial'?'warn':'bad'}">${SC_V[r]||r}</span>`;
  const items = (rep.items||[]).map(i => `
    <details${i.result!=='pass'?' open':''}><summary>${esc(i.checkCode)} ${esc(i.title)} ${vb(i.result)}${i.priority?` <span class="pill">${esc(i.priority)}</span>`:''}</summary>
      <p class="muted">依据：${esc(((i.regulation||'')+' '+(i.articleNo||'')).trim()||'—')}
        ｜佐证：已提供 ${i.evidence.provided} / 缺失 ${i.evidence.missing} / 无制度 ${i.evidence.absent}
        ｜佐证${i.evidenceComplete?'完整':'不完整'} / 内容${i.contentAdequate?'完备':'不完备'} / ${i.compliant?'符合监管要求':'未达监管要求'}</p>
      ${(i.gaps||[]).length?`<p><b>差距</b></p><ul>${i.gaps.map(g=>`<li>[${esc(g.type)}] ${esc(g.code||'—')}：${esc(g.detail)}</li>`).join('')}</ul>`:''}
      ${(i.remediation||[]).length?`<p><b>整改建议</b></p><ul>${i.remediation.map(r=>`<li>${esc(r.action)}<span class="muted">（依据：${esc(r.basis)}）</span></li>`).join('')}</ul>`:''}
      <p><b>专家意见</b>：${esc(i.expertOpinion)}</p>
    </details>`).join('');
  const gaps = rep.gapSummary||[], experts = rep.expertOpinions||[];
  $('#sc_report_out').innerHTML = `
    <p>被查对象：<b>${esc(rep.inspectedTarget||'—')}</b>　检查人：${esc(rep.inspector||'—')}
      　运行：<code>${esc(rep.runId)}</code>　生成：${esc((rep.generatedAt||'').replace('T',' '))}　总体：${vb(s.overall)}</p>
    <div>
      <span class="stat"><b>${s.complianceRate||0}%</b>合规率</span>
      <span class="stat"><b>${s.evidenceCompleteness||0}%</b>佐证完整性</span>
      <span class="stat"><b>${s.contentAdequacy||0}%</b>内容完备性</span>
      <span class="stat"><b>${s.pass||0}/${s.partial||0}/${s.fail||0}</b>符合/部分/不符合</span>
    </div>
    <h4>一、逐条自查结论与差距</h4>${items||'<p class="muted">无</p>'}
    <h4>二、差距汇总</h4>${gaps.length?`<ul>${gaps.map(g=>`<li>${esc(g.checkCode)} [${esc(g.type)}] ${esc(g.code||'—')}：${esc(g.detail)}</li>`).join('')}</ul>`:'<p class="muted">无</p>'}
    <h4>三、专家意见汇总</h4>${experts.length?`<ul>${experts.map(e=>`<li>[${esc(e.priority||'—')}] ${esc(e.checkCode)}：${esc(e.opinion)}</li>`).join('')}</ul>`:'<p class="muted">无</p>'}`;
  const dl = $('#sc_report_dl');
  if (dl){ dl.href = '/api/inspection/runs/' + scLastRunId + '/report.md'; dl.style.display = 'inline'; }
}
async function scProposal(runId) {
  const r = await api('/api/proposals', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reason: `检查项 ${scCurrent.checkCode}（${scCurrent.title}）自查存在知识缺口，需专家补全证据要求/判定规则/阈值`,
      targetKind: 'EvidenceRequirement', raisedFrom: runId,
      payload: {checkCode: scCurrent.checkCode, runId}, actor: ACTOR})});
  alert('已发起提案 ' + (r.id||JSON.stringify(r)) + '，请到「待审核队列」查看。');
}

// 检查台账（M5）本版本暂不提供：按需求先移除菜单与页面，后续再行补充。

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

// ---------- 知识库（菜单 1 站点内联）----------
// 页面样式/呈现逻辑以历史知识站点为准（kb_site.css + kb_site.js），内容数据由
// /api/kb/knowledge/* 按主题分接口动态提供：首屏只拉轻量索引
// （/api/kb/knowledge/index，无正文/无边）注入 window.KNOWLEDGE_BASE；知识图谱、
// 条目详情、检索由 kb_site.js 按需调用 graph/entity/search 子接口。
// 首次加载即触发（#kbdash 为默认视图）。
let kbSiteInited = false, kbSiteLoading = null;
async function kbSiteShow(){
  if (kbSiteInited) return;
  if (kbSiteLoading) return kbSiteLoading;
  const meta = $('#kb_meta');
  if (meta) meta.innerHTML = '<span class="muted">知识库加载中…</span>';
  kbSiteLoading = (async () => {
    const env = await api('/api/kb/knowledge/index').catch(() => null);
    kbSiteLoading = null;
    const c = env && env.content;
    if (!c || !c.entities){
      if (meta) meta.innerHTML = '<span class="badge b-bad">来源不可用</span> ' +
        '<span class="muted">知识库暂不可达，请稍后重试。</span>';
      return;
    }
    window.KNOWLEDGE_BASE = c;
    if (meta) meta.innerHTML = srcBar(env, '条目 ' + (c.entities||[]).length);
    const ver = $('#kb_ver'); if (ver) ver.textContent = c.version || '—';
    const ga = $('#kb_genat');
    if (ga) ga.textContent = String(c.generated_at||'').replace('T',' ') || '—';
    if (window.KbSite && typeof window.KbSite.init === 'function'){
      window.KbSite.init();
      kbSiteInited = true;
    }
  })();
  return kbSiteLoading;
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

// ---------- 设置页：可引用的知识库（多选） + 取数来源状态 ----------
function loadSettings(){ loadKbPick(); loadLlmset(); loadSrcStatus(); }

async function loadKbPick(){
  const box = $('#kb_pick'); if (!box) return;
  box.innerHTML = '<span class="muted">加载中…</span>';
  const d = await api('/api/settings/kb').catch(() => null);
  if (!d || d.available === undefined){
    box.innerHTML = '<span class="muted">知识库列表不可达，请检查知识库平台。</span>'; return;
  }
  if (!d.available.length){
    box.innerHTML = '<span class="muted">暂无可用知识库。</span>'; return;
  }
  const sel = d.selected || [];
  box.innerHTML = d.available.map(k => `
    <label class="pick" title="${esc(k.id)}">
      <input type="checkbox" value="${esc(k.id)}" ${sel.includes(k.id) ? 'checked' : ''}>
      <span class="pick-name">${esc(k.name)}</span>
      <span class="pick-meta">${k.docCount} 篇</span>
    </label>`).join('');
  kbPickStatus(sel.length);
}

function kbPickStatus(n){
  const el = $('#kb_pick_status'); if (!el) return;
  el.textContent = n ? `已选 ${n} 个知识库` : '未选择，使用默认知识库';
}

async function kbPickSave(){
  const ids = Array.from(document.querySelectorAll('#kb_pick input:checked')).map(x => x.value);
  const el = $('#kb_pick_status'); if (el) el.textContent = '保存中…';
  const r = await api('/api/settings/kb', {method: 'PUT',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids})}).catch(() => null);
  if (!r || r.error){ if (el) el.textContent = '保存失败：接口不可达。'; return; }
  kbSiteInited = false;                       // 使知识库视图下次进入时按新配置重建
  kbPickStatus((r.selected || []).length);
  if (el) el.textContent = '✓ 已保存，' + el.textContent;
}

async function kbPickReset(){
  document.querySelectorAll('#kb_pick input').forEach(x => x.checked = false);
  await kbPickSave();
}

// 主动刷新：失效后端取数缓存 → 立即重取知识库首屏索引并回显条目数/取数时间。
// 对应「知识库内容更新后，前端如何拿到最新」的机制（30s TTL 之外的手动即时刷新）。
async function kbRefreshData(){
  const el = $('#kb_refresh_status'); if (el) el.textContent = '刷新中…';
  const env = await api('/api/kb/cache/invalidate', {method: 'POST'}).catch(() => null);
  if (!env){ if (el) el.textContent = '刷新失败：接口不可达。'; return; }
  kbSiteInited = false;                       // 使知识库视图按最新数据重建
  await kbSiteShow();
  const n = (window.KNOWLEDGE_BASE && (window.KNOWLEDGE_BASE.entities || []).length) || 0;
  if (el) el.textContent = '✓ 已刷新，条目 ' + n +
    '　取数 ' + String(env.fetchedAt || '').replace('T', ' ');
}

async function loadSrcStatus(){
  const box = $('#src_status'); if (!box) return;
  const env = await api('/api/kb/sources').catch(() => null);
  const c = env && env.content;
  if (!c || !c.sources){ box.textContent = '来源状态不可达。'; return; }
  box.innerHTML = c.sources.map(s =>
    `<span class="badge b-${s.ok ? 'ok' : 'bad'}">${esc(SRC_LABEL[s.name] || s.name)}</span> `).join('') +
    `<span class="muted">　取数 ${esc((env.fetchedAt || '').replace('T', ' '))}</span>`;
}

// ---------- 首屏默认视图（知识库门户）----------
// #kbdash 为默认可见视图，首屏即引导加载知识库（样式取历史知识站点，数据走 /api/kb/knowledge）。
if (document.getElementById('kbdash')) kbSiteShow();

