#!/usr/bin/env node
/* ============================================================
   交付证据 · 逐视图截图归档（OntoRegGov 全量功能 Demo）

   为什么必须用真实浏览器截图：知识库视图曾出现"接口 200 但载荷 source=none"，
   curl 全绿但页面整页显示"来源不可用"；截图是唯一能固化"页面真实渲染结果"
   的交付证据。本脚本逐一切换视图并全页截图，用于 M4-2 验收证据归档。

   采集口径：
     - 16 个主视图（左侧菜单 data-v 值）逐一切换截全页图；
     - 进入 kbdash 后依次切换 7 个知识子路由（#kb_nav a[data-nav]）截图；
     - 共 23 张，文件命名含两位序号前缀，便于检索与目录排序。

   用法：
     node scripts/acceptance/capture_evidence.mjs                       # 默认地址与输出目录
     BASE_URL=http://host:port node scripts/acceptance/capture_evidence.mjs
     OUT_DIR=/path/to/dir node scripts/acceptance/capture_evidence.mjs
     node scripts/acceptance/capture_evidence.mjs --help

   退出码：0 = 全部采集成功；1 = 存在采集失败（缺图或页面异常）

   依赖：playwright（常规 node_modules 或 npx 缓存 ~/.npm/_npx/<hash>/node_modules）
   ============================================================ */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:8420').replace(/\/$/, '');
// 默认输出目录：产出文档唯一落位（03_平台工程/evidence/screenshots）
const DEFAULT_OUT_DIR = '/Users/FYP/Documents/@西北人的成长/10-Projects/职业项目/数据安全管理平台/03_平台工程/evidence/screenshots';
const OUT_DIR = process.env.OUT_DIR || DEFAULT_OUT_DIR;
const ARGS = process.argv.slice(2);

// 视图清单（与 app/web/static/index.html 的 nav + section 对齐）
const MAIN_VIEWS = ['kbdash', 'dsk', 'pipeline', 'dsc', 'rem', 'rep', 'diag', 'ledger', 'issues', 'gov', 'ext', 'frame', 'arch', 'capability', 'path', 'assets'];
// 知识库子路由（kbdash 内的二级导航）
const KB_ROUTES = ['home', 'graph', 'path', 'timeline', 'cases', 'controls', 'checks'];

/* ---------------- 工具 ---------------- */
function log(...a) { console.log(...a); }
function hr(t) { log('\n' + '='.repeat(64) + (t ? '\n' + t : '')); }

/** 稳健解析 playwright：常规解析 → npx 缓存目录（照抄验收脚本，确保依赖加载一致） */
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

/** 两位序号 + 视图名（英文 id）拼文件名，如 01-kbdash.png / 17-kb-home.png */
function pad(n) { return String(n).padStart(2, '0'); }

/* ============================================================
   主流程：前置 → 逐主视图截图 → 知识子路由截图 → 打印异常
   ============================================================ */
async function main(chromium) {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  // 视口宽度 1440、高度 1000（与验收脚本一致）
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

  // 采集 pageerror / console.error / requestfailed，有则打印，便于归档定位
  const jsErrs = [], reqFails = [], consErrs = [];
  page.on('pageerror', (e) => jsErrs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') consErrs.push(m.text()); });
  page.on('requestfailed', (r) => reqFails.push(r.url() + ' :: ' + (r.failure()?.errorText || '')));

  const failures = [];
  let shot = 0;

  hr('打开首页 ' + BASE_URL + '/');
  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(3000);

  /* [1] 16 个主视图逐一切换全页截图 */
  hr('[1] 主视图截图（' + MAIN_VIEWS.length + ' 项）');
  for (let i = 0; i < MAIN_VIEWS.length; i++) {
    const v = MAIN_VIEWS[i];
    const name = pad(i + 1) + '-' + v + '.png';
    const file = path.join(OUT_DIR, name);
    const link = page.locator(`#nav a[data-v="${v}"]`);
    if (!(await link.count())) {
      failures.push(v + ' 导航项缺失');
      log('FAIL'.padEnd(5), name.padEnd(20), '导航项缺失');
      continue;
    }
    await link.first().click();
    await page.waitForTimeout(1800);
    await page.screenshot({ path: file, fullPage: true });
    shot++;
    log('OK'.padEnd(5), name.padEnd(20), '已截图');
  }

  /* [2] 进入 kbdash，依次切换 7 个知识子路由截图 */
  hr('[2] 知识库子路由截图（' + KB_ROUTES.length + ' 项）');
  for (let i = 0; i < KB_ROUTES.length; i++) {
    const s = KB_ROUTES[i];
    const name = pad(MAIN_VIEWS.length + i + 1) + '-kb-' + s + '.png';
    const file = path.join(OUT_DIR, name);
    // 先回到知识库主视图，再点子路由
    await page.locator('#nav a[data-v="kbdash"]').first().click();
    await page.waitForTimeout(1000);
    const a = page.locator(`#kb_nav a[data-nav="${s}"]`);
    if (!(await a.count())) {
      failures.push('kb:' + s + ' 子导航缺失');
      log('FAIL'.padEnd(5), name.padEnd(20), '子导航缺失');
      continue;
    }
    await a.first().click();
    await page.waitForTimeout(2200);
    await page.screenshot({ path: file, fullPage: true });
    shot++;
    log('OK'.padEnd(5), name.padEnd(20), '已截图');
  }

  await browser.close();

  /* [3] 页面异常汇总（有则打印，便于归档） */
  hr('[3] 采集期页面异常');
  log('pageerror         :', jsErrs.length ? '\n  ' + jsErrs.slice(0, 8).join('\n  ') : '(none)');
  log('console.error     :', consErrs.length ? '\n  ' + consErrs.slice(0, 8).join('\n  ') : '(none)');
  log('requestfailed     :', reqFails.length ? '\n  ' + reqFails.slice(0, 8).join('\n  ') : '(none)');

  /* 汇总 */
  hr('汇总');
  log('输出目录：' + OUT_DIR);
  log('截图成功：' + shot + ' / ' + (MAIN_VIEWS.length + KB_ROUTES.length));
  if (jsErrs.length) log('提示：采集期存在 pageerror ' + jsErrs.length + ' 条');
  if (consErrs.length) log('提示：采集期存在 console.error ' + consErrs.length + ' 条');
  if (reqFails.length) log('提示：采集期存在失败请求 ' + reqFails.length + ' 条');
  if (failures.length) {
    log('结论：FAIL —— 采集失败 ' + failures.length + ' 项：');
    failures.forEach((f, i) => log('  ' + (i + 1) + '. ' + f));
    return 1;
  }
  log('结论：PASS —— 全部 ' + shot + ' 张截图已生成');
  return 0;
}

/* ---------------- 入口 ---------------- */
(async () => {
  if (ARGS.includes('--help') || ARGS.includes('-h')) {
    log(`交付证据 · 逐视图截图归档
用法：
  node scripts/acceptance/capture_evidence.mjs                默认（${BASE_URL} → ${OUT_DIR}）
  BASE_URL=<url> node scripts/acceptance/capture_evidence.mjs 指定平台地址
  OUT_DIR=<dir> node scripts/acceptance/capture_evidence.mjs  指定输出目录
退出码：0 全部成功 / 1 存在失败`);
    process.exit(0);
  }
  let pw;
  try { pw = await loadPlaywright(); }
  catch (e) { console.error('[依赖缺失] ' + e.message); process.exit(2); }
  const chromium = pw.chromium || (pw.default && pw.default.chromium);
  if (!chromium) { console.error('[依赖缺失] playwright 未导出 chromium'); process.exit(2); }

  const code = await main(chromium);
  process.exit(code);
})();
