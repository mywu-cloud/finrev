// functions/api/revenue/[ticker].js
// GET /api/revenue/:ticker?years=3
export async function onRequestGet({ request, env, params }) {
  const ticker = params.ticker;
  const url = new URL(request.url);
  const years = Math.min(parseInt(url.searchParams.get('years') || '3', 10), 10);
  // Fetch extra year for yoy calculation
  const limit = (years + 1) * 12;

  const sql = `SELECT year, month, revenue FROM month_revenues WHERE stock_id = ? ORDER BY year DESC, month DESC LIMIT ?`;

  try {
    const { results } = await env.DB.prepare(sql).bind(ticker, limit).all();
    if (results.length === 0) {
      return Response.json({ detail: 'No revenue data found' }, { status: 404 });
    }

    // Sort ascending for calculation
    const sorted = [...results].sort((a, b) => (a.year * 12 + a.month) - (b.year * 12 + b.month));

    // Build lookup map
    const map = {};
    for (const r of sorted) map[`${r.year}-${r.month}`] = r.revenue;

    // Calculate mom/yoy for each record
    const withCalc = sorted.map(r => {
      // Previous month
      const prevYear = r.month === 1 ? r.year - 1 : r.year;
      const prevMonth = r.month === 1 ? 12 : r.month - 1;
      const prevRev = map[`${prevYear}-${prevMonth}`];
      const mom = (prevRev != null && prevRev !== 0)
        ? Math.round((r.revenue - prevRev) / prevRev * 10000) / 100
        : null;

      // Same month last year
      const lastYearRev = map[`${r.year - 1}-${r.month}`];
      const yoy = (lastYearRev != null && lastYearRev !== 0)
        ? Math.round((r.revenue - lastYearRev) / lastYearRev * 10000) / 100
        : null;

      return {
        year: r.year,
        month: r.month,
        revenue: r.revenue,
        revenue_mom: mom,
        revenue_yoy: yoy,
        cumulative_revenue: null,
        cumulative_yoy: null
      };
    });

    // Return only requested years, descending
    const output = withCalc.reverse().slice(0, years * 12);
    return Response.json(output);
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}
