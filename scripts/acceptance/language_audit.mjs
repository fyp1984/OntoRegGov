#!/usr/bin/env node
/* ============================================================
   页面语言与术语审计（验收硬项）
   对应 skills/cheersai-demo-builder/SKILL.md §4.6：
   1) 逐视图 × 逐页签 dump 用户可见文本，检查禁用术语残留；
   2) 覆盖知识库各子路由（首页/图谱/学习路径/时间线/案例/控制体系/监管检查库）；
   3) 输出页面残留的拉丁字母词频（供人工判断是否仍需中文化），
      并汇总 JS 异常与 4xx/5xx 请求。

   用法：
     node scripts/acceptance/language_audit.mjs
     BASE_URL=http://127.0.0.1:8420 node scripts/acceptance/language_audit.mjs
   退出码：0 = 无残留（PASS）；1 = 存在禁用术语残留。
   ============================================================ */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const BASE_URL = (process.env.BASE_URL || 'http://127.0.0.1:8420').replace(/\/$/, '');

async function resolvePlaywright() {
  try { const m = await import('playwright'); if (m) return m; } catch (e) {}
  const roots = [path.join(os.homedir(), '.npm', '_npx')];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    for (const d of fs.readdirSync(root)) {
      const p = path.join(root, d, 'node_modules', 'playwright', 'index.js');
      if (fs.existsSync(p)) { try { const m = await import(p); if (m) return m.default || m; } catch (e) {} }
    }
  }
  throw new Error('未找到 playwright');
}

// 禁用词口径见 SKILL.md §4.4 术语对照表；机器可读标识（接口路径/表名/字段名）
// 属知识库正文与接口契约样例，已在 visibleText() 中排除，不参与判定。
const FORBIDDEN = [
  '质量门', '差分明细', '原子发布', '原子', '更新标识 updated_at', 'updated_at', 'Webhook', 'webhook',
  'manifest', 'Manifest', 'docId', 'docKey', 'prev_hash', 'append-only', 'runId ', 'run-live',
  'ERROR=0', 'WARN=0', 'strict', 'canonical', 'MCP', 'HITL', 'SoD',
  '端到端', 'packId', 'invocationId', 'latencyMs', 'worst-case', 'in_progress',
  'avgProgress', 'riskLevel', 'computedAt', 'routedToHuman', 'WeKnora', 'weknora', '时延(ms)'
];

const VIEWS = ['kbdash', 'dsk', 'pipeline', 'dsc', 'rem', 'rep', 'gov', 'ext', 'frame', 'arch', 'capability', 'path', 'settings'];
// 知识库子路由（kbdash 内的二级导航）
const KB_SUBROUTES = ['home', 'graph', 'path', 'timeline', 'cases', 'controls', 'checks'];

const pw = await resolvePlaywright();
const chromium = pw.chromium || (pw.default && pw.default.chromium);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
const http4xx = [];
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') errors.push('console.error: ' + m.text()); });
page.on('response', r => { if (r.status() >= 400) http4xx.push(r.status() + ' ' + r.url()); });

await page.goto(BASE_URL + '/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);

function visibleText() {
  return page.evaluate(() => {
    const sec = document.querySelector('section.view:not(.hidden)');
    if (!sec) return { chrome: '', full: '', labels: '' };
    const full = sec.innerText || '';
    // 界面语言审计口径：知识库正文（#kb_app，属"事实源内容"）与接口契约样例
    // （.dz-contract，属"机器可读示例"）不纳入禁用词判定，但仍计入拉丁词频。
    const clone = sec.cloneNode(true);
    clone.querySelectorAll('#kb_app, .dz-contract').forEach(n => n.remove());
    // 标签类文案（标题 / 表头 / 字段名 / 页签），用于识别"中文标签 + 英文字段名"混排；
    // 数据值单元（账号 / 编号 / 编码等标识符）不在其列，避免误判合法标识符。
    const LABEL_SEL = 'h1,h2,h3,h4,h5,h6,th,label,legend,.dz-tab,.dz-metric-k,.dz-kpi-k,.dz-kpi-label';
    const labels = Array.from(clone.querySelectorAll(LABEL_SEL)).map(n => n.innerText || '').join(' | ');
    return { chrome: clone.innerText || '', full: full, labels: labels };
  });
}

let bad = 0;
const latinFreq = {};

// 标签文案中"中文标签 + 小写英文标识"混排（如「差距 gaps」「数据范围 scope」）也判为不一致
const CN_EN_LEAK = /[\u4e00-\u9fa5]\s+[a-z][a-zA-Z_]{3,}/g;

function scan(label, res) {
  const hits = FORBIDDEN.filter(t => res.chrome.includes(t));
  (res.labels.match(CN_EN_LEAK) || []).forEach(s => {
    const v = s.trim();
    if (!hits.includes(v)) hits.push(v);
  });
  if (hits.length) { bad += hits.length; console.log(`FAIL  ${label}  残留: ${hits.join(' | ')}`); }
  else console.log(`OK    ${label}  (界面文案 ${res.chrome.length} chars / 全文 ${res.full.length} chars)`);
  for (const w of (res.full.match(/[A-Za-z][A-Za-z0-9_.\-]{2,}/g) || [])) {
    latinFreq[w] = (latinFreq[w] || 0) + 1;
  }
}

// 1) 主视图 × 页签
for (const v of VIEWS) {
  await page.evaluate(id => window.showView(id), v);
  await page.waitForTimeout(1400);
  const tabKeys = await page.evaluate(() => {
    const sec = document.querySelector('section.view:not(.hidden)');
    if (!sec) return [];
    return Array.from(sec.querySelectorAll('.dz-tabs .dz-tab')).map(b => b.getAttribute('data-key'));
  });
  if (!tabKeys.length) {
    scan(v, await visibleText());
    continue;
  }
  for (const k of tabKeys) {
    await page.evaluate((key) => {
      const sec = document.querySelector('section.view:not(.hidden)');
      const b = sec && sec.querySelector('.dz-tabs .dz-tab[data-key="' + key + '"]');
      if (b) b.click();
    }, k);
    await page.waitForTimeout(1100);
    scan(`${v}/${k}`, await visibleText());
  }
}

// 2) 知识库子路由
for (const r of KB_SUBROUTES) {
  await page.evaluate(() => window.showView('kbdash'));
  await page.waitForTimeout(900);
  await page.evaluate((route) => {
    if (typeof window.showKbRoute === 'function') window.showKbRoute(route);
    else if (location.hash !== '#' + route) location.hash = '#' + route;
  }, r);
  await page.waitForTimeout(1200);
  scan(`kbdash:${r}`, await visibleText());
}

console.log('\nJS 错误：', errors.length ? errors.join('\n  ') : '(none)');
console.log('HTTP 4xx/5xx：', http4xx.length ? http4xx.join('\n  ') : '(none)');
console.log('\n页面残留拉丁词频（≥2 次，供人工判断）：');
Object.entries(latinFreq).sort((a, b) => b[1] - a[1]).filter(([, n]) => n >= 2)
  .slice(0, 60).forEach(([w, n]) => console.log(`  ${String(n).padStart(3)}  ${w}`));
console.log(bad ? `\n结论：仍有 ${bad} 处禁用术语残留` : '\n结论：PASS —— 用户可见文案中无禁用术语');
await browser.close();
process.exit(bad ? 1 : 0);
