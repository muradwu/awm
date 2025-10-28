from sqlalchemy.orm import Session
from sqlalchemy import select, func
from datetime import datetime
from ..models import (
    Supplier, Product,
    PurchaseOrder, PurchaseOrderItem, LabelingCost, POStatus
)

def _upsert_supplier(db: Session, name: str | None) -> Supplier | None:
    if not name:
        return None
    s = db.query(Supplier).filter_by(name=name).one_or_none()
    if not s:
        s = Supplier(name=name)
        db.add(s); db.commit(); db.refresh(s)
    return s

def _attach_product(db: Session, asin: str, listing_title: str, supplier: Supplier | None, cost_hint: float | None) -> Product | None:
    # Пробуем найти продукт по ASIN; SKU может быть разным, поэтому в MVP используем ASIN
    p = db.query(Product).filter_by(asin=asin).first()
    if not p:
        # создадим "скелет" (SKU можно заполнить позже)
        p = Product(sku=f"AUTO-{asin}", asin=asin, title=listing_title, supplier_id=(supplier.id if supplier else None), cost=(cost_hint or 0.0))
        db.add(p); db.commit(); db.refresh(p)
    else:
        # обновим заголовок и привязку к поставщику при необходимости
        p.title = listing_title or p.title
        if supplier:
            p.supplier_id = supplier.id
        if cost_hint and not p.cost:
            p.cost = cost_hint
        db.commit()
    return p

def create_purchase_order(db: Session, payload: dict) -> PurchaseOrder:
    """
    payload:
    {
      "supplier_name": "ACME Distributor",
      "po_name": "PO-2025-10-001",
      "invoice_number": "INV-12345",
      "order_date": "2025-10-28",
      "sales_tax": 12.30,
      "shipping": 25.00,
      "discount": 5.00,
      "items": [
        {
          "asin": "...",
          "listing_title": "...",
          "amazon_link": "...",
          "supplier_mfr_code": "...",
          "quantity": 10,
          "purchase_price": 7.5,
          "sales_tax": null,      # опц. — если задано, не будем распределять из PO
          "shipping": null,       # опц.
          "discount": 0           # опц. скидка по позиции
        },
        ...
      ]
    }
    """
    supplier = _upsert_supplier(db, payload.get("supplier_name"))
    po = PurchaseOrder(
        supplier_id=(supplier.id if supplier else None),
        name=payload["po_name"],
        invoice_number=payload.get("invoice_number"),
        order_date=datetime.fromisoformat(payload.get("order_date")) if payload.get("order_date") else datetime.utcnow(),
        status=POStatus.NEW
    )
    db.add(po); db.commit(); db.refresh(po)

    # создаём позиции
    total_units = 0
    subtotal = 0.0
    for row in payload.get("items", []):
        asin = row["asin"].strip()
        title = row.get("listing_title", "").strip()
        p = _attach_product(db, asin, title, supplier, row.get("purchase_price"))

        qty = int(row["quantity"])
        price = float(row["purchase_price"])
        total_units += qty
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
            sales_tax=float(row["sales_tax"]) if row.get("sales_tax") is not None else 0.0,
            shipping=float(row["shipping"]) if row.get("shipping") is not None else 0.0,
            discount=float(row.get("discount") or 0.0),
        )
        db.add(item)

    # агрегаты по PO
    po.subtotal = float(subtotal)
    po.sales_tax = float(payload.get("sales_tax") or 0.0)
    po.shipping = float(payload.get("shipping") or 0.0)
    po.discount = float(payload.get("discount") or 0.0)

    db.commit()

    # распределим налог/доставку/скидку по позициям и посчитаем unit_cogs
    _recalculate_po_totals_and_cogs(db, po.id)

    db.refresh(po)
    return po

def _recalculate_po_totals_and_cogs(db: Session, po_id: int) -> None:
    po = db.get(PurchaseOrder, po_id)
    items = db.query(PurchaseOrderItem).filter_by(po_id=po_id).all()

    total_units = sum(i.quantity for i in items) or 1

    # Распределяем только ту часть tax/shipping/discount, которую НЕ задали на уровне item
    alloc_tax_pool = po.sales_tax - sum(i.sales_tax for i in items)
    alloc_ship_pool = po.shipping - sum(i.shipping for i in items)
    alloc_disc_pool = po.discount - sum(i.discount for i in items)

    for i in items:
        per_unit_tax = ((alloc_tax_pool / total_units) if alloc_tax_pool else 0.0)
        per_unit_ship = ((alloc_ship_pool / total_units) if alloc_ship_pool else 0.0)
        per_unit_disc = ((alloc_disc_pool / total_units) if alloc_disc_pool else 0.0) * (-1.0)  # скидка уменьшает себестоимость

        # Labeling/Prep по позиции
        lbl_sum = db.scalar(
            select(func.coalesce(func.sum(LabelingCost.cost_total), 0.0)).where(LabelingCost.po_item_id == i.id)
        ) or 0.0
        per_unit_label = lbl_sum / i.quantity if i.quantity else 0.0

        unit_cogs = float(i.purchase_price) \
                    + (i.sales_tax / i.quantity if i.quantity else 0.0) + per_unit_tax \
                    + (i.shipping / i.quantity if i.quantity else 0.0) + per_unit_ship \
                    + per_unit_label \
                    + per_unit_disc  # скидка отрицательным числом

        i.unit_cogs = round(unit_cogs, 6)
        i.extended_total = round(i.unit_cogs * i.quantity, 6)

        # Поддерживаем текущую себестоимость товара (как последняя закупка)
        if i.product_id:
            prod = db.get(Product, i.product_id)
            prod.cost = float(i.unit_cogs)

    # Пересчёт totals
    po.labeling_total = float(db.scalar(
        select(func.coalesce(func.sum(LabelingCost.cost_total), 0.0)).where(LabelingCost.po_item_id.in_([x.id for x in items]))
    ) or 0.0)

    # total_expense = subtotal + tax + shipping - discount + labeling_total
    po.total_expense = float(po.subtotal + po.sales_tax + po.shipping - po.discount + po.labeling_total)

    db.commit()

def add_labeling_cost(db: Session, po_item_id: int, note: str | None, cost_total: float) -> LabelingCost:
    lc = LabelingCost(po_item_id=po_item_id, note=note, cost_total=float(cost_total))
    db.add(lc); db.commit(); db.refresh(lc)

    # после добавления автоматически пересчитываем COGS и итоги по PO
    item = db.get(PurchaseOrderItem, po_item_id)
    _recalculate_po_totals_and_cogs(db, item.po_id)
    return lc

def list_purchase_orders(db: Session) -> list[PurchaseOrder]:
    return db.query(PurchaseOrder).order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).all()

def get_po_with_items(db: Session, po_id: int) -> PurchaseOrder:
    return db.query(PurchaseOrder).filter_by(id=po_id).one()

def set_po_status(db: Session, po_id: int, status: str) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    po.status = POStatus(status)
    db.commit(); db.refresh(po)
    return po
