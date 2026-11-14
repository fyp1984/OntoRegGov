#!/usr/bin/env node
/* ============================================================
   验收 · 浏览器逐视图核验（OntoRegGov 全量功能 Demo）

   为什么必须用浏览器：知识库视图曾出现"接口 200 但载荷 source=none"——
   curl 全绿、页面整页显示"来源不可用"（容器漏挂 kb_site）。
   curl 只验接口存活，验不出"接口 200 但载荷为空"这一整类缺陷。

   用法：
     node scripts/acceptance/acceptance_browser_check.mjs                     # 全量核验（默认 http://127.0.0.1:8420）
     BASE_URL=http://host:port node scripts/.../mjs                 # 指定地址
     node scripts/acceptance/acceptance_browser_check.mjs --selftest           # 判定器自检（双向识别验证）
     node scripts/acceptance/acceptance_browser_check.mjs --help

   退出码：0 = PASS；1 = FAIL（存在未通过项）

   依赖：playwright（常规 node_modules 或 npx 缓存 ~/.npm/_npx/<hash>/node_modules）
   ============================================================ */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:8420').replace(/\/$/, '');
const ARGS = process.argv.slice(2);

// 视图清单（与 app/web/static/index.html 的 nav + section 对齐，5 组 14 视图）
// 说明：checkslib（监管检查库）已并入知识库上方标签 #kb_nav（data-nav="checks"）；
//       rem 已并入 issues（安全治理）；ext 已拆为 scenario + plugin；
//       pipeline 已拆为 collect（知识采集）+ pipeline（知识发布）；
//       gov 已拆为 gov（权限与组织）+ perm（权限策略与审计）；
//       arch / capability / path / assets 四个视图已按下线要求彻底删除；
//       selfcheck（智能预检）收敛为 dsc 执行自查页内的动作入口，不再作为独立菜单。
const MAIN_VIEWS = ['dsc', 'rep', 'diag', 'ledger', 'issues',
                    'kbdash', 'collect', 'pipeline', 'scenario', 'plugin', 'gov', 'perm', 'dsk', 'frame'];
const KB_ROUTES = ['home', 'graph', 'path', 'timeline', 'cases', 'controls', 'checks'];

// 数据一致性期望值（白皮书口径：第 7/9/11 章、附录 A.1-补 / B；与差距对照表一致）
const EXPECT_FIVE = ['problems', 'bases', 'ownership', 'evidenceGaps', 'nextSteps'];
// 安全治理闭环状态机（登记 → 定级 → 派单 → 接收 → 整改 → 回复 → 复检 → 会签 → 归档）
const EXPECT_FLOW_MIN = 8;

// 降级/异常"状态"短语（判定必须是状态化，见 detectInPage）
const BAD_TEXT = ['来源不可用', '知识库暂不可达', '暂不可用'];

// 知识类取数的合法 source 枚举（PRD §7.3）
const OK_SOURCES = ['weknora', 'canonical', 'db', 'sqlite'];
// 需要 source 断言的知识类接口
const SOURCE_PROBES = ['/api/kb/knowledge/index', '/api/kb/knowledge/graph', '/api/kb/checks'];

/* ---------------- 工具 ---------------- */
function log(...a) { console.log(...a); }
function hr(t) { log('\n' + '='.repeat(64) + (t ? '\n' + t : '')); }

function captureHttpErrors(page, errors) {
  page.on('response', (r) => {
    if (r.status() >= 400) {
      errors.push(r.request().method() + ' ' + r.status() + ' ' + r.url());
    }
  });
}

function readErrorBanners(page, rootId) {
  return page.locator(`#${rootId} .dz-banner.bad:visible`).allTextContents();
}

/** 稳健解析 playwright：常规解析 → npx 缓存目录 */
async function loadPlaywright() {
  const tried = [];
  try { const m = await import('playwright'); if (m) return m; }
  catch (e) { tried.push('bare: ' + e.code); }
  const root = path.join(os.homedir(), '.npm', '_npx');
  let dirs = [];
  try { dirs = fs.readdirSync(root); } catch { /* ignore */ }
  for (const d of dirs) {
    const p = path.join(root, d, 'node_modules', 'playwright', 'index.js');
    if (fs.existsSync(p)) {
      try { const m = await import(p); if (m) return m.default || m; }
      catch (e) { tried.push(p + ': ' + e.message); }
    }
  }
  throw new Error('未找到 playwright。请先 `npx playwright install chromium` 或安装 playwright。\n尝试过：\n  ' + tried.join('\n  '));
}

/* ============================================================
   页面内判定函数（序列化后注入，主流程与 --selftest 共用同一份逻辑）
   判定语义（关键，避免两类假信号）：
     - 真降级（应 FAIL）：badge/banner 异常态文本含降级短语；
       或叶子节点文本恰好等于 / 以「短语+标点」开头。
     - 说明性文案（不应 FAIL）：红线说明句如
       "兜底才实时取数（可用来源不可用时的回落策略）" 位于 .dz-banner 正文，
       文本既非恰好相等也非短语开头 —— 不判降级。
     - 业务语义徽章（不判 FAIL）：严重度「高」、判定「不符合」、
       「构建失败」等属演示数据本身，仅作信息项输出。
   ============================================================ */
const DETECT_FN = function detectDelegation(rootId, badText, okSources) {
  const out = { ok: true, reasons: [], info: {} };
  const sec = document.getElementById(rootId);
  if (!sec) { out.ok = false; out.reasons.push('视图容器缺失 #' + rootId); return out; }

  const visible = getComputedStyle(sec).display !== 'none';
  if (!visible) { out.ok = false; out.reasons.push('视图未显示'); }

  const text = (sec.innerText || '').replace(/\s+/g, ' ').trim();
  out.info.textLen = text.length;
  if (!text) { out.ok = false; out.reasons.push('渲染后正文为空'); }

  // (1) 状态化降级判定
  const hits = [];
  sec.querySelectorAll('*').forEach((el) => {
    if (el.children.length) return;                       // 只看叶子节点
    const t = (el.textContent || '').trim();
    if (!t) return;
    if (badText.some((b) => t === b || t.startsWith(b + '，') || t.startsWith(b + '。'))) {
      hits.push('文本节点: ' + t.slice(0, 40));
    }
  });
  sec.querySelectorAll('.badge.b-bad, .dz-banner.bad, .dz-banner.bad *').forEach((el) => {
    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (t && badText.some((b) => t.includes(b))) hits.push('异常态元素: ' + t.slice(0, 40));
  });
  if (hits.length) { out.ok = false; out.reasons.push('降级状态: ' + [...new Set(hits)].join(' | ')); }

  // (2) 元信息降级判定（知识类视图的 kb_meta）
  const metaEl = document.getElementById('kb_meta');
  if (metaEl && sec.contains(metaEl)) {
    const mt = (metaEl.innerText || '').replace(/\s+/g, ' ').trim();
    if (badText.some((b) => mt.includes(b))) {
      out.ok = false; out.reasons.push('元信息降级: ' + mt.slice(0, 50));
    }
    if (mt) out.info.meta = mt.slice(0, 60);
  }

  // (3) 业务徽章仅作信息项（不判失败）
  out.info.bBad = [...sec.querySelectorAll('.badge.b-bad')]
    .map((e) => (e.innerText || '').trim()).filter(Boolean).slice(0, 4);

  // (4) 核心元素非空壳（含 button/.dz-chip：空态下的操作入口也算核心元素）
  out.info.nodes = sec.querySelectorAll(
    'a,canvas,svg,table,.card,.stat-card,.type-tile,.layer-card,button,.dz-chip,.dz-empty'
  ).length;
  if (out.info.nodes === 0) { out.ok = false; out.reasons.push('核心元素为空壳（nodes=0）'); }

  return out;
};

/* ============================================================
   自检模式：验证判定器能双向识别（真降级判 FAIL、说明文案不误判）
   ============================================================ */
async function selftest(chromium) {
  hr('判定器自检（双向识别验证）');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const httpErrors = [];
  captureHttpErrors(page, httpErrors);
  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(3000);
  // 宿主改用知识库视图（kbqa 已下线）：判定根容器 = #kb_app
  await page.locator('#nav a[data-v="kbdash"]').first().click();
  await page.waitForTimeout(2500);

  const run = (rootId) => page.evaluate(
    ({ fn, rootId, badText, okSources }) => eval('(' + fn + ')')(rootId, badText, okSources),
    { fn: DETECT_FN.toString(), rootId, badText: BAD_TEXT, okSources: OK_SOURCES }
  );
  const mutate = (js) => page.evaluate(js);

  let pass = 0, fail = 0;
  const check = (name, res, expectOk) => {
    const good = res.ok === expectOk;
    log((good ? 'PASS' : 'FAIL').padEnd(5), name.padEnd(52),
        'ok=' + res.ok, res.reasons.length ? ('| ' + res.reasons.join(' ; ').slice(0, 70)) : '');
    good ? pass++ : fail++;
  };

  // T0 真实基线：知识库视图正常渲染，不得误判
  check('T0 基线（知识库视图 #kb_app 正常渲染）', await run('kb_app'), true);

  // T0b 说明性文案（含降级短语但非"恰好相等/短语开头"）→ 不得误判
  await mutate(() => {
    const d = document.createElement('div');
    d.id = 'inj0';
    d.textContent = '兜底才实时取数（可用来源不可用时的回落策略）';
    document.getElementById('kb_app').prepend(d);
  });
  check('T0b 说明性叶子节点含「可用来源不可用」→ 不误判', await run('kb_app'), true);

  // T1 注入真实降级徽章 → 必须判失败
  await mutate(() => {
    document.getElementById('inj0')?.remove();
    const d = document.createElement('div');
    d.innerHTML = '<span class="badge b-bad" id="inj1">来源不可用</span>';
    document.getElementById('kb_app').prepend(d);
  });
  check('T1 注入 .badge.b-bad「来源不可用」→ 判 FAIL', await run('kb_app'), false);

  // T2 注入纯文本叶子节点（等价 kb_meta 降级文案）→ 必须判失败
  await mutate(() => {
    const d = document.createElement('div');
    d.id = 'inj2'; d.textContent = '来源不可用';
    document.getElementById('kb_app').prepend(d);
  });
  check('T2 叶子节点文本恰为「来源不可用」→ 判 FAIL', await run('kb_app'), false);

  // T3 普通错误 banner（无降级短语）→ 不应误判为"来源降级"
  await mutate(() => {
    document.getElementById('inj1')?.remove();
    document.getElementById('inj2')?.remove();
    const d = document.createElement('div');
    d.className = 'dz-banner bad'; d.id = 'inj3';
    d.innerHTML = '<span class="dz-banner-text">校验失败：必填项缺失，请补全后重试。</span>';
    document.getElementById('kb_app').prepend(d);
  });
  check('T3 普通 .dz-banner.bad（无降级短语）→ 不误判', await run('kb_app'), true);

  // T4 dz-banner.bad 且文本含降级短语 → 必须判失败
  await mutate(() => {
    document.getElementById('inj3')?.remove();
    const d = document.createElement('div');
    d.className = 'dz-banner bad'; d.id = 'inj4';
    d.innerHTML = '<span class="dz-banner-text">知识库暂不可达，请稍后重试。</span>';
    document.getElementById('kb_app').prepend(d);
  });
  check('T4 .dz-banner.bad「知识库暂不可达」→ 判 FAIL', await run('kb_app'), false);

  await mutate(() => {
    document.getElementById('inj4')?.remove();
    const d = document.createElement('div');
    d.className = 'dz-banner bad'; d.id = 'inj5';
    d.innerHTML = '<span class="dz-banner-text">知识文档清单获取失败：Not Found</span>';
    document.getElementById('kb_app').prepend(d);
  });
  const banners = await readErrorBanners(page, 'kbdash');
  const bannerDetected = banners.some((t) => t.includes('Not Found'));
  check('T5 页面错误横幅「Not Found」→ 被视图验收捕获',
        { ok: bannerDetected, reasons: bannerDetected ? [] : ['错误横幅未被识别'] }, true);

  const before404 = httpErrors.length;
  await page.route('**/__acceptance_selftest_404__', (route) =>
    route.fulfill({ status: 404, contentType: 'text/plain', body: 'Not Found' }));
  await page.evaluate(async () => {
    await fetch('/__acceptance_selftest_404__');
  });
  const captured404 = httpErrors.slice(before404)
    .some((entry) => entry.includes(' 404 ') && entry.includes('__acceptance_selftest_404__'));
  check('T6 HTTP 404 响应 → 被网络验收捕获',
        { ok: captured404, reasons: captured404 ? [] : ['HTTP 404 未被记录'] }, true);

  await browser.close();
  hr('自检结论：' + pass + ' pass / ' + fail + ' fail');
  log(fail === 0
    ? '自检通过——判定器可双向识别（真降级判 FAIL、说明文案不误判）'
    : '自检失败——判定器存在假阳性/假阴性，需修正后再用于验收');
  return fail === 0 ? 0 : 1;
}

/* ============================================================
   主流程：前置检查 → 逐视图核验 → JS/网络 → 汇总
   ============================================================ */
async function main(chromium) {
  const problems = [];
  let checked = 0;

  /* [1] 数据源前置检查（等价于容器 KB10_SITE 挂载检查） */
  hr('[1] 数据源前置检查（source 不得为 none）');
  for (const p of SOURCE_PROBES) {
    let src = 'ERR', note = '';
    try {
      const r = await fetch(BASE_URL + p);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      src = (j && j.source) || 'none';
      const c = j && j.content;
      if (c == null) note = 'content=null';
    } catch (e) { note = e.message; }
    const ok = OK_SOURCES.includes(src) && !note;
    if (!ok) problems.push(p + ' source=' + src + (note ? ' ' + note : ''));
    log((ok ? 'PASS' : 'FAIL').padEnd(5), p.padEnd(34), 'source=' + src, note);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const jsErrs = [], reqFails = [], httpErrors = [];
  page.on('pageerror', (e) => jsErrs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') jsErrs.push(m.text()); });
  page.on('requestfailed', (r) => reqFails.push(r.url() + ' :: ' + (r.failure()?.errorText || '')));
  captureHttpErrors(page, httpErrors);

  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(3000);

  const inspect = (rootId) => page.evaluate(
    ({ fn, rootId, badText, okSources }) => eval('(' + fn + ')')(rootId, badText, okSources),
    { fn: DETECT_FN.toString(), rootId, badText: BAD_TEXT, okSources: OK_SOURCES }
  );

  /* [2] 主视图逐一切换 */
  hr('[2] 主视图逐一切换（' + MAIN_VIEWS.length + ' 项）');
  for (const v of MAIN_VIEWS) {
    const link = page.locator(`#nav a[data-v="${v}"]`);
    if (!(await link.count())) { problems.push(v + ' 导航项缺失'); log(v.padEnd(10), 'FAIL 导航项缺失'); continue; }
    await link.first().click();
    await page.waitForTimeout(1800);
    const r = await inspect(v);
    const banners = await readErrorBanners(page, v);
    const viewOk = r.ok && banners.length === 0;
    checked++;
    if (!r.ok) problems.push(v + ' :: ' + r.reasons.join(' ; '));
    if (banners.length) problems.push(v + ' :: 页面错误横幅：' + banners.join(' | '));
    log((viewOk ? 'PASS' : 'FAIL').padEnd(5), v.padEnd(10),
        'text=' + String(r.info.textLen).padStart(5),
        'nodes=' + String(r.info.nodes).padStart(4),
        r.info.bBad && r.info.bBad.length ? '(业务徽章 ' + r.info.bBad.join('|') + ')' : '',
        !viewOk ? '→ ' + [...r.reasons, ...banners].join(' ; ').slice(0, 90) : '');
  }

  /* [3] 知识库子路由（点 nav 后取 #kb_app） */
  hr('[3] 知识库子路由（' + KB_ROUTES.length + ' 项）');
  for (const s of KB_ROUTES) {
    await page.locator('#nav a[data-v="kbdash"]').first().click();
    await page.waitForTimeout(1000);
    const a = page.locator(`#kb_nav a[data-nav="${s}"]`);
    if (!(await a.count())) { problems.push('kb:' + s + ' 子导航缺失'); log(s.padEnd(10), 'FAIL 子导航缺失'); continue; }
    await a.first().click();
    await page.waitForTimeout(2200);
    const r = await inspect('kbdash');   // 判定根为 kbdash（含 kb_meta 与 kb_app）
    const banners = await readErrorBanners(page, 'kbdash');
    const routeOk = r.ok && banners.length === 0;
    checked++;
    if (!r.ok) problems.push('kb:' + s + ' :: ' + r.reasons.join(' ; '));
    if (banners.length) problems.push('kb:' + s + ' :: 页面错误横幅：' + banners.join(' | '));
    log((routeOk ? 'PASS' : 'FAIL').padEnd(5), s.padEnd(10),
        'text=' + String(r.info.textLen).padStart(6),
        'nodes=' + String(r.info.nodes).padStart(4),
        '| ' + (r.info.meta || '').slice(0, 40),
        !routeOk ? '→ ' + [...r.reasons, ...banners].join(' ; ').slice(0, 90) : '');
  }

  /* [3.5] 交互冒烟：监管检查库（点检查项 → 六维详情；只验空态不足，必须真点一次） */
  hr('[3.5] 交互冒烟 · 监管检查库（筛选 → 点击检查项 → 六维详情）');
  {
    await page.locator('#nav a[data-v="kbdash"]').first().click();
    await page.waitForTimeout(1000);
    const checksNav = page.locator('#kb_nav a[data-nav="checks"]');
    if (!(await checksNav.count())) {
      problems.push('监管检查库子导航缺失（#kb_nav a[data-nav="checks"]）');
      log('FAIL  监管检查库子导航缺失');
    } else {
      await checksNav.first().click();
      await page.waitForTimeout(2500);
      const row = page.locator('#ck_list table tbody tr').first();
      if (!(await row.count())) {
        problems.push('监管检查库列表为空（#ck_list 无检查项行）');
        log('FAIL  检查项列表为空');
      } else {
        await row.click();
        // 轮询等待六维详情渲染（固定时长在冷启动/大列表下存在竞态；取数耗时波动可达数秒）
        const readDetail = () => page.evaluate(() => {
          const detail = document.getElementById('ck_detail');
          return {
            rowCount: document.querySelectorAll('#ck_list table tbody tr').length,
            detailLen: (detail?.innerText || '').replace(/\s+/g, ' ').trim().length,
            sections: detail?.querySelectorAll('details').length || 0,
          };
        });
        let r = { rowCount: 0, detailLen: 0, sections: 0 }, waited = 0;
        while (waited < 8000) {
          await page.waitForTimeout(250); waited += 250;
          r = await readDetail();
          if (r.detailLen > 80 && r.sections >= 3) break;
        }
        const ok = r.rowCount >= 1 && r.detailLen > 80 && r.sections >= 3;
        if (!ok) problems.push('监管检查库六维详情未正常渲染：rows=' + r.rowCount +
                               ' detailLen=' + r.detailLen + ' details=' + r.sections);
        log((ok ? 'PASS' : 'FAIL').padEnd(5), '检查项六维详情',
            '列表=' + String(r.rowCount).padStart(3),
            '详情=' + String(r.detailLen).padStart(5),
            '折叠块=' + String(r.sections).padStart(3),
            ok ? '' : '→ 未正常渲染');
        checked++;
      }
    }
  }

  /* [3.6] 交互冒烟：报告与看板 · 三步下钻（选任务 → 看板图表 → 部门下钻条目明细） */
  hr('[3.6] 交互冒烟 · 报告与看板（选任务 → 看板 → 部门下钻 → 条目明细）');
  {
    await page.locator('#nav a[data-v="rep"]').first().click();
    await page.waitForTimeout(1500);
    const pick = page.locator('#rep_body [data-act="pick"]');
    if (!(await pick.count())) {
      problems.push('报告与看板：任务选择卡片缺失（#rep_body [data-act="pick"]）');
      log('FAIL  任务选择卡片缺失');
    } else {
      await pick.first().click();
      // 轮询等待看板渲染（固定时长在冷启动下存在竞态：/items 冷路径取数可达数秒）
      const readBoard = () => page.evaluate(() => ({
        kpi: document.querySelectorAll('#rep_body .dz-kpi-row').length,
        bars: document.querySelectorAll('#rep_body [data-act="dept"]').length,
        textLen: ((document.getElementById('rep_body') || {}).innerText || '').replace(/\s+/g, ' ').trim().length,
      }));
      let board = { kpi: 0, bars: 0, textLen: 0 }, boardWaited = 0;
      while (boardWaited < 12000) {
        await page.waitForTimeout(250); boardWaited += 250;
        board = await readBoard();
        if (board.kpi >= 1 && board.bars >= 1 && board.textLen > 200) break;
      }
      const boardOk = board.kpi >= 1 && board.bars >= 1 && board.textLen > 200;
      if (!boardOk) problems.push('报告与看板：看板未渲染 kpi=' + board.kpi +
                                  ' bars=' + board.bars + ' text=' + board.textLen);
      log((boardOk ? 'PASS' : 'FAIL').padEnd(5), '看板（完成情况 + 部门比例）',
          'KPI=' + String(board.kpi).padStart(3),
          '部门条=' + String(board.bars).padStart(3),
          boardOk ? '' : '→ 未渲染');
      checked++;
      const bar = page.locator('#rep_body [data-act="dept"]').first();
      if (await bar.count()) {
        await bar.click();
        // 轮询等待条目明细渲染（同上：冷启动取数可达数秒，固定等待会误判为失败）
        const readRows = () => page.evaluate(() =>
          document.querySelectorAll('#rep_body table tbody tr[data-act="row"]').length);
        let rows = 0, rowsWaited = 0;
        while (rowsWaited < 12000) {
          await page.waitForTimeout(250); rowsWaited += 250;
          rows = await readRows();
          if (rows >= 1) break;
        }
        const ok2 = rows >= 1;
        if (!ok2) problems.push('报告与看板：部门下钻未渲染自查条目明细');
        log((ok2 ? 'PASS' : 'FAIL').padEnd(5), '部门下钻 → 自查条目明细',
            '条目=' + String(rows).padStart(4), ok2 ? '' : '→ 无条目');
        checked++;
      }
    }
  }

  /* [3.7] 交互冒烟：安全自查 · 新建自查行业档案（填写 → 创建 → 现有档案列表刷新 → 复位） */
  hr('[3.7] 交互冒烟 · 新建自查行业档案（填写 → 创建 → 现有档案列表刷新）');
  {
    await page.locator('#nav a[data-v="dsc"]').first().click();
    await page.waitForTimeout(1200);
    const tab = page.locator('#dsc_tabs .dz-tab[data-key="profile"]');
    if (!(await tab.count())) {
      problems.push('新建自查行业档案：页签缺失（#dsc_tabs .dz-tab[data-key="profile"]）');
      log('FAIL  页签缺失');
      checked++;
    } else {
      await tab.first().click();
      await page.waitForTimeout(900);
      const form = await page.evaluate(() => ({
        code: !!document.getElementById('ip_code'),
        name: !!document.getElementById('ip_name'),
        lines: !!document.getElementById('ip_lines'),
        btn: !!document.querySelector('[data-act="create-industry-profile"]'),
        rows: document.querySelectorAll('#dsc_pane table tbody tr').length,
      }));
      const formOk = form.code && form.name && form.lines && form.btn && form.rows >= 2;
      if (!formOk) problems.push('新建自查行业档案：表单或列表未渲染 ' + JSON.stringify(form));
      log((formOk ? 'PASS' : 'FAIL').padEnd(5), '行业档案新建表单 + 现有列表',
          '表单字段=4', '现有档案=' + String(form.rows).padStart(2), formOk ? '' : '→ 未渲染');
      checked++;

      const code = 'smoke' + Date.now().toString().slice(-5);
      await page.fill('#ip_code', code);
      await page.fill('#ip_name', '冒烟行业');
      await page.fill('#ip_lines', 'sm1|冒烟条线一\nsm2|冒烟条线二');
      await page.click('[data-act="create-industry-profile"]');
      await page.waitForTimeout(2200);
      const created = await page.evaluate((c) => {
        const box = document.getElementById('dsc_pane');
        return { hit: ((box || {}).innerText || '').indexOf(c) >= 0,
                 rows: document.querySelectorAll('#dsc_pane table tbody tr').length };
      }, code);
      if (!created.hit) problems.push('新建自查行业档案：创建后列表未出现新档案 ' + code);
      log((created.hit ? 'PASS' : 'FAIL').padEnd(5), '创建行业档案 → 列表刷新',
          '新增=' + code, '列表=' + String(created.rows).padStart(2), created.hit ? '' : '→ 未出现');
      checked++;

      await fetch(BASE_URL + '/api/demo/reset', { method: 'POST' }).catch(() => {});
      await page.waitForTimeout(600);
    }
  }

  /* [5] 数据一致性校验（白皮书口径：报告样例 / 场景包 / 九类问题 / 治理闭环 / 资产台账 / 知识发布 / 插件 / 组织） */
  hr('[5] 数据一致性校验（白皮书口径）');
  let dataChecked = 0;
  {
    const probes = [
      { name: '报告样例（附录 B · 五项结构）', url: '/api/report/sample', pick: (j) => j.five,
        check: (f) => !!f && EXPECT_FIVE.every((k) => Array.isArray(f[k]) && f[k].length > 0) },
      { name: '场景包（平台扩展场景 · 八项）', url: '/api/scenario-packs', pick: (j) => j.packs,
        check: (a) => a.length === 8 },
      { name: '典型问题归类（附录 A.1-补 · 九类）', url: '/api/issues/classes', pick: (j) => j.classes,
        check: (a) => a.length === 9 },
      { name: '安全治理闭环（状态机 ≥ 8 态）', url: '/api/gov/issues', pick: (j) => j.flow,
        check: (a) => Array.isArray(a) && a.length >= EXPECT_FLOW_MIN },
      { name: '资产台账（资产记录非空）', url: '/api/asset-ledger', pick: (j) => j.assets,
        check: (a) => Array.isArray(a) && a.length > 0 && a.every((x) => x.assetId && x.category) },
      { name: '知识发布（目标知识库非空）', url: '/api/kb/targets', pick: (j) => j.targets,
        check: (a) => Array.isArray(a) && a.length > 0 },
      { name: '工具插件（插件清单非空）', url: '/api/plugin-settings', pick: (j) => j.plugins,
        check: (a) => Array.isArray(a) && a.length > 0 },
      { name: '组织（组织节点 ≥ 20）', url: '/api/admin/org-nodes', pick: (j) => j.total,
        check: (n) => typeof n === 'number' && n >= 20 }
    ];
    for (const pr of probes) {
      let ok = false, note = '';
      try {
        const r = await fetch(BASE_URL + pr.url);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json();
        const arr = pr.pick(j);
        ok = !!arr && !!pr.check(arr);
        note = Array.isArray(arr) ? ('n=' + arr.length) : String(typeof arr);
      } catch (e) { note = e.message; }
      if (!ok) problems.push('数据一致性：' + pr.name);
      log((ok ? 'PASS' : 'FAIL').padEnd(5), pr.name.padEnd(32), note);
      dataChecked++;
    }
  }

  /* [4] JS 异常与失败请求 */
  hr('[4] JS 异常 / 网络失败');
  log('pageerror + console.error :', jsErrs.length ? '\n  ' + jsErrs.slice(0, 8).join('\n  ') : '(none)');
  log('requestfailed             :', reqFails.length ? '\n  ' + reqFails.slice(0, 8).join('\n  ') : '(none)');
  const uniqueHttpErrors = [...new Set(httpErrors)];
  log('HTTP 4xx/5xx              :', uniqueHttpErrors.length ? '\n  ' + uniqueHttpErrors.slice(0, 12).join('\n  ') : '(none)');
  if (jsErrs.length) problems.push('存在 JS 异常 ' + jsErrs.length + ' 条');
  if (reqFails.length) problems.push('存在失败请求 ' + reqFails.length + ' 条');
  if (uniqueHttpErrors.length) problems.push('存在 HTTP 4xx/5xx 响应 ' + uniqueHttpErrors.length + ' 条');

  await browser.close();

  /* 汇总 */
  hr('汇总');
  const smokeChecked = checked - MAIN_VIEWS.length - KB_ROUTES.length;
  log('核验项数：' + (checked + dataChecked) +
      '（主视图 ' + MAIN_VIEWS.length + ' + 知识子路由 ' + KB_ROUTES.length +
      ' + 交互冒烟 ' + smokeChecked + ' + 数据一致性 ' + dataChecked + '）');
  if (problems.length === 0) {
    log('结论：PASS —— 全部视图渲染正常，无错误横幅、HTTP 错误、JS 异常或失败请求');
    return 0;
  }
  log('结论：FAIL —— 共 ' + problems.length + ' 项问题：');
  problems.forEach((p, i) => log('  ' + (i + 1) + '. ' + p));
  return 1;
}

/* ---------------- 入口 ---------------- */
(async () => {
  if (ARGS.includes('--help') || ARGS.includes('-h')) {
    log(`验收 · 浏览器逐视图核验
用法：
  node scripts/acceptance/acceptance_browser_check.mjs                全量核验（默认 ${BASE_URL}）
  BASE_URL=<url> node scripts/acceptance/acceptance_browser_check.mjs  指定地址
  node scripts/acceptance/acceptance_browser_check.mjs --selftest      判定器自检
退出码：0 PASS / 1 FAIL`);
    process.exit(0);
  }
  let pw;
  try { pw = await loadPlaywright(); }
  catch (e) { console.error('[依赖缺失] ' + e.message); process.exit(2); }
  const chromium = pw.chromium || (pw.default && pw.default.chromium);
  if (!chromium) { console.error('[依赖缺失] playwright 未导出 chromium'); process.exit(2); }

  const code = ARGS.includes('--selftest') ? await selftest(chromium) : await main(chromium);
  process.exit(code);
})();
