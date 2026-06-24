"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, distinct, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db
from .models import Stock, MonthRevenue
from .sync import run_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Industry-stock SQL filter (no Python-side filtering needed)
# 4-digit code, first digit 1-9
# ---------------------------------------------------------------------------
def _industry_filter():
    return (
        func.length(Stock.stock_id) == 4,
        or_(
            Stock.stock_id.like("1%"), Stock.stock_id.like("2%"),
            Stock.stock_id.like("3%"), Stock.stock_id.like("4%"),
            Stock.stock_id.like("5%"), Stock.stock_id.like("6%"),
            Stock.stock_id.like("7%"), Stock.stock_id.like("8%"),
            Stock.stock_id.like("9%"),
        ),
    )


async def _safe_sync(full: bool = False) -> None:
    try:
        await run_sync(full=full)
    except Exception as exc:
        logger.error("run_sync error: %s", exc, exc_info=True)


async def _daily_scheduler() -> None:
    while True:
        try:
            now = datetime.now()
            secs_today = (18 * 60 + 30) * 60
            secs_now = (now.hour * 60 + now.minute) * 60 + now.second
            wait = secs_today - secs_now
            if wait <= 0:
                wait += 86400
            logger.info("Daily sync scheduled in %.0f minutes", wait / 60)
            await asyncio.sleep(wait)
            await _safe_sync(full=False)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Scheduler loop error: %s", exc)
            await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialised")
    asyncio.create_task(_safe_sync(full=False))
    sched_task = asyncio.create_task(_daily_scheduler())
    yield
    sched_task.cancel()
    try:
        await sched_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutdown complete")


app = FastAPI(title="Taiwan Stock Revenue API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _stock_dict(s: Stock) -> dict:
    return {
        "stock_id": s.stock_id,
        "stock_name": s.stock_name,
        "market": s.market,
        "industry": s.industry,
        "close_price": s.close_price,
        "change": s.change,
        "change_pct": s.change_pct,
        "price_date": s.price_date,
        "updated_at": s.updated_at,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/stocks")
async def list_stocks(
    q: str = Query(default=""),
    market: str = Query(default=""),
    industry: str = Query(default=""),
    skip: int = 0,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
):
    len_filter, first_digit_filter = _industry_filter()
    stmt = select(Stock).where(len_filter).where(first_digit_filter)

    if q:
        stmt = stmt.where(
            Stock.stock_id.ilike("%" + q + "%") |
            Stock.stock_name.ilike("%" + q + "%")
        )
    if market:
        stmt = stmt.where(Stock.market == market)
    if industry:
        stmt = stmt.where(Stock.industry == industry)

    stmt = stmt.order_by(Stock.stock_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return [_stock_dict(s) for s in result.scalars().all()]


@app.get("/api/industries")
async def list_industries(
    market: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    len_filter, first_digit_filter = _industry_filter()
    stmt = (
        select(distinct(Stock.industry))
        .where(Stock.industry.isnot(None))
        .where(len_filter)
        .where(first_digit_filter)
    )
    if market:
        stmt = stmt.where(Stock.market == market)
    result = await db.execute(stmt)
    return sorted([r for r in result.scalars().all() if r and r.strip()])


@app.get("/api/stocks/count")
async def count_stocks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count()).select_from(Stock))
    return {"count": result.scalar()}


@app.get("/api/stocks/{stock_id}")
async def get_stock(stock_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Stock).where(Stock.stock_id == stock_id))
    stock = result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    return _stock_dict(stock)


@app.get("/api/revenue/{stock_id}")
async def get_revenue(
    stock_id: str,
    years: int = Query(default=3, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(MonthRevenue)
        .where(MonthRevenue.stock_id == stock_id)
        .order_by(MonthRevenue.year.desc(), MonthRevenue.month.desc())
        .limit(years * 12)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No revenue data found")
    return [
        {
            "year": r.year, "month": r.month, "revenue": r.revenue,
            "revenue_mom": r.revenue_mom, "revenue_yoy": r.revenue_yoy,
            "cumulative_revenue": r.cumulative_revenue,
            "cumulative_yoy": r.cumulative_yoy,
        }
        for r in rows
    ]


@app.post("/api/sync")
async def trigger_sync(full: bool = False):
    asyncio.create_task(_safe_sync(full=full))
    return {"status": "sync started", "full": full}
