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

// ---------- 合规自查（v1.18.0：OpenClaw 智能体版）----------
// 前端只负责输入（合规文件 + 被检查目录）与输出（逐检查项结果 + PDF 报告），
// 全部检查逻辑由后端 openclaw 智能体完成；每注册用户在同一 gateway 内
// 拥有专属 agent（轻隔离），访客共用 guest agent。
const SC_R = {pass:'符合', partial:'部分符合', fail:'不符合', missing:'证据缺失', manual:'需人工'};
const SC_V = SC_R;
function scBadge(r){return `<span class="badge b-${r==='pass'?'ok':r==='partial'?'warn':r==='missing'?'unk':'bad'}">${SC_R[r]||r||'—'}</span>`;}
let scPollTimer = null, scLastRunId = null;

function scUserKey(){ const u=($('#sc_user').value||'').trim(); return u? 'u:'+u : 'default'; }

async function scInit(){
  scLoadTitles();
  scLoadAgentStatus();
  // 记住上次输入
  try{
    const d=localStorage.getItem('sc_dir'); if(d) $('#sc_dir').value=d;
    const u=localStorage.getItem('sc_user'); if(u) $('#sc_user').value=u;
  }catch(e){}
  // 默认展示最近一次执行结果记录（服务端查最新，跨浏览器一致；执行中则继续轮询）
  const lst=await api('/api/selfcheck/runs?limit=1').catch(()=>null);
  const latest=lst&&lst.runs&&lst.runs[0];
  if(latest){ scLastRunId=latest.runId; scPoll(latest.runId); }
}
async function scLoadTitles(){
  const doc=$('#sc_doc').value, pri=$('#sc_pri').value;
  const d=await api('/api/checks?doc='+doc+(pri?'&priority='+pri:''));
  $('#sc_doc_meta').textContent=`共 ${d.filtered} 个检查项`;
}
async function scRegister(){
  const u=($('#sc_user').value||'').trim();
  if(!u){ $('#sc_agent_hint').textContent='请先输入用户名。'; return; }
  $('#sc_agent_hint').textContent='注册中（在智能体服务内创建专属智能体）…';
  const r=await api('/api/users/register',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:u})}).catch(()=>null);
  if(!r||r.error){ $('#sc_agent_hint').textContent = r&&r.error? (r.error.message||'注册失败') : '接口不可达'; return; }
  $('#sc_agent_hint').textContent=`✓ 专属智能体 ${r.agentId}${r.agentCreated?'（已新建）':'（已存在）'}`;
  try{localStorage.setItem('sc_user',u);}catch(e){}
  scLoadAgentStatus();
}
async function scStart(){
  const dir=($('#sc_dir').value||'').trim();
  if(!dir) return alert('请输入被检查文件目录（本地路径或共享盘 UNC 路径）。');
  const body={doc:$('#sc_doc').value, dir, priority:$('#sc_pri').value,
              limit:parseInt($('#sc_limit').value||'0',10), userKey:scUserKey()};
  $('#sc_start_btn').disabled=true;
  const r=await api('/api/selfcheck/runs',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)}).catch(e=>({error:{message:'接口不可达：'+e}}));
  $('#sc_start_btn').disabled=false;
  if(!r||r.error){ $('#sc_progress').innerHTML='<span class="badge b-bad">启动失败</span> '+esc((r&&r.error&&(r.error.message||r.error.code))||''); return; }
  scLastRunId=r.runId;
  try{localStorage.setItem('sc_dir',dir);localStorage.setItem('sc_last_run',r.runId);}catch(e){}
  $('#sc_results').innerHTML='<p class="muted">已提交智能体（agent: '+esc(r.agentId||'')+'），执行中…</p>';
  scPoll(r.runId);
}
function scResume(runId){ scPoll(runId); }
async function scPoll(runId){
  clearTimeout(scPollTimer);
  const d=await api('/api/selfcheck/runs/'+runId).catch(()=>null);
  if(!d||d.error){ $('#sc_progress').innerHTML='<span class="muted">运行记录读取失败。</span>'; return; }
  const s=d.summary||{};
  $('#sc_progress').innerHTML=
    `<span class="badge b-${d.status==='done'?'ok':d.status==='error'?'bad':'warn'}">${d.status==='running'?'智能体执行中':d.status==='done'?'已完成':d.status==='error'?'出错':d.status}</span>`+
    ` 进度 ${d.done||0}/${d.total||0}　文件 ${d.fileCount||0} 个　agent <code>${esc(d.agentId||'')}</code>`+
    `　依据 ${esc(d.docNo||d.doc||'')}　目录 <code>${esc(d.dir||'')}</code>`+
    (d.error?`　<span class="muted">${esc(d.error)}</span>`:'')+
    (d.status==='done'?`　<a href="/api/selfcheck/runs/${runId}/report.pdf" class="ghost-link">导出合规自查报告（PDF）</a>`:'');
  scRenderResults(d);
  if(d.status==='running') scPollTimer=setTimeout(()=>scPoll(runId), 4000);
}
function scRenderResults(d){
  const items=d.items||[];
  if(!items.length && d.status==='running'){ return; }
  if(!items.length){ $('#sc_results').innerHTML='<p class="muted">暂无结果。</p>'; return; }
  const s=d.summary||{};
  const stats=`<div>
    <span class="stat"><b>${s.complianceRate||0}%</b>检查项合规率</span>
    <span class="stat"><b>${s.pass||0}</b>符合</span>
    <span class="stat"><b>${s.partial||0}</b>部分符合</span>
    <span class="stat"><b>${s.fail||0}</b>不符合</span>
    <span class="stat"><b>${s.missing||0}</b>证据缺失</span>
    <span class="stat"><b>${s.manual||0}</b>需人工</span></div>`;
  $('#sc_results').innerHTML=stats+items.map(it=>{
    const els=(it.elements||[]).map(e=>
      `<tr><td>${esc(e.code||'')}</td><td>${scBadge(e.verdict)}</td>
       <td>${esc((e.evidenceFiles||[]).join('、')||'—')}</td><td class="muted">${esc(e.reason||'')}</td></tr>`).join('');
    const gaps=(it.gaps||[]).map(g=>`<li>${esc(g)}</li>`).join('');
    const rem=(it.remediation||[]).map(g=>`<li>${esc(g)}</li>`).join('');
    const miss=(it.missingEvidence||[]).map(g=>`<li>${esc(g)}</li>`).join('');
    const rf=(it.readFiles||[]);
    return `<details${it.result!=='pass'?' open':''}><summary>${esc(it.checkCode)} ${esc(it.title)}
      ${scBadge(it.result)}${it.priority?` <span class="pill">${esc(it.priority)}</span>`:''}
      ${it.confidence!=null?`<span class="muted">置信 ${Math.round(it.confidence*100)}%</span>`:''}</summary>
      <p class="muted">${esc(it.summary||'')}${it.error?`　<span class="badge b-bad">智能体失败</span> ${esc(it.error)}`:''}</p>
      ${rf.length?`<p class="muted" style="font-size:12px">智能体自主取证 ${rf.length} 份文件：${esc(rf.join('、'))}</p>`:''}
      ${els?`<table><tr><th>要素</th><th>判定</th><th>证据文件</th><th>智能体理由</th></tr>${els}</table>`:''}
      ${miss?`<p><b>缺失证据</b></p><ul>${miss}</ul>`:''}
      ${gaps?`<p><b>差距</b></p><ul>${gaps}</ul>`:''}
      ${rem?`<p><b>整改建议</b></p><ul>${rem}</ul>`:''}
    </details>`;
  }).join('');
}
async function scLoadAgentStatus(){
  const box=$('#sc_oc_status'); if(!box) return;
  const d=await api('/api/selfcheck/agent/status').catch(()=>null);
  if(!d){ box.innerHTML='<span class="badge b-bad">状态接口不可达</span>'; return; }
  const g=d.gateway||{};
  box.innerHTML=`<span class="badge b-${g.ok?'ok':'bad'}">${g.ok?'OpenClaw 智能体服务在线':'智能体服务离线（启动自查时自动拉起）'}</span>`+
    ` <span class="muted">端点 ${esc(g.base||'—')}　整合目录 <code>${esc(d.home||'')}</code></span>`;
}

// 检查台账（M5）本版本暂不提供：按需求先移除菜单与页面，后续再行补充。

async function loadChecks() {
  const docEl = $('#ck_doc'), domEl = $('#ck_domain'), priEl = $('#ck_pri'), kwEl = $('#ck_kw'), listEl = $('#ck_list');
  if (!listEl) return;
  const doc = docEl ? docEl.value : '', dom = domEl ? domEl.value : '',
        pri = priEl ? priEl.value : '', kw = kwEl ? kwEl.value.trim() : '';
  let url = '/api/checks?';
  if (doc) url += '&doc=' + doc;
  if (dom) url += '&domain=' + dom;
  if (pri) url += '&priority=' + pri;
  if (kw) url += '&keyword=' + encodeURIComponent(kw);
  listEl.innerHTML = '<span class="muted">加载中…</span>';
  const d = await api(url);
  const docLabel = {jg24:'金规〔2024〕24号', jg93:'金办发〔2025〕93号', pboc3:'人行令〔2025〕第3号', jf8:'金发〔2026〕8号'};
  if (!d || !d.checks){ listEl.innerHTML = '<span class="muted">检查项取数失败，请稍后重试。</span>'; return; }
  const rows = d.checks.map(c =>
    `<tr style="cursor:pointer" onclick="showCheck('${c.checkCode}')" title="查看 ${esc(c.checkCode)} 六维详情">
      <td><b>${esc(c.checkCode)}</b></td><td>${esc(c.title)}</td>
      <td><span class="pill">${esc(c.priority)}</span></td><td>${esc(c.domainLabel||c.domain||'')}</td>
      <td><span class="muted">${esc(docLabel[c.docKey]||c.docKey||'')}</span></td></tr>`).join('');
  listEl.innerHTML =
    `<div class="muted" style="margin:0 0 8px">共 <b>${d.filtered != null ? d.filtered : d.checks.length}</b> 项` +
    `${d.total != null && d.total !== d.filtered ? `（总 ${d.total} 项）` : ''}</div>` +
    '<table><thead><tr><th>编号</th><th>标题</th><th>优先级</th><th>领域</th><th>文号</th></tr></thead>' +
    '<tbody>' + (rows || '<tr><td colspan=5>没有匹配的检查项</td></tr>') + '</tbody></table>';
}
async function showCheck(code) {
  const box = $('#ck_detail');
  if (!box) return;
  box.innerHTML = '<span class="muted">加载中…</span>';
  const c = await api('/api/checks/' + code);
  if (!c || c.error){ box.innerHTML = '<span class="muted">检查项加载失败，请稍后重试。</span>'; return; }
  const lvColor = {L1:'#1B4FE4',L2:'#3a6bf0',L3:'#6d90f5',L4:'#e08a00',L5:'#2a9d5c'};
  const el = (c.elements||[]).map(e =>
    `<tr><td><b>${esc(e.code)}</b></td><td>${esc(e.text)}</td>
      <td>${(e.focusLevels||'').split(',').filter(Boolean).map(l=>`<span style="color:${lvColor[l]}" class="pill">${esc(l)}</span>`).join(' ') || '<span class="muted">—</span>'}</td></tr>`).join('');
  const steps = (c.methodSteps||[]).map(s=>{
    const kind = s.stepKind === 'evidence' ? '查证据' : '查制度';
    const focus = (s.stepKind === 'evidence' && s.focus) ? ` — <span class="muted">${esc(s.focus)}</span>` : '';
    return `<li><b>[${kind}${esc(String(s.stepNo))}]</b> ${esc(s.action || s.focus || '')}${focus}</li>`;
  }).join('');
  const v = c.verdict || {};
  const vd = k => {
    let arr = [];
    try { arr = JSON.parse(v[k] || '[]') || []; } catch (e) { arr = []; }
    return arr.map(x => `<li>${esc(x)}</li>`).join('');
  };
  const vBlock = (label, cls, key) =>
    `<p style="margin:10px 0 2px"><span class="badge ${cls}">${label}</span></p><ul style="margin:4px 0">${vd(key) || '<li class="muted">—</li>'}</ul>`;
  const fp = (c.findings||[]).map(f =>
    `<li><b>问题</b>　${esc(f.problem)}<br><span class="muted"><b>根因</b>：${esc(f.rootCause||'—')}；<b>整改</b>：${esc(f.remediation||'—')}</span></li>`).join('');
  const rel = (c.related||[]).map(r => `<li><b>${esc(r.ref)}</b>（关联）</li>`).join('');
  const sc = (c.suggestedControls||[]).map(s=>{
    const badge = s.status === 'provisional'
      ? `<span class="badge b-warn">暂定对应 · 待 CT 确认</span>`
      : `<span class="badge b-unk">待对齐（10 工程 v1.5）</span>`;
    return `<li><span class="pill">${esc(s.layer)}</span> <b>${esc(s.name)}</b> ${badge}<br>
      <span class="muted">${esc(s.type||'')}${s.baseControlTitle ? '｜暂定对应底座：' + esc(s.baseControlTitle) : ''}</span></li>`;
  }).join('');
  box.innerHTML = `
    <h4>${esc(c.checkCode)} ${esc(c.title)} <span class="pill">${esc(c.priority)}</span> <span class="muted">${esc(c.domainLabel||c.domain||'')}</span></h4>
    <p class="muted"><b>依据</b> ${esc(c.regulation||'—')} <b>（${esc(c.articleNo||'—')}）</b>｜<b>挂接法条</b>：${esc((c.citesClause||[]).join('、')||'—')}</p>
    <details open><summary>条文原文</summary><p>${esc(c.articleText||'（同前条，见法条）')}</p></details>
    <details open><summary>检查清单（要素 · 关注层级色标）</summary><table>
      <thead><tr><th>要素</th><th>检查内容</th><th>关注层级</th></tr></thead>
      <tbody>${el||'<tr><td colspan=3 class="muted">—</td></tr>'}</tbody></table></details>
    <details><summary>检查方法（查制度 · 查证据${c.tip?' · <b>杀手锏：'+esc(c.tip)+'</b>':''}）</summary><ol>${steps||'<li>—</li>'}</ol></details>
    <details><summary>三档判定要点</summary>
      ${vBlock('通过','b-ok','verdictPass')}
      ${vBlock('部分符合','b-warn','verdictPartial')}
      ${vBlock('不符合','b-bad','verdictFail')}</details>
    <details><summary>常见问题 / 根因 / 整改</summary><ul>${fp||'<li>—</li>'}</ul></details>
    <details><summary>关联检查项</summary><ul>${rel||'<li>—</li>'}</ul>
      <p class="muted">${esc(c.relatedRaw||'')}</p></details>
    <details open><summary>建议控制措施（占位 · 待 10 工程 v1.5 CT 编码对齐）</summary>
      <p class="muted">以下为检查侧控制需求占位，<b>非已落实 / 已对齐权威控制</b>；权威控制词汇唯一事实源 = <b>10 工程 v1.5</b>。</p>
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
let kbEffCount = 0;   // 部署当前生效的知识库数量（未勾选时用于说明兜底口径）
function loadSettings(){ loadKbPick(); loadLlmset(); loadSrcStatus(); }

async function loadKbPick(){
  const box = $('#kb_pick'); if (!box) return;
  box.innerHTML = '<span class="muted">加载中…</span>';
  const d = await api('/api/settings/kb').catch(() => null);
  if (!d || d.available === undefined){
    box.innerHTML = '<span class="muted">知识库列表不可达，请检查知识库平台。</span>'; return;
  }
  const degraded = d.source === 'degraded';
  const note = degraded
    ? '<div class="muted" style="margin-bottom:8px"><span class="badge b-warn">降级展示</span> ' +
      '知识库平台暂不可达，以下为<strong>演示知识库目录</strong>（已含部署当前生效库），' +
      '可正常勾选，不阻断作业。</div>'
    : '';
  if (!d.available.length){
    box.innerHTML = note + '<span class="muted">暂无可用知识库。</span>'; return;
  }
  const sel = d.selected || [];
  const docs = n => (n === null || n === undefined) ? '篇数 —' : (n + ' 篇');
  const eff = d.effective || [];
  box.innerHTML = note + d.available.map(k => `
    <label class="pick" title="${esc(k.id)}">
      <input type="checkbox" value="${esc(k.id)}" ${sel.includes(k.id) ? 'checked' : ''}>
      <span class="pick-name">${esc(k.name)}</span>
      ${k.effective ? '<span class="badge b-ok">当前生效</span>' : ''}
      <span class="pick-meta">${docs(k.docCount)}</span>
    </label>`).join('');
  kbPickStatus(sel.length, eff.length);
}

function kbPickStatus(n, effN){
  const el = $('#kb_pick_status'); if (!el) return;
  if (effN !== undefined) kbEffCount = effN;
  const base = n ? `已选 ${n} 个知识库`
    : (kbEffCount ? `未选择，使用部署默认的 ${kbEffCount} 个知识库` : '未选择，使用默认知识库');
  el.textContent = base;
}

async function kbPickSave(){
  const ids = Array.from(document.querySelectorAll('#kb_pick input:checked')).map(x => x.value);
  const el = $('#kb_pick_status'); if (el) el.textContent = '保存中…';
  const r = await api('/api/settings/kb', {method: 'PUT',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ids})}).catch(() => null);
  if (!r || r.error){ if (el) el.textContent = '保存失败：接口不可达。'; return; }
  kbSiteInited = false;                       // 使知识库视图下次进入时按新配置重建
  kbPickStatus((r.selected || []).length, (r.effective || []).length);
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

