// functions/api/sync.js - POST /api/sync?full=false
export async function onRequestPost({ request, env }) {
  const url = new URL(request.url);
  const full = url.searchParams.get('full') === 'true';
  const TOKEN = env.FINMIND_TOKEN || '';
  try {
    // 取得上市股票產業對照表
    const twseIndRes = await fetch('https://openapi.twse.com.tw/v1/opendata/t187ap03_L');
    const twseIndData = await twseIndRes.json();
    const indMap = {};
    for (const x of twseIndData) {
      const c = String(x['公司代號']||'').trim();
      const i = String(x['產業類別']||'').trim();
      if (c) indMap[c] = i;
    }

    // 取得上市股票收盤資料
    const twseRes = await fetch('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL');
    const twseStocks = await twseRes.json();
    const now = new Date().toISOString();
    const stocks = [];

    for (const s of twseStocks) {
      const id = String(s.Code||'').trim();
      const name = String(s.Name||'').trim();
      if (!id || !name) continue;
      const cl = parseFloat(s.ClosingPrice) || null;
      const ch = parseFloat(s.Change) || null;
      // 修正：漲跌幅 = 漲跌額 / 前日收盤 = ch / (cl - ch)，避免除以零
      const prevClose = cl != null && ch != null ? cl - ch : null;
      const pct = (prevClose && prevClose !== 0) ? Math.round(ch / prevClose * 10000) / 100 : null;
      stocks.push({ id, name, market: 'TWSE', ind: indMap[id] || null, cl, ch, pct, now });
    }

    // 取得上櫃股票收盤資料
    const tpexRes = await fetch('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes');
    const tpexStocks = await tpexRes.json();
    for (const s of tpexStocks) {
      const id = String(s.SecuritiesCompanyCode||'').trim();
      const name = String(s.CompanyName||'').trim();
      if (!id || !name) continue;
      const cl = parseFloat(s.Close) || null;
      const ch = parseFloat(s.Change) || null;
      const prevClose = cl != null && ch != null ? cl - ch : null;
      const pct = (prevClose && prevClose !== 0) ? Math.round(ch / prevClose * 10000) / 100 : null;
      stocks.push({ id, name, market: 'TPEx', ind: null, cl, ch, pct, now });
    }

    // 批次寫入資料庫
    for (let i = 0; i < stocks.length; i += 100) {
      const b = stocks.slice(i, i + 100);
      await env.DB.batch(b.map(s => env.DB.prepare(
        'INSERT INTO stocks(stock_id,stock_name,market,industry,close_price,change,change_pct,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(stock_id) DO UPDATE SET stock_name=excluded.stock_name,market=excluded.market,industry=excluded.industry,close_price=excluded.close_price,change=excluded.change,change_pct=excluded.change_pct,updated_at=excluded.updated_at'
      ).bind(s.id, s.name, s.market, s.ind, s.cl, s.ch, s.pct, s.now)));
    }

    // 同步月營收資料（使用 FinMind API）
    if (TOKEN) {
      const today = new Date();
      const yr = full
        ? 2010
        : (today.getMonth() >= 3 ? today.getFullYear() - 1 : today.getFullYear() - 2);
      const ids = full
        ? stocks.filter(s => s.id.length === 4 && s.id[0] >= '1' && s.id[0] <= '9').map(s => s.id).slice(0, 30)
        : ['2330','2317','2454','2382','2308','2303','3711','2412','1301','1303','2881','2882','2886','2891','5880'];

      for (const sid of ids) {
        try {
          const r = await fetch(`https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id=${sid}&start_date=${yr}-01-01&token=${TOKEN}`);
          const d = await r.json();
          if (d.status !== 200 || !d.data?.length) continue;
          for (let i = 0; i < d.data.length; i += 50) {
            await env.DB.batch(d.data.slice(i, i + 50).map(x => env.DB.prepare(
              'INSERT INTO month_revenues(stock_id,year,month,revenue,revenue_mom,revenue_yoy,cumulative_revenue,cumulative_yoy) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(stock_id,year,month) DO UPDATE SET revenue=excluded.revenue,revenue_mom=excluded.revenue_mom,revenue_yoy=excluded.revenue_yoy,cumulative_revenue=excluded.cumulative_revenue,cumulative_yoy=excluded.cumulative_yoy'
            ).bind(
              sid,
              parseInt(x.revenue_year),
              parseInt(x.revenue_month),
              parseInt(x.revenue),
              parseFloat(x.revenue_month_compare_last_month_increase) || null,
              parseFloat(x.revenue_month_compare_last_year_increase) || null,
              parseInt(x.cumulative_revenue) || null,
              parseFloat(x.cumulative_revenue_compare_last_year_increase) || null
            )));
          }
        } catch(e) {}
      }
    }

    return Response.json({ status: 'ok', stocks: stocks.length });
  } catch(e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}
