
from app.db import Base, engine, SessionLocal
from app.models import Supplier, Product, InventorySnapshot, Sale, Fee, FeeType
from app.services.metrics import recompute_metrics_for_month
from datetime import datetime

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Suppliers
    supp = db.query(Supplier).filter_by(name="Demo Distributor").one_or_none()
    if not supp:
        supp = Supplier(name="Demo Distributor")
        db.add(supp)
        db.commit()
        db.refresh(supp)

    # Products
    def upsert(sku, asin, title, cost):
        p = db.query(Product).filter_by(sku=sku).one_or_none()
        if not p:
            p = Product(sku=sku, asin=asin, title=title, supplier_id=supp.id, cost=cost)
            db.add(p)
        else:
            p.asin = asin; p.title = title; p.cost = cost; p.supplier_id = supp.id
        db.commit(); db.refresh(p)
        return p

    p1 = upsert("SKU-AAA", "B000AAA", "Sample Product AAA", 10.50)
    p2 = upsert("SKU-BBB", "B000BBB", "Sample Product BBB", 18.00)
    p3 = upsert("SKU-CCC", "B000CCC", "Sample Product CCC", 7.25)

    # Inventory snapshots
    now = datetime.utcnow()
    db.add_all([
        InventorySnapshot(product_id=p1.id, qty=120, fc="FBA", at=now),
        InventorySnapshot(product_id=p2.id, qty=45, fc="FBA", at=now),
        InventorySnapshot(product_id=p3.id, qty=0, fc="FBA", at=now),
    ])

    # Sales
    db.add_all([
        Sale(product_id=p1.id, units=3, price=24.99, at=now),
        Sale(product_id=p2.id, units=1, price=39.00, at=now),
        Sale(product_id=p1.id, units=2, price=24.99, at=now),
    ])

    # Fees
    db.add_all([
        Fee(product_id=p1.id, type=FeeType.FBA, amount=7.12, at=now),
        Fee(product_id=p1.id, type=FeeType.REFERRAL, amount=3.75, at=now),
        Fee(product_id=p2.id, type=FeeType.FBA, amount=6.90, at=now),
        Fee(product_id=p2.id, type=FeeType.REFERRAL, amount=5.85, at=now),
    ])

    db.commit()

    # Metrics for current month
    recompute_metrics_for_month(db, now.year, now.month)
    db.close()
    print("Seeded demo data.")

if __name__ == "__main__":
    main()
