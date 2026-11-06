import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const root = new URL('../public/', import.meta.url);
const html = readFileSync(new URL('index.html', root), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const priority = JSON.parse(readFileSync(new URL('data/market_priority.json', root)));
const summary = JSON.parse(readFileSync(new URL(priority.summaryPath, root)));
const historyOf = symbol => JSON.parse(readFileSync(new URL(summary.historyPaths[symbol], root))).rows;
function rangeText(symbol, years) {
  const rows = historyOf(symbol);
  const end = rows.at(-1)[0];
  const cutoff = new Date(`${end}T00:00:00Z`);
  cutoff.setUTCFullYear(cutoff.getUTCFullYear() - years);
  const start = rows.find(row => row[0] >= cutoff.toISOString().slice(0, 10))[0];
  return `${start} 至 ${end}`;
}
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setTimeout(resolve, 0)); };

function element() {
  return {
    value: 'all', textContent: '', style: {}, children: [], events: {}, hidden: true,
    classList: { toggle() {} },
    addEventListener(name, callback) { this.events[name] = callback; },
    appendChild(child) { this.children.push(child); },
    set innerHTML(value) { this.html = value; this.children = []; },
    get innerHTML() { return this.html || ''; },
    getBoundingClientRect() { return { width: 900, height: 440, left: 0 }; },
    getContext() { return new Proxy({}, { get: () => () => {}, set: () => true }); },
  };
}

function app(intercept = () => undefined) {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  get('#search').value = '';
  const requests = [];
  const context = vm.createContext({
    Intl, AbortController, setTimeout, clearTimeout,
    requestAnimationFrame: callback => callback(),
    document: { querySelector: get, querySelectorAll: () => [], createElement: element },
    window: { devicePixelRatio: 1, addEventListener() {} },
    fetch: async url => {
      requests.push(url);
      const custom = intercept(url);
      if (custom) return { ok: true, json: () => custom };
      return { ok: true, json: async () => JSON.parse(readFileSync(new URL(url, root))) };
    },
  });
  vm.runInContext(source, context);
  const select = symbol => {
    const button = get('#symbolList').children.find(item => item.innerHTML.includes(`class="ticker">${symbol}<`));
    assert.ok(button, `Missing ${symbol} button`);
    button.events.click();
  };
  const range = value => get('#rangeButtons').events.click({ target: { tagName: 'BUTTON', dataset: { range: value } } });
  return { get, requests, select, range };
}

test('QQQ and SPY render first without downloading full histories', async () => {
  const ui = app();
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^QQQ/);
  assert.equal(ui.requests[0], './data/market_priority.json');
  assert.equal(ui.requests.filter(url => url.includes('/series/')).length, 0);
  assert.equal(ui.get('#symbolList').children.length, summary.symbols.length);
  ui.select('SPY');
  assert.match(ui.get('#chartTitle').textContent, /^SPY/);
  assert.equal(ui.requests.filter(url => url.includes('/series/')).length, 0);
  ui.range('5y');
  await flush();
  assert.equal(ui.requests.filter(url => url.includes('/series/SPY.')).length, 1);
  assert.doesNotMatch(ui.get('#chartSubtitle').textContent, /加载中/);
  ui.range('3y');
  await flush();
  assert.equal(ui.requests.filter(url => url.includes('/series/SPY.')).length, 1);
  assert.ok(ui.requests.every(url => !url.includes('market_dca.')));
});

test('stock summaries display immediately and late histories cannot replace another stock', async () => {
  let finishNvda;
  const nvda = new Promise(resolve => { finishNvda = resolve; });
  const ui = app(url => url.includes('/NVDA.') ? nvda : undefined);
  await flush();
  ui.select('NVDA');
  assert.match(ui.get('#chartTitle').textContent, /^NVDA/);
  assert.notEqual(ui.get('#latestPrice').textContent, '--');
  ui.select('AAPL');
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^AAPL/);
  finishNvda(JSON.parse(readFileSync(new URL(summary.historyPaths.NVDA, root))));
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^AAPL/);
  ui.select('NVDA');
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^NVDA/);
  assert.equal(ui.requests.filter(url => url.includes('/series/NVDA.')).length, 1);
});

test('network failures stop retrying and expose a working retry control', async () => {
  let offline = true;
  const ui = app(url => url === './data/market_priority.json' && offline ? Promise.reject(new Error('offline')) : undefined);
  await flush();
  assert.equal(ui.requests.length, 3);
  assert.equal(ui.get('#retryData').hidden, false);
  assert.match(ui.get('#updated').textContent, /网络异常/);
  offline = false;
  ui.get('#retryData').events.click();
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^QQQ/);
  assert.equal(ui.get('#retryData').hidden, true);
});

test('index ten-year, twenty-year and all-history views reuse one on-demand download', async () => {
  const ui = app();
  await flush();
  ui.range('10y');
  await flush();
  assert.ok(ui.get('#chartSubtitle').textContent.endsWith(rangeText('QQQ', 10)));
  ui.range('20y');
  await flush();
  assert.ok(ui.get('#chartSubtitle').textContent.endsWith(rangeText('QQQ', 20)));
  ui.range('all');
  await flush();
  assert.ok(ui.get('#chartSubtitle').textContent.endsWith(`2000-01-03 至 ${historyOf('QQQ').at(-1)[0]}`));
  assert.equal(ui.requests.filter(url => url.includes('/series/QQQ.')).length, 1);
  ui.select('SPY');
  await flush();
  assert.ok(ui.get('#chartSubtitle').textContent.endsWith(`2000-01-03 至 ${historyOf('SPY').at(-1)[0]}`));
  assert.equal(ui.requests.filter(url => url.includes('/series/SPY.')).length, 1);
  ui.select('AAPL');
  await flush();
  assert.match(ui.get('#chartTitle').textContent, /^AAPL/);
  assert.ok(ui.get('#chartSubtitle').textContent.endsWith(rangeText('AAPL', 5)));
});
