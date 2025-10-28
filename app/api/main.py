
from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session
from datetime import datetime
from ..db import Base, engine, get_db
from ..models import Product, Supplier, InventorySnapshot, Sale, Fee, MetricSnapshot
from ..services.scheduler import start_scheduler
from ..services.metrics import recompute_metrics_for_month
from pydantic import BaseModel

app = FastAPI(title="AWM — Amazon Wholesale Manager", version="0.2.0")
Base.metadata.create_all(bind=engine)
start_scheduler()

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SKUResponse(BaseModel):
    sku: str
    asin: str
    title: str
    supplier: str | None
    cost: float
    current_qty: int
    month_revenue: float
    month_profit: float
    month_roi: float

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.get("/sku/{sku}", response_model=SKUResponse)
def get_sku(sku: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter_by(sku=sku).one_or_none()
    if not p:
        raise HTTPException(404, f"SKU {sku} not found")
    # latest inventory
    inv = db.query(InventorySnapshot).filter_by(product_id=p.id).order_by(InventorySnapshot.at.desc()).first()
    # latest metric
    now = datetime.utcnow()
    period = now.strftime("%Y-%m")
    ms = db.query(MetricSnapshot).filter_by(product_id=p.id, period=period).one_or_none()
    return SKUResponse(
        sku=p.sku,
        asin=p.asin,
        title=p.title,
        supplier=p.supplier.name if p.supplier else None,
        cost=p.cost or 0.0,
        current_qty=inv.qty if inv else 0,
        month_revenue=ms.revenue if ms else 0.0,
        month_profit=ms.profit if ms else 0.0,
        month_roi=ms.roi if ms else 0.0,
    )

@app.get("/products")
def products(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    period = now.strftime("%Y-%m")
    out = []
    for p in db.query(Product).all():
        inv = db.query(InventorySnapshot).filter_by(product_id=p.id).order_by(InventorySnapshot.at.desc()).first()
        ms = db.query(MetricSnapshot).filter_by(product_id=p.id, period=period).one_or_none()
        out.append({
            "sku": p.sku,
            "asin": p.asin,
            "title": p.title,
            "supplier": p.supplier.name if p.supplier else None,
            "cost": float(p.cost or 0.0),
            "qty": int(inv.qty if inv else 0),
            "revenue": float(ms.revenue if ms else 0.0),
            "profit": float(ms.profit if ms else 0.0),
            "roi": float(ms.roi if ms else 0.0),
        })
    return out

@app.get("/dashboard/summary")
def summary(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    period = now.strftime("%Y-%m")
    rows = db.query(MetricSnapshot).filter_by(period=period).all()
    total_revenue = sum(r.revenue for r in rows)
    total_profit = sum(r.profit for r in rows)
    avg_roi = (sum(r.roi for r in rows) / len(rows)) if rows else 0.0

    top_products = sorted(rows, key=lambda r: r.profit, reverse=True)[:10]
    top_list = [{
        "sku": db.query(Product).get(tp.product_id).sku,
        "profit": tp.profit,
        "revenue": tp.revenue,
        "roi": tp.roi
    } for tp in top_products]

    return {
        "period": period,
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "avg_roi": avg_roi,
        "top_products": top_list
    }

class RecomputeRequest(BaseModel):
    year: int
    month: int

@app.post("/admin/recompute")
def admin_recompute(req: RecomputeRequest, db: Session = Depends(get_db)):
    recompute_metrics_for_month(db, req.year, req.month)
    return {"ok": True}

@app.post("/admin/run-sync")
def admin_run_sync(db: Session = Depends(get_db)):
    from ..services.scheduler import daily_job
    daily_job()
    return {"ok": True}

@app.get("/export/metrics.csv")
def export_metrics_csv(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    period = now.strftime("%Y-%m")
    rows = db.query(MetricSnapshot).filter_by(period=period).all()
    header = "sku,period,revenue,cogs,fees,profit,roi\n"
    lines = [header]
    for r in rows:
        sku = db.query(Product).get(r.product_id).sku
        lines.append(f"{sku},{r.period},{r.revenue:.2f},{r.cogs:.2f},{r.fees:.2f},{r.profit:.2f},{r.roi:.2f}\n")
    return PlainTextResponse("".join(lines), media_type="text/csv")

# --- Minimal Web UI ---
DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AWM Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script>
    async function loadSummary() {
      const r = await fetch('/dashboard/summary');
      const s = await r.json();
      document.getElementById('period').textContent = s.period;
      document.getElementById('totalRevenue').textContent = s.total_revenue.toFixed(2);
      document.getElementById('totalProfit').textContent = s.total_profit.toFixed(2);
      document.getElementById('avgRoi').textContent = s.avg_roi.toFixed(2) + '%';

      const labels = s.top_products.map(p => p.sku);
      const profits = s.top_products.map(p => p.profit);
      const ctx = document.getElementById('profitChart').getContext('2d');
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels,
          datasets: [{ label: 'Profit', data: profits }]
        },
        options: { responsive: true, maintainAspectRatio: false }
      });
    }
    async function loadProducts() {
      const r = await fetch('/products');
      const rows = await r.json();
      const tbody = document.getElementById('tbody');
      tbody.innerHTML = '';
      for (const x of rows) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${x.sku}</td>
          <td>${x.title}</td>
          <td>${x.supplier ?? ''}</td>
          <td style="text-align:right">${x.cost.toFixed(2)}</td>
          <td style="text-align:right">${x.qty}</td>
          <td style="text-align:right">${x.revenue.toFixed(2)}</td>
          <td style="text-align:right">${x.profit.toFixed(2)}</td>
          <td style="text-align:right">${x.roi.toFixed(2)}%</td>`;
        tbody.appendChild(tr);
      }
    }
    window.addEventListener('DOMContentLoaded', async () => {
      await loadSummary();
      await loadProducts();
    });
  </script>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 2rem; }
    .cards { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 1rem; }
    .card { border: 1px solid #eee; border-radius: 12px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
    .muted { color: #666; font-size: .9rem; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { border-bottom: 1px solid #eee; padding: .5rem; }
    th { text-align: left; background: #fafafa; }
    #chartWrap { height: 280px; }
    @media (max-width: 900px) { .cards{ grid-template-columns: repeat(2,1fr);} }
    @media (max-width: 600px) { .cards{ grid-template-columns: 1fr;} }
  </style>
</head>
<body>
  <h1>AWM — Dashboard <span class="muted" id="period"></span></h1>
  <div class="cards">
    <div class="card"><div class="muted">Total Revenue</div><div id="totalRevenue" style="font-size:1.6rem;font-weight:700">—</div></div>
    <div class="card"><div class="muted">Total Profit</div><div id="totalProfit" style="font-size:1.6rem;font-weight:700">—</div></div>
    <div class="card"><div class="muted">Average ROI</div><div id="avgRoi" style="font-size:1.6rem;font-weight:700">—</div></div>
    <div class="card"><div class="muted">Exports</div><a href="/export/metrics.csv">Download metrics.csv</a></div>
  </div>

  <div class="card" style="margin-top:1rem;">
    <div class="muted" style="margin-bottom:.5rem;">Top Products by Profit</div>
    <div id="chartWrap"><canvas id="profitChart"></canvas></div>
  </div>

  <h2 style="margin-top:1.5rem;">Products</h2>
  <table>
    <thead>
      <tr>
        <th>SKU</th><th>Title</th><th>Supplier</th><th style="text-align:right">Cost</th><th style="text-align:right">Qty</th><th style="text-align:right">Revenue</th><th style="text-align:right">Profit</th><th style="text-align:right">ROI</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def web_index():
    return HTMLResponse(content=DASHBOARD_HTML)
# --- ДОБАВКИ ДЛЯ PURCHASE ORDERS ---
from ..services import purchase_orders as po_svc

class POItemIn(BaseModel):
    asin: str
    listing_title: str
    amazon_link: str | None = None
    supplier_mfr_code: str | None = None
    quantity: int
    purchase_price: float
    sales_tax: float | None = None
    shipping: float | None = None
    discount: float | None = 0.0

class POCreate(BaseModel):
    supplier_name: str | None = None
    po_name: str
    invoice_number: str | None = None
    order_date: str | None = None  # 'YYYY-MM-DD'
    sales_tax: float | None = 0.0
    shipping: float | None = 0.0
    discount: float | None = 0.0
    items: list[POItemIn]

class POStatusPatch(BaseModel):
    status: str  # NEW | CLOSED

class LabelingIn(BaseModel):
    po_item_id: int
    note: str | None = None
    cost_total: float

@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Purchase Orders</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:20px}
h1{margin-bottom:12px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border-bottom:1px solid #eee;padding:8px}
th{text-align:left;background:#fafafa}
input,select,button,textarea{padding:8px;border:1px solid #ddd;border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.card{border:1px solid #eee;border-radius:12px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:12px}
.mono{font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace}
</style>
<script>
async function loadPOs(){
  const r = await fetch('/api/purchase-orders'); const rows = await r.json();
  const tb = document.getElementById('tbody'); tb.innerHTML='';
  for(const x of rows){
    const tr=document.createElement('tr');
    tr.innerHTML = `
      <td class="mono">#${x.id}</td>
      <td>${x.name}</td>
      <td>${x.supplier ?? ''}</td>
      <td>${x.order_date.split('T')[0]}</td>
      <td>${x.status}</td>
      <td style="text-align:right">${x.total_expense.toFixed(2)}</td>
      <td><a href="/po/${x.id}">Open</a></td>`;
    tb.appendChild(tr);
  }
}
async function createPO(ev){
  ev.preventDefault();
  const form = new FormData(ev.target);
  const item = {
    asin: form.get('asin'),
    listing_title: form.get('listing_title'),
    amazon_link: form.get('amazon_link') || null,
    supplier_mfr_code: form.get('supplier_mfr_code') || null,
    quantity: Number(form.get('quantity')),
    purchase_price: Number(form.get('purchase_price')),
    sales_tax: form.get('item_sales_tax')? Number(form.get('item_sales_tax')): null,
    shipping: form.get('item_shipping')? Number(form.get('item_shipping')): null,
    discount: form.get('item_discount')? Number(form.get('item_discount')): 0
  };
  const payload = {
    supplier_name: form.get('supplier_name') || null,
    po_name: form.get('po_name'),
    invoice_number: form.get('invoice_number') || null,
    order_date: form.get('order_date') || null,
    sales_tax: Number(form.get('sales_tax') || 0),
    shipping: Number(form.get('shipping') || 0),
    discount: Number(form.get('discount') || 0),
    items: [item]
  };
  const r = await fetch('/api/purchase-orders', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  if(!r.ok){ alert('Error creating PO'); return; }
  ev.target.reset(); await loadPOs();
}
window.addEventListener('DOMContentLoaded', loadPOs);
</script>
</head><body>
  <h1>Purchase Orders</h1>
  <div class="card">
    <h3 style="margin-top:0">New Purchase Order</h3>
    <form class="grid" onsubmit="createPO(event)">
      <input name="supplier_name" placeholder="Supplier name">
      <input name="po_name" placeholder="PO name *" required>
      <input name="invoice_number" placeholder="Invoice #">
      <input name="order_date" type="date">
      <input name="sales_tax" placeholder="PO Sales tax (total)">
      <input name="shipping" placeholder="PO Shipping (total)">
      <input name="discount" placeholder="PO Discount (total)">
      <div style="grid-column:1/-1;border-top:1px solid #eee;margin-top:6px;padding-top:8px;font-weight:600">Item</div>
      <input name="asin" placeholder="ASIN *" required>
      <input name="listing_title" placeholder="Listing title *" required>
      <input name="amazon_link" placeholder="Amazon link">
      <input name="supplier_mfr_code" placeholder="Supplier MFR code">
      <input name="quantity" type="number" min="1" step="1" placeholder="Quantity *" required>
      <input name="purchase_price" type="number" step="0.0001" placeholder="Purchase price *" required>
      <input name="item_sales_tax" type="number" step="0.0001" placeholder="Item sales tax (opt)">
      <input name="item_shipping" type="number" step="0.0001" placeholder="Item shipping (opt)">
      <input name="item_discount" type="number" step="0.0001" placeholder="Item discount (opt)">
      <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center">
        <button type="submit">Create a new purchase order</button>
        <span class="mono">Status: NEW</span>
      </div>
    </form>
  </div>

  <div class="card">
    <h3 style="margin-top:0">All Purchase Orders</h3>
    <table>
      <thead><tr>
        <th>ID</th><th>PO name</th><th>Supplier</th><th>Date</th><th>Status</th><th style="text-align:right">Total Expense</th><th></th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</body></html>
    """
    return HTMLResponse(html)

@app.get("/po/{po_id}", response_class=HTMLResponse)
def po_detail(po_id: int, db: Session = Depends(get_db)):
    po = po_svc.get_po_with_items(db, po_id)
    # простая читаемая страница с позициями и формой добавления Labeling
    rows = ""
    for it in po.items:
        rows += f"<tr><td>{it.asin}</td><td>{it.listing_title}</td><td>{it.quantity}</td><td>{it.purchase_price:.4f}</td><td>{it.unit_cogs:.4f}</td><td class='mono'>{it.id}</td></tr>"
    html = f"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PO #{po.id}</title>
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:20px}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
th,td{{border-bottom:1px solid #eee;padding:8px}}
th{{text-align:left;background:#fafafa}}
input,button{{padding:8px;border:1px solid #ddd;border-radius:8px}}
.card{{border:1px solid #eee;border-radius:12px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:12px}}
.mono{{font-family:ui-monospace, Menlo, Consolas, monospace}}
</style>
<script>
async function addLabeling(e){{
  e.preventDefault();
  const f = new FormData(e.target);
  const payload = {{
    po_item_id: Number(f.get('po_item_id')),
    note: f.get('note') || null,
    cost_total: Number(f.get('cost_total'))
  }};
  const r = await fetch('/api/po/labeling', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}})
  if(!r.ok){{ alert('Error adding labeling'); return; }}
  location.reload();
}}
async function setStatus(status) {{
  await fetch('/api/purchase-orders/{po.id}/status', {{method:'PATCH', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{status}})}})
  location.reload();
}}
</script>
</head><body>
  <div class="card">
    <h2 style="margin:0">PO #{po.id} — {po.name} <span class="mono">[{po.status}]</span></h2>
    <div>Supplier: {po.supplier.name if po.supplier else ''}</div>
    <div>Date: {po.order_date.date()}</div>
    <div>Total expense: <b>{po.total_expense:.2f}</b> (subtotal {po.subtotal:.2f} + tax {po.sales_tax:.2f} + ship {po.shipping:.2f} - disc {po.discount:.2f} + labeling {po.labeling_total:.2f})</div>
    <div style="margin-top:8px;display:flex;gap:8px">
      <button onclick="setStatus('NEW')">Set NEW</button>
      <button onclick="setStatus('CLOSED')">Set CLOSED</button>
      <a href="/po" style="margin-left:auto">← Back to list</a>
    </div>
  </div>

  <div class="card">
    <h3 style="margin:0">Items</h3>
    <table>
      <thead><tr><th>ASIN</th><th>Title</th><th>Qty</th><th>Purchase price</th><th>Unit COGS</th><th>Item ID</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h3 style="margin:0">Labeling / Prep</h3>
    <form onsubmit="addLabeling(event)">
      <div>PO Item ID: <input name="po_item_id" required placeholder="e.g. 12"></div>
      <div>Cost total: <input name="cost_total" type="number" step="0.0001" required></div>
      <div>Note: <input name="note" placeholder="e.g. FNSKU labels"></div>
      <div style="margin-top:8px"><button type="submit">Add labeling cost</button></div>
    </form>
    <div class="mono" style="margin-top:6px">* после добавления произойдёт автоматический пересчёт COGS</div>
  </div>
</body></html>
    """
    return HTMLResponse(html)

@app.get("/api/purchase-orders")
def api_po_list(db: Session = Depends(get_db)):
    pos = po_svc.list_purchase_orders(db)
    out = []
    for p in pos:
        out.append({
            "id": p.id,
            "name": p.name,
            "supplier": (p.supplier.name if p.supplier else None),
            "order_date": p.order_date.isoformat(),
            "status": p.status.value,
            "subtotal": p.subtotal,
            "sales_tax": p.sales_tax,
            "shipping": p.shipping,
            "discount": p.discount,
            "labeling_total": p.labeling_total,
            "total_expense": p.total_expense
        })
    return out

@app.post("/api/purchase-orders")
def api_po_create(body: POCreate, db: Session = Depends(get_db)):
    po = po_svc.create_purchase_order(db, body.model_dump())
    return {"ok": True, "po_id": po.id}

@app.patch("/api/purchase-orders/{po_id}/status")
def api_po_status(po_id: int, body: POStatusPatch, db: Session = Depends(get_db)):
    po = po_svc.set_po_status(db, po_id, body.status)
    return {"ok": True, "status": po.status.value}

@app.post("/api/po/labeling")
def api_po_labeling(body: LabelingIn, db: Session = Depends(get_db)):
    lc = po_svc.add_labeling_cost(db, body.po_item_id, body.note, body.cost_total)
    return {"ok": True, "labeling_id": lc.id}

@app.post("/admin/run-seed")
def run_seed(db: Session = Depends(get_db)):
    from ..scripts import seed_demo
    seed_demo.run(db)
    return {"ok": True, "message": "Demo data seeded"}
