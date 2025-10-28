from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models import SalesRecord, PurchaseOrderItem

def list_sales(db: Session, month: Optional[int] = None, year: Optional[int] = None) -> List[dict]:
    q = db.query(SalesRecord)
    if year:
        q = q.filter(SalesRecord.year == year)
    if month:
        q = q.filter(SalesRecord.month == month)
    q = q.order_by(SalesRecord.date.desc(), SalesRecord.id.desc())

    out = []
    for s in q.all():
        out.append({
            "id": s.id,
            "external_id": s.external_id,
            "date": s.date.isoformat(),
            "asin": s.asin,
            "description": s.description,
            "amount": s.amount,
            "type": s.type,
            "party": s.party,
            "month": s.month,
            "units_sold": s.units_sold,
            "cogs_per_unit": s.cogs_per_unit,
            "fba_fee_per_unit": s.fba_fee_per_unit,
            "amazon_fee_per_unit": s.amazon_fee_per_unit,
            "after_fees_per_unit": s.after_fees_per_unit,
            "net_per_unit": s.net_per_unit,
            "pay_supplier_per_unit": s.pay_supplier_per_unit,
            "prep_per_unit": s.prep_per_unit,
            "ship_to_amz_per_unit": s.ship_to_amz_per_unit,
            "po_id": s.po_id,
            "po_item_id": s.po_item_id
        })
    return out

def upsert_sales(db: Session, records: List[Dict]) -> int:
    """
    Простая загрузка из Sellerboard/Amazon (JSON).
    Ожидаемый формат record:
    {
      "external_id": "...", "date": "YYYY-MM-DD", "asin": "...",
      "description": "...", "amount": 0, "type": "Order", "party": "...",
      "units_sold": 1, "cogs_per_unit": 0, "fba_fee_per_unit": 0, "amazon_fee_per_unit": 0,
      "after_fees_per_unit": 0, "net_per_unit": 0, "pay_supplier_per_unit": 0,
      "prep_per_unit": 0, "ship_to_amz_per_unit": 0, "po_item_id": 123 (optional)
    }
    """
    cnt = 0
    for r in records:
        ext = (r.get("external_id") or "").strip()
        date_str = r.get("date")
        try:
            dt = datetime.fromisoformat(date_str)
        except:
            dt = datetime.utcnow()

        sr = db.query(SalesRecord).filter_by(external_id=ext).one_or_none()
        if not sr:
            sr = SalesRecord(external_id=ext)
            db.add(sr)

        sr.date = dt
        sr.asin = r.get("asin")
        sr.description = r.get("description")
        sr.amount = float(r.get("amount") or 0)
        sr.type = r.get("type")
        sr.party = r.get("party")
        sr.month = int(r.get("month") or dt.month)
        sr.year = int(r.get("year") or dt.year)

        sr.units_sold = int(r.get("units_sold") or 0)
        sr.cogs_per_unit = float(r.get("cogs_per_unit") or 0)
        sr.fba_fee_per_unit = float(r.get("fba_fee_per_unit") or 0)
        sr.amazon_fee_per_unit = float(r.get("amazon_fee_per_unit") or 0)
        sr.after_fees_per_unit = float(r.get("after_fees_per_unit") or 0)
        sr.net_per_unit = float(r.get("net_per_unit") or 0)
        sr.pay_supplier_per_unit = float(r.get("pay_supplier_per_unit") or 0)
        sr.prep_per_unit = float(r.get("prep_per_unit") or 0)
        sr.ship_to_amz_per_unit = float(r.get("ship_to_amz_per_unit") or 0)

        po_item_id = r.get("po_item_id")
        if po_item_id:
            sr.po_item_id = int(po_item_id)
            # при желании подтянем po_id
            poi = db.get(PurchaseOrderItem, int(po_item_id))
            if poi:
                sr.po_id = poi.po_id

        cnt += 1

    db.commit()
    return cnt
