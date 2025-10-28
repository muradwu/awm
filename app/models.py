from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Enum,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship
import enum

# ---------- БАЗОВЫЙ КЛАСС ----------
Base = declarative_base()


# ---------- ENUM СТАТУСОВ ----------
class POStatus(enum.Enum):
    NEW = "NEW"
    CLOSED = "CLOSED"


# ---------- ПОСТАВЩИК ----------
class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    contact_name = Column(String(255))
    phone = Column(String(255))
    email = Column(String(255))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="supplier")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")

    def __repr__(self):
        return f"<Supplier(name={self.name})>"


# ---------- ПРОДУКТ ----------
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    sku = Column(String(255))
    asin = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(512))
    cost = Column(Float, default=0.0)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))

    supplier = relationship("Supplier", back_populates="products")
    po_items = relationship("PurchaseOrderItem", back_populates="product")

    def __repr__(self):
        return f"<Product(asin={self.asin}, cost={self.cost})>"


# ---------- PURCHASE ORDER ----------
class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    name = Column(String(255), nullable=False)
    invoice_number = Column(String(255))
    order_date = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(POStatus), default=POStatus.NEW)

    subtotal = Column(Float, default=0.0)
    sales_tax = Column(Float, default=0.0)
    shipping = Column(Float, default=0.0)
    discount = Column(Float, default=0.0)
    labeling_total = Column(Float, default=0.0)
    total_expense = Column(Float, default=0.0)

    supplier = relationship("Supplier", back_populates="purchase_orders")
    items = relationship("PurchaseOrderItem", back_populates="po", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PO(name={self.name}, status={self.status.value})>"


# ---------- PURCHASE ORDER ITEM ----------
class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)

    asin = Column(String(64), nullable=False)
    listing_title = Column(String(512))
    amazon_link = Column(Text)
    supplier_mfr_code = Column(String(255))
    quantity = Column(Integer, default=1)
    purchase_price = Column(Float, default=0.0)
    sales_tax = Column(Float, default=0.0)
    shipping = Column(Float, default=0.0)
    discount = Column(Float, default=0.0)

    unit_cogs = Column(Float, default=0.0)  # себестоимость за единицу
    extended_total = Column(Float, default=0.0)  # общая сумма по строке

    po = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product", back_populates="po_items")
    labeling_costs = relationship("LabelingCost", back_populates="po_item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<POItem(asin={self.asin}, qty={self.quantity}, unit_cogs={self.unit_cogs})>"


# ---------- LABELING / PREP ----------
class LabelingCost(Base):
    __tablename__ = "labeling_costs"

    id = Column(Integer, primary_key=True)
    po_item_id = Column(Integer, ForeignKey("purchase_order_items.id"))
    note = Column(String(255))
    cost_total = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    po_item = relationship("PurchaseOrderItem", back_populates="labeling_costs")

    def __repr__(self):
        return f"<LabelingCost(po_item_id={self.po_item_id}, cost_total={self.cost_total})>"
# ---------- GENERAL LEDGER (GL) ----------
class GLTransaction(Base):
    __tablename__ = "gl_transactions"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.utcnow, nullable=False)

    nc_code = Column(String(64), nullable=False)          # NC (код)
    account_name = Column(String(255), nullable=False)    # Account Name
    reference = Column(String(255))                       # Reference
    description = Column(Text)                            # Description

    amount = Column(Float, default=0.0)                   # Amount (введённая сумма)
    dr = Column(Float, default=0.0)                       # Dr
    cr = Column(Float, default=0.0)                       # Cr
    value = Column(Float, default=0.0)                    # Value (можно вычислять)

    month = Column(Integer, nullable=False)               # месяц (1..12)
    year = Column(Integer, nullable=False)                # год (YYYY)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- PREPAYMENTS ----------
class Prepayment(Base):
    __tablename__ = "prepayments"

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.utcnow, nullable=False)
    party = Column(String(255), nullable=False)           # контрагент
    description = Column(Text)
    amount = Column(Float, default=0.0)
    balance = Column(Float, default=0.0)

    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- SALES ----------
class SalesRecord(Base):
    __tablename__ = "sales_records"

    id = Column(Integer, primary_key=True)               # наш внутренний ID
    external_id = Column(String(128), index=True)        # ID из Amazon/Sellerboard
    date = Column(DateTime, nullable=False)

    asin = Column(String(64), index=True, nullable=False)
    description = Column(Text)

    amount = Column(Float, default=0.0)                  # Gross / Amount
    type = Column(String(64))                            # TYPE (Order/Refund/…)
    party = Column(String(255))                          # Party / Buyer / Marketplace

    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)

    units_sold = Column(Integer, default=0)
    cogs_per_unit = Column(Float, default=0.0)
    fba_fee_per_unit = Column(Float, default=0.0)
    amazon_fee_per_unit = Column(Float, default=0.0)

    after_fees_per_unit = Column(Float, default=0.0)
    net_per_unit = Column(Float, default=0.0)

    pay_supplier_per_unit = Column(Float, default=0.0)
    prep_per_unit = Column(Float, default=0.0)
    ship_to_amz_per_unit = Column(Float, default=0.0)

    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    po_item_id = Column(Integer, ForeignKey("purchase_order_items.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
