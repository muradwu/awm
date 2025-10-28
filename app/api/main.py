
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
  <nav style="display:flex;gap:12px;align-items:center;margin-bottom:12px">
    <a href="/" style="text-decoration:none;font-weight:700">Dashboard</a>
    <span style="color:#aaa">•</span>
    <a href="/po" style="text-decoration:none">Purchase Orders</a>
  </nav>

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
@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Purchase Orders</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:20px}
h1{margin-bottom:12px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border-bottom:1px solid #eee;padding:8px}
th{text-align:left;background:#fafafa}
input,button{padding:8px;border:1px solid #ddd;border-radius:8px}
.card{border:1px solid #eee;border-radius:12px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.05);margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.flex{display:flex;gap:8px;align-items:center}
.btn{cursor:pointer}
.btn.secondary{background:#f6f6f6}
.btn.danger{background:#ffe8e8;border-color:#ffcccc}
.right{text-align:right}
.mono{font-family:ui-monospace, Menlo, Consolas, monospace}
.badge{background:#fafafa;border:1px solid #eee;border-radius:999px;padding:2px 8px}
</style>
<script>
function el(tag, attrs={}, ...children){
  const e = document.createElement(tag);
  for(const [k,v] of Object.entries(attrs)){ if(k==='class') e.className=v; else if(k==='html') e.innerHTML=v; else e.setAttribute(k,v); }
  for(const c of children){ if(typeof c==='string') e.appendChild(document.createTextNode(c)); else if(c) e.appendChild(c); }
  return e;
}

function itemRow(idx){
  const row = el('tr', {class:'item-row'});
  row.appendChild(el('td', {}, el('input', {name:`asin_${idx}`, placeholder:'ASIN *', required:true, style:'width:120px'})));
  row.appendChild(el('td', {}, el('input', {name:`title_${idx}`, placeholder:'Listing title *', required:true, style:'width:220px'})));
  row.appendChild(el('td', {}, el('input', {name:`link_${idx}`, placeholder:'Amazon link', style:'width:200px'})));
  row.appendChild(el('td', {}, el('input', {name:`mfr_${idx}`, placeholder:'Supplier MFR', style:'width:140px'})));
  row.appendChild(el('td', {}, el('input', {name:`qty_${idx}`, type:'number', min:'1', step:'1', value:'1', required:true, style:'width:90px'})));
  row.appendChild(el('td', {}, el('input', {name:`price_${idx}`, type:'number', step:'0.0001', placeholder:'0.00', required:true, style:'width:110px'})));
  row.appendChild(el('td', {}, el('input', {name:`tax_${idx}`, type:'number', step:'0.0001', placeholder:'(opt)', style:'width:100px'})));
  row.appendChild(el('td', {}, el('input', {name:`ship_${idx}`, type:'number', step:'0.0001', placeholder:'(opt)', style:'width:100px'})));
  row.appendChild(el('td', {}, el('input', {name:`disc_${idx}`, type:'number', step:'0.0001', value:'0', style:'width:100px'})));
  const rm = el('button', {type:'button', class:'btn danger'}, 'Remove');
  rm.onclick = ()=> row.remove();
  row.appendChild(el('td', {}, rm));
  return row;
}

function collectItems(){
  const rows = Array.from(document.querySelectorAll('.item-row'));
  const items = [];
  for(const r of rows){
    const get = n => r.querySelector(`[name="${n}"]`);
    function val(name){ const x = get(name); return x ? x.value.trim() : ''; }
    const asin = val([...r.querySelectorAll('input')][0].name);
    // names are dynamic; we read by order instead:
    const inputs = r.querySelectorAll('input');
    const obj = {
      asin: inputs[0].value.trim(),
      listing_title: inputs[1].value.trim(),
      amazon_link: inputs[2].value.trim() || null,
      supplier_mfr_code: inputs[3].value.trim() || null,
      quantity: Number(inputs[4].value || 0),
      purchase_price: Number(inputs[5].value || 0),
      sales_tax: inputs[6].value ? Number(inputs[6].value) : null,
      shipping: inputs[7].value ? Number(inputs[7].value) : null,
      discount: inputs[8].value ? Number(inputs[8].value) : 0
    };
    if(!obj.asin || !obj.listing_title || !obj.quantity || !obj.purchase_price){
      alert('Fill required fields for each item (ASIN, title, qty, price).'); return null;
    }
    items.push(obj);
  }
  if(items.length===0){ alert('Add at least one item.'); return null; }
  return items;
}

async function createPO(ev){
  ev.preventDefault();
  const f = new FormData(ev.target);
  const items = collectItems();
  if(!items) return;

  const payload = {
    supplier_name: f.get('supplier_name') || null,
    po_name: f.get('po_name'),
    invoice_number: f.get('invoice_number') || null,
    order_date: f.get('order_date') || null,
    sales_tax: Number(f.get('sales_tax') || 0),
    shipping: Number(f.get('shipping') || 0),
    discount: Number(f.get('discount') || 0),
    items
  };

  const r = await fetch('/api/purchase-orders', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  if(!r.ok){ const t=await r.text(); alert('Error creating PO: '+t); return; }
  ev.target.reset();
  document.getElementById('items-body').innerHTML='';
  addItem(); // оставим одну пустую строку
  await loadPOs();
}

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
      <td><span class="badge">${x.status}</span></td>
      <td class="right">${x.total_expense.toFixed(2)}</td>
      <td><a href="/po/${x.id}">Open</a></td>`;
    tb.appendChild(tr);
  }
}

let itemIdx = 0;
function addItem(){
  const body = document.getElementById('items-body');
  body.appendChild(itemRow(itemIdx++));
}

window.addEventListener('DOMContentLoaded', ()=>{
  addItem(); // начнём с одной строки
  loadPOs();
});
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
      <div style="grid-column:1/-1;border-top:1px solid #eee;margin-top:6px;padding-top:8px;font-weight:600">Items</div>

      <div style="grid-column:1/-1">
        <table>
          <thead>
            <tr>
              <th>ASIN *</th><th>Title *</th><th>Amazon link</th><th>MFR code</th>
              <th>Qty *</th><th>Price *</th><th>Sales tax</th><th>Shipping</th><th>Discount</th><th></th>
            </tr>
          </thead>
          <tbody id="items-body"></tbody>
        </table>
        <div class="flex" style="margin-top:8px">
          <button type="button" class="btn secondary" onclick="addItem()">+ Add item</button>
          <span class="mono" style="color:#666">Сколько угодно строк перед созданием PO</span>
        </div>
      </div>

      <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center;margin-top:6px">
        <button type="submit" class="btn">Create a new purchase order</button>
        <span class="mono">Status: NEW</span>
      </div>
    </form>
  </div>

  <div class="card">
    <h3 style="margin-top:0">All Purchase Orders</h3>
    <table>
      <thead><tr>
        <th>ID</th><th>PO name</th><th>Supplier</th><th>Date</th><th>Status</th><th class="right">Total Expense</th><th></th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</body></html>
    """
    return HTMLResponse(html)
