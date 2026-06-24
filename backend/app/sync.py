"""
Data synchronisation helpers.
Sources:
  - TWSE OpenAPI  (listed stocks + close price + change + industry)
  - TPEx OpenAPI  (OTC stocks + close price + change + industry)
  - FinMind API   (TaiwanStockMonthRevenue)

TWSE STOCK_DAY_ALL fields:
    Code, Name, TradeVolume, TradeValue, OpeningPrice,
    HighestPrice, LowestPrice, ClosingPrice, Change, Transaction

TPEx tpex_mainboard_daily_close_quotes fields:
    SecuritiesCompanyCode, CompanyName, Close, Change, ...
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import engine, init_db
from .models import Stock, MonthRevenue

logger = logging.getLogger(__name__)

FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"

# ---------------------------------------------------------------------------
# TWSE industry code -> Chinese name
# ---------------------------------------------------------------------------
TWSE_INDUSTRY_MAP: Dict[str, str] = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學生技醫療", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業", "16": "觀光餐旅",
    "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業",
    "33": "農業科技業", "34": "電子商務", "35": "綠能環保", "36": "數位雲端",
    "37": "運動休閒", "38": "居家生活", "80": "管理股票", "91": "存託憑證",
}

# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _parse_float(raw: object) -> Optional[float]:
    """Parse price string like '2,255.00' or '+15.00' or '--' to float."""
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if not s or s in ("--", "-", "N/A", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _calc_change_pct(close: Optional[float], change: Optional[float]) -> Optional[float]:
    """change_pct = change / (close - change) * 100, rounded to 2dp."""
    if close is None or change is None or change == 0:
        return None
    prev = close - change
    if prev == 0:
        return None
    return round(change / abs(prev) * 100, 2)

def _today_str() -> str:
    """Return today's date as YYYY-MM-DD in Taiwan time (UTC+8)."""
    from datetime import timezone, timedelta
    tz_tw = timezone(timedelta(hours=8))
    return datetime.now(tz_tw).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Industry mapping helpers
# ---------------------------------------------------------------------------

async def _fetch_twse_industry_map(client: httpx.AsyncClient) -> Dict[str, str]:
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    try:
        r = await client.get(url, timeout=30)
        r.raise_for_status()
        result: Dict[str, str] = {}
        for item in r.json():
            code = str(item.get("公司代號", "") or "").strip()
            raw = str(item.get("產業別", "") or item.get("IndustryCode", "")).strip()
            if not code:
                continue
            if raw and raw.lstrip("0123456789") == "":
                industry = TWSE_INDUSTRY_MAP.get(raw.zfill(2), raw)
            else:
                industry = raw
            if industry:
                result[code] = industry
        logger.info("TWSE industry map: %d entries", len(result))
        return result
    except Exception as e:
        logger.warning("TWSE industry map error: %s", e)
        return {}

async def _fetch_tpex_industry_map(client: httpx.AsyncClient) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for url in [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t21sc03",
    ]:
        try:
            r = await client.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                continue
            for item in data:
                code = str(
                    item.get("SecuritiesCompanyCode", "")
                    or item.get("公司代號", "") or item.get("代號", "")
                ).strip()
                ind = str(
                    item.get("IndustryCode", "")
                    or item.get("產業別", "") or item.get("產業類別", "")
                ).strip()
                if code and ind:
                    result[code] = ind
            if result:
                logger.info("TPEx industry map: %d entries", len(result))
                return result
        except Exception as e:
            logger.warning("TPEx industry endpoint %s error: %s", url, e)
    return result

# ---------------------------------------------------------------------------
# Stock list helpers
# ---------------------------------------------------------------------------

async def _fetch_twse_stocks(
    client: httpx.AsyncClient,
    industry_map: Dict[str, str],
) -> List[Dict]:
    """
    TWSE STOCK_DAY_ALL: fetch close price, change, and derive price_date.
    """
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        r = await client.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Try to get the trading date from first record or use today
        price_date = _today_str()
        if data and isinstance(data, list) and len(data) > 0:
            first = data[0]
            # TWSE may return Date field like "20260624"
            raw_date = str(first.get("Date", "") or "").strip()
            if len(raw_date) == 8 and raw_date.isdigit():
                price_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        stocks = []
        for item in data:
            code = item.get("Code", "").strip()
            name = item.get("Name", "").strip()
            if not code or not name:
                continue
            close = _parse_float(item.get("ClosingPrice"))
            change = _parse_float(item.get("Change"))
            change_pct = _calc_change_pct(close, change)
            stocks.append({
                "stock_id": code,
                "stock_name": name,
                "market": "TWSE",
                "industry": industry_map.get(code),
                "close_price": close,
                "change": change,
                "change_pct": change_pct,
                "price_date": price_date,
            })
        logger.info("TWSE: fetched %d stocks, price_date=%s", len(stocks), price_date)
        return stocks
    except Exception as e:
        logger.error("TWSE fetch error: %s", e)
        return []

async def _fetch_tpex_stocks(
    client: httpx.AsyncClient,
    industry_map: Dict[str, str],
) -> List[Dict]:
    """
    TPEx tpex_mainboard_daily_close_quotes: fetch close price, change, derive price_date.
    """
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    try:
        r = await client.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        price_date = _today_str()
        if data and isinstance(data, list) and len(data) > 0:
            first = data[0]
            # TPEx may return Date like "114/06/24" (ROC year) or "2026/06/24"
            raw_date = str(first.get("Date", "") or first.get("date", "") or "").strip()
            if raw_date:
                parts = raw_date.replace("-", "/").split("/")
                if len(parts) == 3:
                    y, m, d = parts[0], parts[1], parts[2]
                    if len(y) <= 3:  # ROC year
                        y = str(int(y) + 1911)
                    price_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        stocks = []
        for item in data:
            code = item.get("SecuritiesCompanyCode", "").strip()
            name = item.get("CompanyName", "").strip()
            if not code or not name:
                continue
            close = _parse_float(item.get("Close"))
            change = _parse_float(item.get("Change"))
            change_pct = _calc_change_pct(close, change)
            industry = (
                industry_map.get(code)
                or str(item.get("IndustryCode", "") or item.get("產業別", "")).strip()
                or None
            )
            stocks.append({
                "stock_id": code,
                "stock_name": name,
                "market": "TPEx",
                "industry": industry,
                "close_price": close,
                "change": change,
                "change_pct": change_pct,
                "price_date": price_date,
            })
        logger.info("TPEx: fetched %d stocks, price_date=%s", len(stocks), price_date)
        return stocks
    except Exception as e:
        logger.error("TPEx fetch error: %s", e)
        return []

# ---------------------------------------------------------------------------
# FinMind revenue helper
# ---------------------------------------------------------------------------

async def _fetch_finmind_revenue(
    client: httpx.AsyncClient, stock_id: str, start_date: str
) -> List[Dict]:
    params = {
        "dataset": "TaiwanStockMonthRevenue",
        "data_id": stock_id,
        "start_date": start_date,
        "token": FINMIND_TOKEN,
    }
    try:
        r = await client.get(FINMIND_API, params=params, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if payload.get("status") != 200:
            logger.warning("FinMind %s: status=%s msg=%s",
                           stock_id, payload.get("status"), payload.get("msg"))
            return []
        return payload.get("data", [])
    except Exception as e:
        logger.error("FinMind %s error: %s", stock_id, e)
        return []

# ---------------------------------------------------------------------------
# Database upsert helpers
# ---------------------------------------------------------------------------

async def _upsert_stocks(stocks: List[Dict]) -> None:
    if not stocks:
        return
    now = datetime.utcnow().isoformat()
    rows = [
        {
            "stock_id": s["stock_id"],
            "stock_name": s["stock_name"],
            "market": s["market"],
            "industry": s.get("industry"),
            "close_price": s.get("close_price"),
            "change": s.get("change"),
            "change_pct": s.get("change_pct"),
            "price_date": s.get("price_date"),
            "updated_at": now,
        }
        for s in stocks
    ]
    stmt = sqlite_insert(Stock).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id"],
        set_={
            "stock_name": stmt.excluded.stock_name,
            "market": stmt.excluded.market,
            "industry": stmt.excluded.industry,
            "close_price": stmt.excluded.close_price,
            "change": stmt.excluded.change,
            "change_pct": stmt.excluded.change_pct,
            "price_date": stmt.excluded.price_date,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    async with engine.begin() as conn:
        await conn.execute(stmt)
    logger.info("Upserted %d stocks", len(rows))

def _calc_pct(new_val: Optional[int], old_val: Optional[int]) -> Optional[float]:
    if not new_val or not old_val:
        return None
    return round((new_val - old_val) / abs(old_val) * 100, 2)

async def _upsert_revenues(rows: List[Dict]) -> None:
    if not rows:
        return
    rev_map: Dict[Tuple[int, int], int] = {}
    for r in rows:
        y = int(r.get("revenue_year", 0) or 0)
        m = int(r.get("revenue_month", 0) or 0)
        if y and m:
            rev_map[(y, m)] = int(r.get("revenue", 0) or 0)

    db_rows = []
    for r in rows:
        try:
            sid = str(r.get("stock_id", "")).strip()
            y = int(r.get("revenue_year", 0) or 0)
            m = int(r.get("revenue_month", 0) or 0)
            if not sid or not y or not m:
                continue
            revenue = int(r.get("revenue", 0) or 0)
            revenue_mom = _calc_pct(revenue, rev_map.get((y, m - 1) if m > 1 else (y - 1, 12)))
            revenue_yoy = _calc_pct(revenue, rev_map.get((y - 1, m)))
            cum = sum(rev_map.get((y, mo), 0) for mo in range(1, m + 1) if (y, mo) in rev_map)
            cum_prev = sum(rev_map.get((y - 1, mo), 0) for mo in range(1, m + 1) if (y - 1, mo) in rev_map)
            db_rows.append({
                "stock_id": sid, "year": y, "month": m, "revenue": revenue,
                "revenue_mom": revenue_mom, "revenue_yoy": revenue_yoy,
                "cumulative_revenue": cum or None,
                "cumulative_yoy": _calc_pct(cum or None, cum_prev or None),
            })
        except Exception as e:
            logger.warning("Revenue row error: %s | row=%s", e, r)

    if not db_rows:
        return
    stmt = sqlite_insert(MonthRevenue).values(db_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "year", "month"],
        set_={
            "revenue": stmt.excluded.revenue,
            "revenue_mom": stmt.excluded.revenue_mom,
            "revenue_yoy": stmt.excluded.revenue_yoy,
            "cumulative_revenue": stmt.excluded.cumulative_revenue,
            "cumulative_yoy": stmt.excluded.cumulative_yoy,
        },
    )
    async with engine.begin() as conn:
        await conn.execute(stmt)
    logger.info("Upserted %d revenue rows for %s", len(db_rows), db_rows[0]["stock_id"])

# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

async def run_sync(full: bool = False) -> None:
    logger.info("run_sync started (full=%s)", full)
    await init_db()

    async with httpx.AsyncClient(timeout=60) as client:
        twse_ind, tpex_ind = await asyncio.gather(
            _fetch_twse_industry_map(client),
            _fetch_tpex_industry_map(client),
        )
        twse_stocks, tpex_stocks = await asyncio.gather(
            _fetch_twse_stocks(client, twse_ind),
            _fetch_tpex_stocks(client, tpex_ind),
        )
        all_stocks = twse_stocks + tpex_stocks
        await _upsert_stocks(all_stocks)

        if not all_stocks:
            logger.warning("No stocks fetched; skipping revenue sync")
            return

        if full:
            stock_ids = [s["stock_id"] for s in all_stocks]
            start_date = "2010-01-01"
        else:
            priority_ids = [
                "2330", "2317", "2454", "2382", "2308",
                "2303", "3711", "2412", "1301", "1303",
                "2881", "2882", "2886", "2891", "5880",
            ]
            stock_ids = priority_ids
            today = date.today()
            start_date = "{}-01-01".format(
                today.year - 1 if today.month >= 4 else today.year - 2
            )

        logger.info("Fetching revenue for %d stocks from %s", len(stock_ids), start_date)
        sem = asyncio.Semaphore(3)

        async def fetch_and_store(sid: str) -> None:
            async with sem:
                rows = await _fetch_finmind_revenue(client, sid, start_date)
                if rows:
                    logger.info("  %s: %d revenue rows", sid, len(rows))
                    await _upsert_revenues(rows)
                await asyncio.sleep(0.3)

        await asyncio.gather(*[fetch_and_store(sid) for sid in stock_ids])

    logger.info("run_sync completed")
