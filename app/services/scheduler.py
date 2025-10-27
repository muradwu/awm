
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..services.metrics import recompute_metrics_for_month
from ..spapi.reports import fetch_reports_stub
from ..spapi.parser import parse_inventory_csv, parse_orders_csv, parse_settlement_csv
from ..services.ingest import ingest_inventory_snapshots, ingest_sales, ingest_fees

scheduler = BackgroundScheduler(timezone="UTC")

def daily_job():
    db: Session = SessionLocal()
    try:
        # 1) Fetch latest CSVs (stubbed) and parse
        inv_csv, orders_csv, sett_csv = fetch_reports_stub()

        inv_rows = parse_inventory_csv(inv_csv)
        order_rows = parse_orders_csv(orders_csv)
        fee_rows = parse_settlement_csv(sett_csv)

        # 2) Ingest
        ingest_inventory_snapshots(db, inv_rows)
        ingest_sales(db, order_rows)
        ingest_fees(db, fee_rows)

        # 3) Recompute metrics for current month
        now = datetime.utcnow()
        recompute_metrics_for_month(db, now.year, now.month)
    finally:
        db.close()

def start_scheduler():
    from ..config import settings
    # run once at startup
    daily_job()
    # schedule daily at 03:00 UTC (configurable via cron if needed)
    scheduler.add_job(daily_job, "cron", hour=3, minute=0)
    scheduler.start()
