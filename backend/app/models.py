from sqlalchemy import Column, String, Integer, BigInteger, Float, UniqueConstraint, Index
from .database import Base


class Stock(Base):
        __tablename__ = "stocks"
        id = Column(Integer, primary_key=True, autoincrement=True)
        stock_id = Column(String(10), nullable=False, unique=True, index=True)
        stock_name = Column(String(50), nullable=False)
        market = Column(String(10), nullable=False)    # TWSE / TPEx
    industry = Column(String(50), nullable=True)   # 產業別
    close_price = Column(Float, nullable=True)     # 收盤價
    change = Column(Float, nullable=True)          # 漲跌 (price change)
    change_pct = Column(Float, nullable=True)      # 漲跌幅 %
    price_date = Column(String(10), nullable=True) # 股價日期 e.g. 2026-06-24
    updated_at = Column(String(30), nullable=True)


class MonthRevenue(Base):
        __tablename__ = "month_revenues"
        id = Column(Integer, primary_key=True, autoincrement=True)
        stock_id = Column(String(10), nullable=False, index=True)
        year = Column(Integer, nullable=False)
        month = Column(Integer, nullable=False)
        revenue = Column(BigInteger, nullable=False)          # 當月營收 (千元)
    revenue_mom = Column(Float, nullable=True)            # 月增率 %
    revenue_yoy = Column(Float, nullable=True)            # 年增率 %
    cumulative_revenue = Column(BigInteger, nullable=True) # 累計營收 (千元)
    cumulative_yoy = Column(Float, nullable=True)          # 累計年增率 %

    __table_args__ = (
                UniqueConstraint("stock_id", "year", "month", name="uq_stock_ym"),
                Index("ix_stock_ym", "stock_id", "year", "month"),
    )
