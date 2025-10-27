
from sqlalchemy.orm import Session
from typing import Iterable
from datetime import datetime
from ..models import Product, Supplier, InventorySnapshot, Sale, Fee, FeeType

def upsert_supplier(db: Session, name: str) -> Supplier:
    s = db.query(Supplier).filter_by(name=name).one_or_none()
    if not s:
        s = Supplier(name=name)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s

def upsert_product(db: Session, sku: str, asin: str, title: str, supplier: Supplier, cost: float) -> Product:
    p = db.query(Product).filter_by(sku=sku).one_or_none()
    if not p:
        p = Product(sku=sku, asin=asin, title=title, supplier_id=supplier.id, cost=cost)
        db.add(p)
    else:
        p.asin = asin
        p.title = title
        p.supplier_id = supplier.id
        p.cost = cost
    db.commit()
    db.refresh(p)
    return p

def ingest_inventory_snapshots(db: Session, rows: Iterable[dict]) -> None:
    for r in rows:
        # expected keys: sku, qty, fc, at
        sku = r["sku"]; qty = int(r["qty"]); fc = r.get("fc", "FBA"); at = r.get("at") or datetime.utcnow()
        p = db.query(Product).filter_by(sku=sku).one_or_none()
        if not p:
            # Skip unknown SKU for now
            continue
        db.add(InventorySnapshot(product_id=p.id, qty=qty, fc=fc, at=at))
    db.commit()

def ingest_sales(db: Session, rows: Iterable[dict]) -> None:
    for r in rows:
        sku = r["sku"]; units = int(r["units"]); price = float(r["price"]); at = r.get("at") or datetime.utcnow()
        p = db.query(Product).filter_by(sku=sku).one_or_none()
        if not p: continue
        db.add(Sale(product_id=p.id, units=units, price=price, at=at))
    db.commit()

def ingest_fees(db: Session, rows: Iterable[dict]) -> None:
    for r in rows:
        sku = r["sku"]; ftype = FeeType(r.get("type", "OTHER")); amount = float(r["amount"]); at = r.get("at") or datetime.utcnow()
        p = db.query(Product).filter_by(sku=sku).one_or_none()
        if not p: continue
        db.add(Fee(product_id=p.id, type=ftype, amount=amount, at=at))
    db.commit()
