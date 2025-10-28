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

    def __
