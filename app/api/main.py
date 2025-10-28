from __future__ import annotations
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db, init_db
from ..services import purchase_orders as po_svc
from ..services import accounting as acc_svc
from ..services import sales as sales_svc

app = FastAPI(title="AWM API")

# ---------- авто-инициализация БД ----------
@app.on_event("startup")
def _startup_create_tables():
    init_db()

# ---------- модели запросов ----------
class POItemIn(BaseModel):
    asin: str
    listing_title: str
    amazon_link: str | None = None
    supplier_mfr_code: str | None = None
    quantity: int
    purchase_price: float
    sales_tax: float | None = 0.0
    shipping: float | None = 0.0
    discount: float | None = 0.0

class POCreate(BaseModel):
    supplier_name: str | None = None
    po_name: str
    invoice_number: str | None = None
    order_date: str | None = None
    sales_tax: float | None = 0.0
    shipping: float | None = 0.0
    discount: float | None = 0.0
    items: list[POItemIn]

class POStatusPatch(BaseModel):
    status: str

class LabelingIn(BaseModel):
    po_item_id: int
    note: str | None = None
    cost_total: float

class GLIn(BaseModel):
    date: str | None = None
    nc_code: str
    account_name: str
    reference: str | None = None
    description: str | None = None
    amount: float | None = 0.0
    dr: float | None = 0.0
    cr: float | None = 0.0
    value: float | None = 0.0
    month: int | None = None
    year: int | None = None

class PrepaymentIn(BaseModel):
    date: str | None = None
    party: str
    description: str | None = None
    amount: float | None = 0.0
    balance: float | None = 0.0
    month: int | None = None
    year: int | None = None

class SalesImportIn(BaseModel):
    records: list[dict]

# ---------- layout ----------
def render_layout(active: str, content_html: str, title="AWM"):
    menu_items = [
        ("Dashboard", "/", "dashboard"),
        ("Purchase Orders", "/po", "po"),
        ("Label / Prep", "/label", "label"),
        ("Transportation Costs", "/transport", "transport"),
        ("Inventory", "/inventory", "inventory"),
        ("—", "#", "sep"),
        ("Accounting: GL", "/accounting/gl", "gl"),
        ("Accounting: Prepayments", "/accounting/prepayments", "prepayments"),
        ("Accounting: TB", "/accounting/tb", "tb"),
        ("Sales", "/sales", "sales"),
    ]
    sidebar = ""
    for name, link, key in menu_items:
        if key == "sep":
            sidebar += '<div style="border-top:1px solid #2a2a2a;margin:12px 0;"></div>'
            continue
        cls = "active" if key == active else ""
        sidebar += f'<a href="{link}" class="menu-item {cls}">{name}</a>'
    return f"""
<!doctype html><html><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
body {{ margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#121212;color:#fff;display:flex;height:100vh; }}
.sidebar{{width:260px;background:#1e1e1e;padding:20px;display:flex;flex-direction:column}}
.menu-item{{color:#bbb;text-decoration:none;padding:10px 0;display:block;border-left:3px solid transparent}}
.menu-item.active{{color:#fff;font-weight:600;border-left:3px solid #007bff}}
.menu-item:hover{{color:#fff}}
.content{{flex:1;overflow-y:auto;padding:20px 30px}}
.card{{background:#1e1e1e;border-radius:10px;padding:16px;margin-bottom:20px;box-shadow:0 0 10px rgba(0,0,0,.3)}}
table{{width:100%;border-collapse:collapse;color:#fff}}
th,td{{border-bottom:1px solid #333;padding:8px;text-align:left}}
th{{background:#2a2a2a}}
input,button,select,textarea{{background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px;padding:8px}}
button:hover{{background:#007bff;border-color:#007bff}}
.flex{{display:flex;gap:8px;align-items:center}}
</style></head>
<body>
  <div class="sidebar">
    <h2 style="color:#fff;margin-bottom:20px;">AWM</h2>
    {sidebar}
  </div>
  <div class="content">{content_html}</div>
</body></html>
"""

# ---------- Pages: basic ----------
@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    html = """
    <h1>Dashboard</h1>
    <div class="card">
      <p>Добро пожаловать в Amazon Wholesale Manager.</p>
      <p>Используйте левое меню: PO, Label/Prep, Transport, Inventory, Accounting (GL/Prepayments/TB) и Sales.</p>
    </div>
    """
    return HTMLResponse(render_layout("dashboard", html))

# ---------- Purchase Orders (та же версия с таблицей ASIN) ----------
@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = """
    <h1>Purchase Orders</h1>
    <div class="card">
      <h3>New Purchase Order</h3>
      <form id="poForm" onsubmit="createPO(event)">
        <input name='supplier_name' placeholder='Supplier name'>
        <input name='po_name' placeholder='PO name *' required>
        <input name='invoice_number' placeholder='Invoice #'>
        <input name='order_date' type='date'>
        <input name='sales_tax' placeholder='Sales Tax'>
        <input name='shipping' placeholder='Shipping'>
        <input name='discount' placeholder='Discount'>

        <div style="margin-top:15px;border-top:1px solid #333;padding-top:10px;">
          <h4>Items</h4>
          <table id='itemsTbl'>
            <thead><tr><th>ASIN *</th><th>Title *</th><th>Qty</th><th>Price</th><th></th></tr></thead>
            <tbody></tbody>
          </table>
          <button type="button" onclick="addItem()">+ Add ASIN</button>
        </div>

        <div style="margin-top:10px;">
          <button type='submit'>Create PO</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3>All Purchase Orders</h3>
      <table id='tbl'>
        <thead><tr><th>ID</th><th>Name</th><th>Supplier</th><th>Date</th><th>Status</th><th>Total</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

<script>
function addItem(){
  const tb=document.querySelector("#itemsTbl tbody");
  const tr=document.createElement("tr");
  tr.innerHTML=`<td><input name='asin' placeholder='ASIN' required></td>
                <td><input name='title' placeholder='Title' required></td>
                <td><input name='qty' type='number' min='1' step='1' value='1'></td>
                <td><input name='price' type='number' step='0.01' value='0'></td>
                <td><button type='button' onclick='this.parentElement.parentElement.remove()'>🗑</button></td>`;
  tb.appendChild(tr);
}
function collectItems(){
  const rows=document.querySelectorAll("#itemsTbl tbody tr");
  const arr=[];
  for(const r of rows){
    const asin=r.querySelector("input[name='asin']").value.trim();
    const title=r.querySelector("input[name='title']").value.trim();
    const qty=Number(r.querySelector("input[name='qty']").value||0);
    const price=Number(r.querySelector("input[name='price']").value||0);
    if(!asin||!title) continue;
    arr.push({asin,listing_title:title,quantity:qty,purchase_price:price,sales_tax:0,shipping:0,discount:0});
  }
  return arr;
}
async function createPO(e){
  e.preventDefault();
  const f=new FormData(e.target);
  const payload={
    supplier_name:f.get('supplier_name')||null,
    po_name:f.get('po_name'),
    invoice_number:f.get('invoice_number')||null,
    order_date:f.get('order_date')||null,
    sales_tax:parseFloat(f.get('sales_tax')||0),
    shipping:parseFloat(f.get('shipping')||0),
    discount:parseFloat(f.get('discount')||0),
    items:collectItems()
  };
  if(payload.items.length===0){alert("Add at least one ASIN");return;}
  const r=await fetch('/api/purchase-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(r.ok){alert('PO created');loadPOs();e.target.reset();document.querySelector("#itemsTbl tbody").innerHTML='';addItem();}
  else alert(await r.text());
}
async function loadPOs(){
  const r=await fetch('/api/purchase-orders');const data=await r.json();
  const tb=document.querySelector('#tbl tbody');tb.innerHTML='';
  for(const po of data){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${po.id}</td><td>${po.name}</td><td>${po.supplier||''}</td>
                  <td>${po.order_date?.split('T')[0]||''}</td><td>${po.status}</td>
                  <td>${po.total_expense.toFixed(2)}</td>`;
    tb.appendChild(tr);
  }
}
loadPOs();addItem();
</script>
    """
    return HTMLResponse(render_layout("po", html, "Purchase Orders"))

# ---------- Label / Transport / Inventory (как раньше-списочно) ----------
@app.get("/label", response_class=HTMLResponse)
def label_page(db: Session = Depends(get_db)):
    items = db.query(po_svc.PurchaseOrderItem).all()
    rows = ""
    for it in items:
        rows += f"<tr><td>{it.asin}</td><td>{it.listing_title}</td><td>{it.quantity}</td><td>{it.purchase_price:.2f}</td><td><input placeholder='Prep center'><input placeholder='Prep cost' style='width:100px'></td></tr>"
    html = f"""
    <h1>Label / Prep</h1>
    <div class='card'>
      <table><thead><tr><th>ASIN</th><th>Title</th><th>Qty</th><th>Cost</th><th>Prep</th></tr></thead><tbody>{rows}</tbody></table>
    </div>
    """
    return HTMLResponse(render_layout("label", html, "Label / Prep"))

@app.get("/transport", response_class=HTMLResponse)
def transport_page(db: Session = Depends(get_db)):
    items = db.query(po_svc.PurchaseOrderItem).all()
    rows = ""
    for it in items:
        rows += f"<tr><td>{it.asin}</td><td>{it.listing_title}</td><td>{it.quantity}</td><td>{it.purchase_price:.2f}</td><td><input placeholder='Shipping to FBA' style='width:120px'></td></tr>"
    html = f"""
    <h1>Transportation Costs</h1>
    <div class='card'>
      <table><thead><tr><th>ASIN</th><th>Title</th><th>Qty</th><th>Cost</th><th>Shipping to FBA</th></tr></thead><tbody>{rows}</tbody></table>
    </div>
    """
    return HTMLResponse(render_layout("transport", html, "Transportation Costs"))

@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(db: Session = Depends(get_db)):
    items = db.query(po_svc.PurchaseOrderItem).all()
    rows = ""
    for it in items:
        total = it.quantity * (it.unit_cogs or 0)
        rows += f"<tr><td>{it.asin}</td><td>{it.listing_title}</td><td>{it.quantity}</td><td>{it.unit_cogs:.2f}</td><td>{total:.2f}</td></tr>"
    html = f"""
    <h1>Inventory</h1>
    <div class='card'>
      <table><thead><tr><th>ASIN</th><th>Title</th><th>Qty</th><th>COGS</th><th>Total Cost</th></tr></thead><tbody>{rows}</tbody></table>
    </div>
    """
    return HTMLResponse(render_layout("inventory", html, "Inventory"))

# ---------- Accounting: GL ----------
@app.get("/accounting/gl", response_class=HTMLResponse)
def accounting_gl_page(month: int | None = Query(None), year: int | None = Query(None), db: Session = Depends(get_db)):
    rows_data = acc_svc.list_gl(db, month=month, year=year)
    rows = ""
    for r in rows_data:
        rows += f"<tr><td>{r['date'][:10]}</td><td>{r['nc_code']}</td><td>{r['account_name']}</td><td>{r['reference'] or ''}</td><td>{r['description'] or ''}</td><td>{r['amount']:.2f}</td><td>{r['dr']:.2f}</td><td>{r['cr']:.2f}</td><td>{r['value']:.2f}</td><td>{r['month']}/{r['year']}</td></tr>"

    html = f"""
    <h1>Accounting — GL</h1>
    <div class='card'>
      <form class='flex' onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)" value="{month or ''}">
        <input id="y" placeholder="Year (YYYY)" value="{year or ''}">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class='card'>
      <h3>New GL Transaction</h3>
      <form id="glForm" onsubmit="return createGL(event)">
        <input name="date" type="date">
        <input name="nc_code" placeholder="NC code *" required>
        <input name="account_name" placeholder="Account Name *" required>
        <input name="reference" placeholder="Reference">
        <input name="description" placeholder="Description">
        <input name="amount" placeholder="Amount">
        <input name="dr" placeholder="Dr">
        <input name="cr" placeholder="Cr">
        <input name="value" placeholder="Value">
        <input name="month" placeholder="Month">
        <input name="year" placeholder="Year">
        <button type="submit">Add</button>
      </form>
    </div>
    <div class='card'>
      <table>
        <thead><tr><th>Date</th><th>NC</th><th>Account</th><th>Ref</th><th>Description</th><th>Amount</th><th>Dr</th><th>Cr</th><th>Value</th><th>Period</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <script>
    function goFilter(){ 
      const m=document.getElementById('m').value.trim(); 
      const y=document.getElementById('y').value.trim();
      const qs = new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
      location.href='/accounting/gl'+(qs.toString() ? ('?'+qs.toString()) : ''); 
      return false;
    }
    async function createGL(e){
      e.preventDefault();
      const f=new FormData(e.target);
      const body = Object.fromEntries(f.entries());
      // пустые числа -> 0
      for (const k of ["amount","dr","cr","value"]) body[k] = parseFloat(body[k]||0);
      if (body["month"]) body["month"]=parseInt(body["month"]);
      if (body["year"]) body["year"]=parseInt(body["year"]);
      const r=await fetch('/api/gl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!r.ok) return alert(await r.text());
      location.reload();
    }
    </script>
    """
    return HTMLResponse(render_layout("gl", html, "Accounting — GL"))

# ---------- Accounting: Prepayments ----------
@app.get("/accounting/prepayments", response_class=HTMLResponse)
def accounting_prepayments_page(month: int | None = Query(None), year: int | None = Query(None), db: Session = Depends(get_db)):
    rows_data = acc_svc.list_prepayments(db, month=month, year=year)
    rows = ""
    for r in rows_data:
        rows += f"<tr><td>{r['date'][:10]}</td><td>{r['party']}</td><td>{r['description'] or ''}</td><td>{r['amount']:.2f}</td><td>{r['balance']:.2f}</td><td>{r['month']}/{r['year']}</td></tr>"

    html = f"""
    <h1>Accounting — Prepayments</h1>
    <div class='card'>
      <form class='flex' onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)" value="{month or ''}">
        <input id="y" placeholder="Year (YYYY)" value="{year or ''}">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class='card'>
      <h3>New Prepayment</h3>
      <form onsubmit="return createPP(event)">
        <input name="date" type="date">
        <input name="party" placeholder="Party *" required>
        <input name="description" placeholder="Description">
        <input name="amount" placeholder="Amount">
        <input name="balance" placeholder="Balance">
        <input name="month" placeholder="Month">
        <input name="year" placeholder="Year">
        <button type="submit">Add</button>
      </form>
    </div>
    <div class='card'>
      <table>
        <thead><tr><th>Date</th><th>Party</th><th>Description</th><th>Amount</th><th>Balance</th><th>Period</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <script>
    function goFilter(){ 
      const m=document.getElementById('m').value.trim(); 
      const y=document.getElementById('y').value.trim();
      const qs = new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
      location.href='/accounting/prepayments'+(qs.toString() ? ('?'+qs.toString()) : ''); 
      return false;
    }
    async function createPP(e){
      e.preventDefault();
      const f=new FormData(e.target);
      const body = Object.fromEntries(f.entries());
      for (const k of ["amount","balance"]) body[k] = parseFloat(body[k]||0);
      if (body["month"]) body["month"]=parseInt(body["month"]);
      if (body["year"]) body["year"]=parseInt(body["year"]);
      const r=await fetch('/api/prepayments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!r.ok) return alert(await r.text());
      location.reload();
    }
    </script>
    """
    return HTMLResponse(render_layout("prepayments", html, "Accounting — Prepayments"))

# ---------- Accounting: TB ----------
@app.get("/accounting/tb", response_class=HTMLResponse)
def accounting_tb_page(month: int | None = Query(None), year: int | None = Query(None), db: Session = Depends(get_db)):
    rows_data = acc_svc.tb(db, month=month, year=year)
    rows = ""
    for r in rows_data:
        rows += f"<tr><td>{r['account']}</td><td>{r['dr']:.2f}</td><td>{r['cr']:.2f}</td><td>{r['value']:.2f}</td><td>{r['balance']:.2f}</td></tr>"
    html = f"""
    <h1>Accounting — Trial Balance</h1>
    <div class='card'>
      <form class='flex' onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)" value="{month or ''}">
        <input id="y" placeholder="Year (YYYY)" value="{year or ''}">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class='card'>
      <table>
        <thead><tr><th>Account</th><th>Dr</th><th>Cr</th><th>Value</th><th>Balance (Dr-Cr)</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <script>
    function goFilter(){ 
      const m=document.getElementById('m').value.trim(); 
      const y=document.getElementById('y').value.trim();
      const qs = new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
      location.href='/accounting/tb'+(qs.toString() ? ('?'+qs.toString()) : ''); 
      return false;
    }
    </script>
    """
    return HTMLResponse(render_layout("tb", html, "Accounting — TB"))

# ---------- Sales ----------
@app.get("/sales", response_class=HTMLResponse)
def sales_page(month: int | None = Query(None), year: int | None = Query(None), db: Session = Depends(get_db)):
    rows_data = sales_svc.list_sales(db, month=month, year=year)
    rows = ""
    for s in rows_data:
        rows += (
            f"<tr><td>{s['id']}</td><td>{s['date'][:10]}</td><td>{s['asin']}</td><td>{s['description'] or ''}</td>"
            f"<td>{s['amount']:.2f}</td><td>{s['type'] or ''}</td><td>{s['party'] or ''}</td>"
            f"<td>{s['month']}</td><td>{s['units_sold']}</td><td>{s['cogs_per_unit']:.2f}</td>"
            f"<td>{s['fba_fee_per_unit']:.2f}</td><td>{s['amazon_fee_per_unit']:.2f}</td>"
            f"<td>{s['after_fees_per_unit']:.2f}</td><td>{s['net_per_unit']:.2f}</td>"
            f"<td>{s['pay_supplier_per_unit']:.2f}</td><td>{s['prep_per_unit']:.2f}</td>"
            f"<td>{s['ship_to_amz_per_unit']:.2f}</td><td>{s['po_id'] or ''}</td></tr>"
        )

    html = f"""
    <h1>Sales</h1>
    <div class='card'>
      <form class='flex' onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)" value="{month or ''}">
        <input id="y" placeholder="Year (YYYY)" value="{year or ''}">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class='card'>
      <h3>Import from Sellerboard/Amazon (JSON)</h3>
      <p>Через /api/sales/import можно загрузить массив records[]. Минимум: external_id, date (YYYY-MM-DD), asin, amount, type, party, units_sold.</p>
      <pre style="white-space:pre-wrap;background:#0f111a;border-radius:8px;padding:10px;border:1px solid #333;">
POST /api/sales/import
{{"records":[
  {{"external_id":"A1","date":"2025-10-28","asin":"B00XXXX","description":"Order #1","amount":19.99,"type":"Order","party":"Amazon","units_sold":1}}
]}}
</pre>

    </div>
    <div class='card'>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Date</th><th>ASIN</th><th>Description</th><th>Amount</th><th>TYPE</th><th>Party</th><th>Month</th>
            <th>Units sold</th><th>COGS</th><th>FBA</th><th>Amazon fee</th><th>AFTER FEES</th><th>NET per unit</th>
            <th>Payment to Supplier</th><th>Prep</th><th>Shipping to Amazon</th><th>PO</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <script>
    function goFilter(){ 
      const m=document.getElementById('m').value.trim(); 
      const y=document.getElementById('y').value.trim();
      const qs = new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
      location.href='/sales'+(qs.toString() ? ('?'+qs.toString()) : ''); 
      return false;
    }
    </script>
    """
    return HTMLResponse(render_layout("sales", html, "Sales"))

# ---------- API ----------
@app.post("/api/purchase-orders")
def api_po_create(body: POCreate, db: Session = Depends(get_db)):
    try:
        po = po_svc.create_purchase_order(db, body.model_dump())
        return {"ok": True, "po_id": po.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/purchase-orders")
def api_po_list(db: Session = Depends(get_db)):
    return po_svc.list_purchase_orders(db)

@app.patch("/api/purchase-orders/{po_id}/status")
def api_po_status(po_id: int, body: POStatusPatch, db: Session = Depends(get_db)):
    po = po_svc.set_po_status(db, po_id, body.status)
    return {"ok": True, "status": po.status.value}

@app.post("/api/po/labeling")
def api_po_labeling(body: LabelingIn, db: Session = Depends(get_db)):
    lc = po_svc.add_labeling_cost(db, body.po_item_id, body.note, body.cost_total)
    return {"ok": True, "labeling_id": lc.id}

# Accounting API
@app.get("/api/gl")
def api_gl_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return acc_svc.list_gl(db, month=month, year=year)

@app.post("/api/gl")
def api_gl_create(body: GLIn, db: Session = Depends(get_db)):
    try:
        r = acc_svc.create_gl(db, body.model_dump())
        return {"ok": True, "id": r.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/prepayments")
def api_prepayments_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return acc_svc.list_prepayments(db, month=month, year=year)

@app.post("/api/prepayments")
def api_prepayments_create(body: PrepaymentIn, db: Session = Depends(get_db)):
    try:
        r = acc_svc.create_prepayment(db, body.model_dump())
        return {"ok": True, "id": r.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/tb")
def api_tb(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return acc_svc.tb(db, month, year)

# Sales API
@app.get("/api/sales")
def api_sales_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return sales_svc.list_sales(db, month=month, year=year)

@app.post("/api/sales/import")
def api_sales_import(body: SalesImportIn, db: Session = Depends(get_db)):
    try:
        n = sales_svc.upsert_sales(db, body.records)
        return {"ok": True, "imported": n}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Admin
@app.post("/admin/init-db")
def admin_init_db():
    init_db()
    return {"ok": True, "message": "DB initialized"}
