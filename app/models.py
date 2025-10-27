
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
