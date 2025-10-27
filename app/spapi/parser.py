
import csv
from io import StringIO
from datetime import datetime

def _csv_to_rows(csv_text: str) -> list[dict]:
    reader = csv.DictReader(StringIO(csv_text))
    return [dict(row) for row in reader]

def parse_inventory_csv(csv_text: str) -> list[dict]:
    rows = _csv_to_rows(csv_text)
    out = []
    for r in rows:
        out.append({
            "sku": r["sku"],
            "qty": int(float(r["qty"])),
            "fc": r.get("fc", "FBA"),
            "at": datetime.fromisoformat(r["at"].replace("Z","+00:00")) if r.get("at") else None
        })
    return out

def parse_orders_csv(csv_text: str) -> list[dict]:
    rows = _csv_to_rows(csv_text)
    out = []
    for r in rows:
        out.append({
            "sku": r["sku"],
            "units": int(float(r["units"])),
            "price": float(r["price"]),
            "at": datetime.fromisoformat(r["at"].replace("Z","+00:00")) if r.get("at") else None
        })
    return out

def parse_settlement_csv(csv_text: str) -> list[dict]:
    rows = _csv_to_rows(csv_text)
    out = []
    for r in rows:
        out.append({
            "sku": r["sku"],
            "type": r.get("type", "OTHER"),
            "amount": float(r["amount"]),
            "at": datetime.fromisoformat(r["at"].replace("Z","+00:00")) if r.get("at") else None
        })
    return out
