from __future__ import annotations
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.models import GLTransaction, Prepayment

# ------- GL -------
def list_gl(db: Session, month: Optional[int] = None, year: Optional[int] = None) -> List[dict]:
    q = db.query(GLTransaction)
    if year:
        q = q.filter(GLTransaction.year == year)
    if month:
        q = q.filter(GLTransaction.month == month)
    q = q.order_by(GLTransaction.date.desc(), GLTransaction.id.desc())
    out = []
    for r in q.all():
        out.append({
            "id": r.id,
            "date": r.date.isoformat(),
            "nc_code": r.nc_code,
            "account_name": r.account_name,
            "reference": r.reference,
            "description": r.description,
            "amount": r.amount,
            "dr": r.dr,
            "cr": r.cr,
            "value": r.value,
            "month": r.month,
            "year": r.year
        })
    return out

def create_gl(db: Session, payload: dict) -> GLTransaction:
    def f(x, default=0.0):
        if x in (None, ""): return default
        try: return float(str(x).replace(",", "."))
        except: return default

    dt = payload.get("date")
    if not dt:
        dt_obj = datetime.utcnow()
    else:
        # допускаем YYYY-MM-DD
        try:
            dt_obj = datetime.fromisoformat(dt)
        except:
            dt_obj = datetime.utcnow()

    r = GLTransaction(
        date=dt_obj,
        nc_code=payload["nc_code"],
        account_name=payload["account_name"],
        reference=payload.get("reference"),
        description=payload.get("description"),
        amount=f(payload.get("amount")),
        dr=f(payload.get("dr")),
        cr=f(payload.get("cr")),
        value=f(payload.get("value")),
        month=int(payload.get("month") or dt_obj.month),
        year=int(payload.get("year") or dt_obj.year),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r

def tb(db: Session, month: Optional[int], year: Optional[int]) -> List[Dict]:
    """
    Trial Balance — агрегируем GL по account_name (или по nc_code).
    """
    q = db.query(
        GLTransaction.account_name.label("account"),
        func.coalesce(func.sum(GLTransaction.dr), 0.0).label("dr_sum"),
        func.coalesce(func.sum(GLTransaction.cr), 0.0).label("cr_sum"),
        func.coalesce(func.sum(GLTransaction.value), 0.0).label("val_sum"),
    )
    if year:
        q = q.filter(GLTransaction.year == year)
    if month:
        q = q.filter(GLTransaction.month == month)
    q = q.group_by(GLTransaction.account_name).order_by(GLTransaction.account_name.asc())

    out = []
    for row in q.all():
        out.append({
            "account": row.account,
            "dr": float(row.dr_sum or 0),
            "cr": float(row.cr_sum or 0),
            "value": float(row.val_sum or 0),
            "balance": float((row.dr_sum or 0) - (row.cr_sum or 0)),
        })
    return out

# ------- Prepayments -------
def list_prepayments(db: Session, month: Optional[int] = None, year: Optional[int] = None) -> List[dict]:
    q = db.query(Prepayment)
    if year:
        q = q.filter(Prepayment.year == year)
    if month:
        q = q.filter(Prepayment.month == month)
    q = q.order_by(Prepayment.date.desc(), Prepayment.id.desc())
    out = []
    for r in q.all():
        out.append({
            "id": r.id,
            "date": r.date.isoformat(),
            "party": r.party,
            "description": r.description,
            "amount": r.amount,
            "balance": r.balance,
            "month": r.month,
            "year": r.year
        })
    return out

def create_prepayment(db: Session, payload: dict) -> Prepayment:
    def f(x, default=0.0):
        if x in (None, ""): return default
        try: return float(str(x).replace(",", "."))
        except: return default

    dt = payload.get("date")
    if not dt:
        dt_obj = datetime.utcnow()
    else:
        try:
            dt_obj = datetime.fromisoformat(dt)
        except:
            dt_obj = datetime.utcnow()

    r = Prepayment(
        date=dt_obj,
        party=payload["party"],
        description=payload.get("description"),
        amount=f(payload.get("amount")),
        balance=f(payload.get("balance")),
        month=int(payload.get("month") or dt_obj.month),
        year=int(payload.get("year") or dt_obj.year),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r
