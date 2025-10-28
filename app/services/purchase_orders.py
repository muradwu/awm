from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import (
    Supplier,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    LabelingCost,
    POStatus,
)

# -------- helpers --------

def _parse_date(s: Optional[str]) -> datetime:
    """Accepts many common date formats; returns UTC now if empty."""
    if not s:
        return datetime.utcnow()
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        raise ValueError(
            f"Unrecognized date format: {s}. Use YYYY-MM-DD (e.g. 2024-02-14)."
        )

def _to_float(x) -> float:
    """Safely parse numbers like '7,12' or None."""
    if x is None or x == "":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    return float(str(x).replace(",", "."))

# -------- tiny upserts/links --------

def _upsert_supplier(db: Session, name: Optional[str]) -> Optional[Supplier]:
    if not name:
        return None
    s = db.query(Supplier).filter_by(name=name).one_or_none()
    if not s:
        s = Supplier(name=name)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s

def _attach_product(
    db: Session,
    asin: str,
    listing_title: str,
    supplier: Optional[Supplier],
    cost_hint: Optional[float],
) -> Optional[Product]:
    """Find or create Product by ASIN and update minimal fields."""
    p = db.query(Product).filter_by(asin=asin).first()
    if not p:
        p = Product(
            sku=f"AUTO-{asin}",
            asin=asin,
            title=listing_title or asin,
            supplier_id=(supplier.id if supplier else None),
            cost=_to_float(cost_hint),
        )
        db.add(p)
        db.commit()
        db.refresh(p)
    else:
        if listing_title:
            p.title = listing_title
        if supplier:
            p.supplier_id = supplier.id
        if cost_hint and not p.cost:
            p.cost = _to_float(cost_hint)
        db.commit()
    return p

# -------- core API used by endpoints --------

def create_purchase_order(db: Session, payload: dict) -> PurchaseOrder:
    """
    payload = {
        "supplier_name": "...",
        "po_name": "...",
        "invoice_number": "...",
        "order_date": "YYYY-MM-DD" | "MM/DD/YYYY" | "DD.MM.YYYY",
        "sales_tax": 0.0,
        "shipping": 0.0,
        "discount": 0.0,
        "items": [
            {
              "asin": "...", "listing_title": "...", "amazon_link": "...",
              "supplier_mfr_code": "...",
              "quantity": 10, "purchase_price": 7.12,
              "sales_tax": null, "shipping": null, "discount": 0
            }, ...
        ]
    }
    """
    supplier = _upsert_supplier(db, payload.get("supplier_name"))
    po = PurchaseOrder(
        supplier_id=(supplier.id if supplier else None),
        name=payload["po_name"],
        invoice_number=payload.get("invoice_number"),
        order_date=_parse_date(payload.get("order_date")),
        status=POStatus.NEW,
    )
    db.add(po)
    db.commit()
    db.refresh(po)

    subtotal = 0.0
    for row in payload.get("items", []):
        asin = (row.get("asin") or "").strip()
        if not asin:
            raise ValueError("ASIN is required for each item.")
        title = (row.get("listing_title") or "").strip()
        if not title:
            raise ValueError("Listing title is required for each item.")

        p = _attach_product(db, asin, title, supplier, row.get("purchase_price"))

        qty = int(row.get("quantity") or 0)
        if qty <= 0:
            raise ValueError("Quantity must be positive.")
        price = _to_float(row.get("purchase_price"))
        subtotal += qty * price

        item = PurchaseOrderItem(
            po_id=po.id,
            product_id=(p.id if p else None),
            asin=asin,
            listing_title=title,
            amazon_link=row.get("amazon_link"),
            supplier_mfr_code=row.get("supplier_mfr_code"),
            quantity=qty,
            purchase_price=price,
            sales_tax=_to_float(row.get("sales_tax")),
            shipping=_to_float(row.get("shipping")),
            discount=_to_float(row.get("discount")),
        )
        db.add(item)

    po.subtotal = float(subtotal)
    po.sales_tax = _to_float(payload.get("sales_tax"))
    po.shipping = _to_float(payload.get("shipping"))
    po.discount = _to_float(payload.get("discount"))

    db.commit()

    _recalculate_po_totals_and_cogs(db, po.id)
    db.refresh(po)
    return po

def _recalculate_po_totals_and_cogs(db: Session, po_id: int) -> None:
    po = db.get(PurchaseOrder, po_id)
    items: List[PurchaseOrderItem] = db.query(PurchaseOrderItem).filter_by(po_id=po_id).all()
    total_units = sum(i.quantity for i in items) or 1

    # pools to allocate per unit (only remaining parts)
    alloc_tax_pool = po.sales_tax - sum(i.sales_tax for i in items)
    alloc_ship_pool = po.shipping - sum(i.shipping for i in items)
    alloc_disc_pool = po.discount - sum(i.discount for i in items)  # discount will be negative per unit

    for i in items:
        per_unit_tax = (alloc_tax_pool / total_units) if alloc_tax_pool else 0.0
        per_unit_ship = (alloc_ship_pool / total_units) if alloc_ship_pool else 0.0
        per_unit_disc = (alloc_disc_pool / total_units) if alloc_disc_pool else 0.0
        per_unit_disc *= -1.0  # скидка уменьшает себестоимость

        lbl_sum = db.scalar(
            select(func.coalesce(func.sum(LabelingCost.cost_total), 0.0)).where(LabelingCost.po_item_id == i.id)
        ) or 0.0
        per_unit_label = lbl_sum / i.quantity if i.quantity else 0.0

        unit_cogs = (
            float(i.purchase_price)
            + (i.sales_tax / i.quantity if i.quantity else 0.0) + per_unit_tax
            + (i.shipping / i.quantity if i.quantity else 0.0) + per_unit_ship
            + per_unit_label
            + per_unit_disc
        )

        i.unit_cogs = round(unit_cogs, 6)
        i.extended_total = round(i.unit_cogs * i.quantity, 6)

        if i.product_id:
            prod = db.get(Product, i.product_id)
            prod.cost = float(i.unit_cogs)

    po.labeling_total = float(
        db.scalar(
            select(func.coalesce(func.sum(LabelingCost.cost_total), 0.0)).where(
                LabelingCost.po_item_id.in_([x.id for x in items])
            )
        )
        or 0.0
    )
    po.total_expense = float(po.subtotal + po.sales_tax + po.shipping - po.discount + po.labeling_total)

    db.commit()

def add_labeling_cost(db: Session, po_item_id: int, note: Optional[str], cost_total: float) -> LabelingCost:
    lc = LabelingCost(po_item_id=po_item_id, note=note, cost_total=_to_float(cost_total))
    db.add(lc)
    db.commit()
    db.refresh(lc)
    item = db.get(PurchaseOrderItem, po_item_id)
    _recalculate_po_totals_and_cogs(db, item.po_id)
    return lc

def list_purchase_orders(db: Session):
    pos = db.query(PurchaseOrder).order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).all()
    # отдаём лёгкий словарь для UI
    out = []
    for p in pos:
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "supplier": (p.supplier.name if p.supplier else None),
                "order_date": p.order_date.isoformat() if p.order_date else None,
                "status": p.status.value,
                "subtotal": p.subtotal,
                "sales_tax": p.sales_tax,
                "shipping": p.shipping,
                "discount": p.discount,
                "labeling_total": p.labeling_total,
                "total_expense": p.total_expense,
            }
        )
    return out

def get_po_with_items(db: Session, po_id: int) -> PurchaseOrder:
    return db.query(PurchaseOrder).filter_by(id=po_id).one()

def set_po_status(db: Session, po_id: int, status: str) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    po.status = POStatus(status)
    db.commit()
    db.refresh(po)
    return po
