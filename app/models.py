
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey, Float, DateTime, Enum, UniqueConstraint
from datetime import datetime
from .db import Base
import enum

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    products: Mapped[list["Product"]] = relationship(back_populates="supplier")

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String, unique=True, index=True)
    asin: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    cost: Mapped[float] = mapped_column(Float, default=0.0)

    supplier: Mapped["Supplier"] = relationship(back_populates="products")
    inventory_snapshots: Mapped[list["InventorySnapshot"]] = relationship(back_populates="product")
    sales: Mapped[list["Sale"]] = relationship(back_populates="product")
    fees: Mapped[list["Fee"]] = relationship(back_populates="product")
    metrics: Mapped[list["MetricSnapshot"]] = relationship(back_populates="product")

class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer)
    fc: Mapped[str] = mapped_column(String, default="FBA")
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    product: Mapped["Product"] = relationship(back_populates="inventory_snapshots")

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    units: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    product: Mapped["Product"] = relationship(back_populates="sales")

class FeeType(str, enum.Enum):
    FBA = "FBA"
    REFERRAL = "REFERRAL"
    OTHER = "OTHER"

class Fee(Base):
    __tablename__ = "fees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    type: Mapped[FeeType] = mapped_column(Enum(FeeType))
    amount: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    product: Mapped["Product"] = relationship(back_populates="fees")

class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (UniqueConstraint("product_id", "period", name="uq_product_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    period: Mapped[str] = mapped_column(String, index=True)  # e.g., '2025-10-01'
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    cogs: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    roi: Mapped[float] = mapped_column(Float, default=0.0)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    product: Mapped["Product"] = relationship(back_populates="metrics")

# --- ПОСЛЕ существующих моделей добавь это ---

from sqlalchemy import Boolean

class POStatus(str, enum.Enum):
    NEW = "NEW"
    CLOSED = "CLOSED"

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    supplier: Mapped["Supplier"] = relationship()
    name: Mapped[str] = mapped_column(String, index=True)               # Название Purchase Order
    invoice_number: Mapped[str | None] = mapped_column(String)
    order_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus), default=POStatus.NEW)

    # Итоги по PO (денежные поля считаем и держим для быстрого чтения)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)         # sum(units * purchase_price)
    sales_tax: Mapped[float] = mapped_column(Float, default=0.0)
    shipping: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    labeling_total: Mapped[float] = mapped_column(Float, default=0.0)   # суммарный Labeling/Prep
    total_expense: Mapped[float] = mapped_column(Float, default=0.0)    # subtotal+tax+shipping-labeling? (ниже считаем)

    items: Mapped[list["PurchaseOrderItem"]] = relationship(back_populates="po", cascade="all, delete-orphan")

class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    po: Mapped["PurchaseOrder"] = relationship(back_populates="items")

    # Товарная часть
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    product: Mapped["Product"] = relationship()
    asin: Mapped[str] = mapped_column(String, index=True)
    listing_title: Mapped[str] = mapped_column(String)
    amazon_link: Mapped[str | None] = mapped_column(String)
    supplier_mfr_code: Mapped[str | None] = mapped_column(String)

    quantity: Mapped[int] = mapped_column(Integer)
    purchase_price: Mapped[float] = mapped_column(Float)  # $ за единицу (до tax/shipping/discount)
    sales_tax: Mapped[float] = mapped_column(Float, default=0.0)  # item-level override (опц.), иначе распределим из PO
    shipping: Mapped[float] = mapped_column(Float, default=0.0)   # item-level override (опц.), иначе распределим из PO
    discount: Mapped[float] = mapped_column(Float, default=0.0)   # item-level item discount (опц.)

    # Расчитанные поля (после апдейта PO)
    unit_cogs: Mapped[float] = mapped_column(Float, default=0.0)        # итоговая себестоимость за 1 ед. с распределениями и labeling
    extended_total: Mapped[float] = mapped_column(Float, default=0.0)   # unit_cogs * quantity

class LabelingCost(Base):
    __tablename__ = "labeling_costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_items.id"))
    po_item: Mapped["PurchaseOrderItem"] = relationship()
    note: Mapped[str | None] = mapped_column(String)
    cost_total: Mapped[float] = mapped_column(Float, default=0.0)    # стоимость услуги на позицию целиком
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
