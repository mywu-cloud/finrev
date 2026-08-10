// scripts/fetch-revenue.js
// Fetches TaiwanStockInfo + TaiwanStockMonthRevenue from FinMind and writes
// cached JSON snapshots (data/revenue-twse.json, data/revenue-tpex.json)
// used by the front-end so it does not have to query FinMind live, per
// stock, on every page load. This removes the rate-limited per-stock
// live loop that previously ran on every visit for the "搶先報" tabs.
//
// Resumable design: a stock is skipped entirely (no FinMind call) if its
// cached revenue history already has a value for the current "target
// month" (the month currently being progressively disclosed, before the
// 10th of the following month). Once every stock's target month is
// filled in, later scheduled runs in the same window do nothing.
const fs = require('fs');
const path = require('path');

const FINFO = 'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo';
const FREV = 'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id=';
const TOKEN = process.env.FINMIND_TOKEN || '';
const BAD = ['ETF', '存託憑證', '特別股', '受益憑證'];
const BATCH = 10;
const DELAY_MS = 350;
const DATA_DIR = path.join(__dirname, '..', 'data');

function ok4(code) { return /^[1-9][0-9]{3}$/.test(code); }
function okName(name) { return !BAD.some(function (b) { return (name || '').indexOf(b) >= 0; }); }
function withToken(url) { return TOKEN ? url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + TOKEN : url; }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function isTaipeiWeekday() {
  const now = new Date(Date.now() + 8 * 3600 * 1000);
  const dow = now.getUTCDay();
  return dow >= 1 && dow <= 5;
}

function targetMonth() {
  const now = new Date(Date.now() + 8 * 3600 * 1000);
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth() + 1;
  const d = now.getUTCDate();
  let ty = y, tm;
  if (d > 15) { tm = m; } else { tm = m - 1; }
  if (tm <= 0) { tm += 12; ty -= 1; }
  return ty * 100 + tm;
}

async function fetchJson(url) {
  const res = await fetch(withToken(url));
  return res.json();
}

async function fetchStockList() {
  const data = await fetchJson(FINFO);
  if (data.status !== 200) return { twse: [], tpex: [] };
  const seen = {};
  const twse = [], tpex = [];
  for (const s of data.data || []) {
    if (!ok4(s.stock_id) || !okName(s.stock_name || '')) continue;
    if (seen[s.stock_id]) continue;
    seen[s.stock_id] = true;
    if (s.type === 'twse') twse.push(s);
    else if (s.type === 'tpex') tpex.push(s);
  }
  return { twse, tpex };
}

function loadExisting(market) {
  const file = path.join(DATA_DIR, 'revenue-' + market + '.json');
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return { updatedAt: '', targetMonth: {}, stocks: {} };
  }
}

function parseRevenueRows(arr) {
  const months = {};
  for (const d of arr) {
    if (d.revenue_year == null || d.revenue_month == null) continue;
    months[d.revenue_year + '_' + d.revenue_month] = d.revenue;
  }
  return months;
}

async function build(market, stocks) {
  const cache = loadExisting(market);
  if (!cache.stocks) cache.stocks = {};
  const target = targetMonth();
  const ty = Math.floor(target / 100), tm = target % 100;
  const targetKey = ty + '_' + tm;
  const now = new Date();
  const startDate = (now.getFullYear() - 1) + '-01-01';

  const todo = stocks.filter(function (s) {
    const c = cache.stocks[s.stock_id];
    return !(c && c.months && c.months[targetKey] != null);
  });

  console.log('[' + market + '] total=' + stocks.length + ' todo=' + todo.length + ' targetKey=' + targetKey);

  let quotaHit = false;
  for (let i = 0; i < todo.length && !quotaHit; i += BATCH) {
    const batch = todo.slice(i, i + BATCH);
    const results = await Promise.all(batch.map(function (s) {
      const url = FREV + s.stock_id + '&start_date=' + startDate;
      return fetchJson(url).catch(function () { return { status: 0, data: [] }; }).then(function (d) { return { s: s, d: d }; });
    }));
    for (const r of results) {
      if (r.d && r.d.status === 402) { quotaHit = true; break; }
      if (!r.d || r.d.status !== 200) continue;
      const months = parseRevenueRows(r.d.data || []);
      if (!Object.keys(months).length) continue;
      const prev = cache.stocks[r.s.stock_id] || {};
      cache.stocks[r.s.stock_id] = {
        name: r.s.stock_name || prev.name || '',
        industry: r.s.industry_category || prev.industry || '',
        months: months
      };
    }
    console.log('[' + market + '] ' + Math.min(i + BATCH, todo.length) + '/' + todo.length + (quotaHit ? ' (quota hit)' : ''));
    if (i + BATCH < todo.length && !quotaHit) await sleep(DELAY_MS);
  }

  cache.updatedAt = new Date().toISOString();
  cache.targetMonth = { year: ty, month: tm, key: targetKey };
  return cache;
}

async function main() {
  const force = process.env.FORCE_RUN === '1' || process.env.FORCE_RUN === 'true';
  if (!force) {
    if (!isTaipeiWeekday()) { console.log('Not a Taipei weekday, skipping run.'); return; }
    const day = new Date(Date.now() + 8 * 3600 * 1000).getUTCDate();
    if (day < 5 || day > 15) { console.log('Outside day 5-15 window (day=' + day + '), skipping run.'); return; }
  }

  const { twse, tpex } = await fetchStockList();
  console.log('stock universe: twse=' + twse.length + ' tpex=' + tpex.length);

  const twseCache = await build('twse', twse);
  const tpexCache = await build('tpex', tpex);

  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(path.join(DATA_DIR, 'revenue-twse.json'), JSON.stringify(twseCache));
  fs.writeFileSync(path.join(DATA_DIR, 'revenue-tpex.json'), JSON.stringify(tpexCache));
  console.log('Done.');
}

main().catch(function (e) { console.error(e); process.exit(1); });
