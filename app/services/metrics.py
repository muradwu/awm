
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from datetime import datetime
from ..models import Product, Sale, Fee, MetricSnapshot, FeeType

def compute_month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")

def recompute_metrics_for_month(db: Session, year: int, month: int) -> None:
    # Aggregate revenue, cogs (cost * units), fees per product for given month
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    period = start.strftime("%Y-%m")

    products = db.scalars(select(Product)).all()
    for p in products:
        # revenue
        revenue = db.scalar(
            select(func.coalesce(func.sum(Sale.price * Sale.units), 0.0))
            .where(Sale.product_id == p.id, Sale.at >= start, Sale.at < end)
        ) or 0.0

        units = db.scalar(
            select(func.coalesce(func.sum(Sale.units), 0))
            .where(Sale.product_id == p.id, Sale.at >= start, Sale.at < end)
        ) or 0

        cogs = (p.cost or 0.0) * units

        fees = db.scalar(
            select(func.coalesce(func.sum(Fee.amount), 0.0))
            .where(Fee.product_id == p.id, Fee.at >= start, Fee.at < end)
        ) or 0.0

        profit = revenue - cogs - fees
        roi = (profit / cogs * 100.0) if cogs > 0 else 0.0

        # upsert MetricSnapshot
        ms = db.query(MetricSnapshot).filter_by(product_id=p.id, period=period).one_or_none()
        if not ms:
            ms = MetricSnapshot(product_id=p.id, period=period)
            db.add(ms)
        ms.revenue = float(revenue)
        ms.cogs = float(cogs)
        ms.fees = float(fees)
        ms.profit = float(profit)
        ms.roi = float(roi)
    db.commit()
