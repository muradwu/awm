
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
