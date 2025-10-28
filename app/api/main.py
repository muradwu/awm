from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db, init_db
from ..services import purchase_orders as po_svc
from ..services import accounting as acc_svc
from ..services import sales as sales_svc
from ..models import PurchaseOrderItem  # для /api/po/items

app = FastAPI(title="AWM API")

# ---------- авто-инициализация БД ----------
@app.on_event("startup")
def _startup_create_tables():
    init_db()


# ---------- Pydantic-модели запросов ----------
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
    status: str  # NEW | CLOSED

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


# ---------- Общий layout (чёрная тема, меню слева) ----------
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
        else:
            cls = "menu-item active" if key == active else "menu-item"
            sidebar += f'<a href="{link}" class="{cls}">{name}</a>'

    return """
<!doctype html><html><head><meta charset="utf-8"/>
<title>""" + title + """</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       background:#121212; color:#fff; display:flex; height:100vh; }
.sidebar { width:260px; background:#1e1e1e; padding:20px; display:flex; flex-direction:column; }
.menu-item { color:#bbb; text-decoration:none; padding:10px 0; display:block; border-left:3px solid transparent; }
.menu-item.active { color:#fff; font-weight:600; border-left:3px solid #007bff; }
.menu-item:hover { color:#fff; }
.content { flex:1; overflow-y:auto; padding:20px 30px; }
.card { background:#1e1e1e; border-radius:10px; padding:16px; margin-bottom:20px; box-shadow:0 0 10px rgba(0,0,0,.3); }
.table-wrap { width:100%; overflow:auto; }
table { width:100%; border-collapse:collapse; color:#fff; min-width:900px; }
th,td { border-bottom:1px solid #333; padding:8px; text-align:left; white-space:nowrap; }
th { background:#2a2a2a; position:sticky; top:0; }
input,button,select,textarea { background:#2a2a2a; color:#fff; border:1px solid #444; border-radius:6px; padding:8px; }
button:hover { background:#007bff; border-color:#007bff; }
.row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.badge { background:#222; border:1px solid #444; border-radius:999px; padding:2px 8px; }
</style>
</head>
<body>
  <div class="sidebar">
    <h2 style="color:#fff;margin-bottom:20px;">AWM</h2>
    """ + sidebar + """
  </div>
  <div class="content">
    """ + content_html + """
  </div>
</body></html>
"""


# ---------- Pages (все страницы наполняются данными через JS с API) ----------
@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    html = """
    <h1>Dashboard</h1>
    <div class="card">
      <p>Добро пожаловать в Amazon Wholesale Manager.</p>
      <p>Используйте левое меню: PO, Label/Prep, Transport, Inventory, Accounting (GL/Prepayments/TB), Sales.</p>
    </div>
    """
    return HTMLResponse(render_layout("dashboard", html))


@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = """
    <h1>Purchase Orders</h1>
    <div class="card">
      <h3>New Purchase Order</h3>
      <form id="poForm" onsubmit="return createPO(event)">
        <div class="row">
          <input name='supplier_name' placeholder='Supplier name'>
          <input name='po_name' placeholder='PO name *' required>
          <input name='invoice_number' placeholder='Invoice #'>
          <input name='order_date' type='date'>
          <input name='sales_tax' placeholder='Sales Tax'>
          <input name='shipping' placeholder='Shipping'>
          <input name='discount' placeholder='Discount'>
        </div>

        <div style="margin-top:15px;border-top:1px solid #333;padding-top:10px;">
          <h4>Items</h4>
          <div class="table-wrap">
            <table id='itemsTbl'>
              <thead><tr><th>ASIN *</th><th>Title *</th><th>Qty</th><th>Price</th><th></th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <button type="button" onclick="addItem()">+ Add ASIN</button>
        </div>

        <div style="margin-top:10px;">
          <button type='submit'>Create PO</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3>All Purchase Orders</h3>
      <div class="table-wrap">
        <table id='tbl'>
          <thead><tr><th>ID</th><th>Name</th><th>Supplier</th><th>Date</th><th>Status</th><th>Total</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
function addItem(){
  const tb=document.querySelector("#itemsTbl tbody");
  const tr=document.createElement("tr");
  tr.innerHTML='<td><input name="asin" placeholder="ASIN" required></td>'
              +'<td><input name="title" placeholder="Title" required></td>'
              +'<td><input name="qty" type="number" min="1" step="1" value="1"></td>'
              +'<td><input name="price" type="number" step="0.01" value="0"></td>'
              +'<td><button type="button" onclick="this.closest(\\'tr\\').remove()">🗑</button></td>';
  tb.appendChild(tr);
}
function collectItems(){
  const rows=document.querySelectorAll("#itemsTbl tbody tr");
  const arr=[];
  for(const r of rows){
    const asin=r.querySelector('input[name="asin"]').value.trim();
    const title=r.querySelector('input[name="title"]').value.trim();
    const qty=Number(r.querySelector('input[name="qty"]').value||0);
    const price=Number(r.querySelector('input[name="price"]').value||0);
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
  if(payload.items.length===0){alert("Add at least one ASIN");return false;}
  const r=await fetch('/api/purchase-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(r.ok){alert('PO created');loadPOs();e.target.reset();document.querySelector("#itemsTbl tbody").innerHTML='';addItem();}
  else alert(await r.text());
  return false;
}
async function loadPOs(){
  const r=await fetch('/api/purchase-orders');const data=await r.json();
  const tb=document.querySelector('#tbl tbody');tb.innerHTML='';
  for(const po of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+po.id+'</td><td>'+po.name+'</td><td>'+(po.supplier||'')+'</td>'
                +'<td>'+(po.order_date?po.order_date.split('T')[0]:'')+'</td><td>'+po.status+'</td>'
                +'<td>'+Number(po.total_expense||0).toFixed(2)+'</td>';
    tb.appendChild(tr);
  }
}
loadPOs();addItem();
</script>
    """
    return HTMLResponse(render_layout("po", html, "Purchase Orders"))


@app.get("/label", response_class=HTMLResponse)
def label_page():
    html = """
    <h1>Label / Prep</h1>
    <div class="card">
      <div class="table-wrap">
        <table id="labelTbl">
          <thead><tr><th>PO Item ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Price</th><th>Prep center</th><th>Prep cost (total)</th><th></th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
async function loadItems(){
  const r=await fetch('/api/po/items'); const data=await r.json();
  const tb=document.querySelector('#labelTbl tbody'); tb.innerHTML='';
  for(const it of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
                +'<td>'+it.quantity+'</td><td>'+Number(it.purchase_price||0).toFixed(2)+'</td>'
                +'<td><input data-k="note" placeholder="Prep center"></td>'
                +'<td><input data-k="cost_total" type="number" step="0.01" placeholder="0.00"></td>'
                +'<td><button type="button" class="save-btn">Save</button></td>';
    tb.appendChild(tr);
  }
  tb.querySelectorAll('.save-btn').forEach(btn=>{
    btn.addEventListener('click', async (e)=>{
      const tr=e.target.closest('tr');
      const id=Number(tr.children[0].textContent);
      const note=tr.querySelector('input[data-k="note"]').value||null;
      const cost_total=parseFloat(tr.querySelector('input[data-k="cost_total"]').value||0);
      const body={po_item_id:id, note:note, cost_total:cost_total};
      const rr=await fetch('/api/po/labeling',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!rr.ok) alert(await rr.text()); else alert('Saved');
    });
  });
}
loadItems();
</script>
    """
    return HTMLResponse(render_layout("label", html, "Label / Prep"))


@app.get("/transport", response_class=HTMLResponse)
def transport_page():
    html = """
    <h1>Transportation Costs</h1>
    <div class="card">
      <div class="table-wrap">
        <table id="transTbl">
          <thead><tr><th>PO Item ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Price</th><th>Shipping to FBA (total)</th><th>Note</th><th></th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <p class="badge">Примечание: пока транспортные расходы сохраняются как отдельные записи в LabelingCost с note="transport" и учитываются в COGS (как и prep).</p>
    </div>

<script>
async function loadItems(){
  const r=await fetch('/api/po/items'); const data=await r.json();
  const tb=document.querySelector('#transTbl tbody'); tb.innerHTML='';
  for(const it of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
                +'<td>'+it.quantity+'</td><td>'+Number(it.purchase_price||0).toFixed(2)+'</td>'
                +'<td><input data-k="cost_total" type="number" step="0.01" placeholder="0.00"></td>'
                +'<td><input data-k="note" placeholder="transport"></td>'
                +'<td><button type="button" class="save-btn">Save</button></td>';
    tb.appendChild(tr);
  }
  tb.querySelectorAll('.save-btn').forEach(btn=>{
    btn.addEventListener('click', async (e)=>{
      const tr=e.target.closest('tr');
      const id=Number(tr.children[0].textContent);
      const cost_total=parseFloat(tr.querySelector('input[data-k="cost_total"]').value||0);
      let note=tr.querySelector('input[data-k="note"]').value||'transport';
      const body={po_item_id:id, note:note, cost_total:cost_total};
      // используем тот же эндпоинт labeling: это попадёт в COGS
      const rr=await fetch('/api/po/labeling',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!rr.ok) alert(await rr.text()); else alert('Saved');
    });
  });
}
loadItems();
</script>
    """
    return HTMLResponse(render_layout("transport", html, "Transportation Costs"))


@app.get("/inventory", response_class=HTMLResponse)
def inventory_page():
    html = """
    <h1>Inventory</h1>
    <div class="card">
      <div class="table-wrap">
        <table id="invTbl">
          <thead><tr><th>PO Item ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Unit COGS</th><th>Total Cost</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
async function loadItems(){
  const r=await fetch('/api/po/items'); const data=await r.json();
  const tb=document.querySelector('#invTbl tbody'); tb.innerHTML='';
  for(const it of data){
    const unit=Number(it.unit_cogs||0);
    const total=unit*Number(it.quantity||0);
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
                +'<td>'+it.quantity+'</td><td>'+unit.toFixed(4)+'</td><td>'+total.toFixed(2)+'</td>';
    tb.appendChild(tr);
  }
}
loadItems();
</script>
    """
    return HTMLResponse(render_layout("inventory", html, "Inventory"))


@app.get("/accounting/gl", response_class=HTMLResponse)
def accounting_gl_page():
    html = """
    <h1>Accounting — GL</h1>
    <div class="card">
      <form class="row" onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)">
        <input id="y" placeholder="Year (YYYY)">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class="card">
      <h3>New GL Transaction</h3>
      <form id="glForm" onsubmit="return createGL(event)">
        <div class="row">
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
        </div>
      </form>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="glTbl">
          <thead><tr><th>Date</th><th>NC</th><th>Account</th><th>Ref</th><th>Description</th><th>Amount</th><th>Dr</th><th>Cr</th><th>Value</th><th>Period</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
function goFilter(){
  const m=document.getElementById('m').value.trim();
  const y=document.getElementById('y').value.trim();
  loadGL(m||null, y||null);
  return false;
}
async function loadGL(m,y){
  const qs=new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
  const r=await fetch('/api/gl'+(qs.toString()?('?'+qs.toString()):'')); const data=await r.json();
  const tb=document.querySelector('#glTbl tbody'); tb.innerHTML='';
  for(const r of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+r.date.slice(0,10)+'</td><td>'+r.nc_code+'</td><td>'+r.account_name+'</td>'
                +'<td>'+(r.reference||'')+'</td><td>'+(r.description||'')+'</td>'
                +'<td>'+Number(r.amount||0).toFixed(2)+'</td><td>'+Number(r.dr||0).toFixed(2)+'</td>'
                +'<td>'+Number(r.cr||0).toFixed(2)+'</td><td>'+Number(r.value||0).toFixed(2)+'</td>'
                +'<td>'+r.month+'/'+r.year+'</td>';
    tb.appendChild(tr);
  }
}
async function createGL(e){
  e.preventDefault();
  const f=new FormData(e.target);
  const body=Object.fromEntries(f.entries());
  for(const k of ['amount','dr','cr','value']) body[k]=parseFloat(body[k]||0);
  if(body.month) body.month=parseInt(body.month); if(body.year) body.year=parseInt(body.year);
  const r=await fetch('/api/gl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok) return alert(await r.text());
  e.target.reset(); loadGL();
}
loadGL();
</script>
    """
    return HTMLResponse(render_layout("gl", html, "Accounting — GL"))


@app.get("/accounting/prepayments", response_class=HTMLResponse)
def accounting_prepayments_page():
    html = """
    <h1>Accounting — Prepayments</h1>
    <div class="card">
      <form class="row" onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)">
        <input id="y" placeholder="Year (YYYY)">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class="card">
      <h3>New Prepayment</h3>
      <form onsubmit="return createPP(event)">
        <div class="row">
          <input name="date" type="date">
          <input name="party" placeholder="Party *" required>
          <input name="description" placeholder="Description">
          <input name="amount" placeholder="Amount">
          <input name="balance" placeholder="Balance">
          <input name="month" placeholder="Month">
          <input name="year" placeholder="Year">
          <button type="submit">Add</button>
        </div>
      </form>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="ppTbl">
          <thead><tr><th>Date</th><th>Party</th><th>Description</th><th>Amount</th><th>Balance</th><th>Period</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
function goFilter(){
  const m=document.getElementById('m').value.trim();
  const y=document.getElementById('y').value.trim();
  loadPP(m||null, y||null);
  return false;
}
async function loadPP(m,y){
  const qs=new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
  const r=await fetch('/api/prepayments'+(qs.toString()?('?'+qs.toString()):'')); const data=await r.json();
  const tb=document.querySelector('#ppTbl tbody'); tb.innerHTML='';
  for(const x of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+x.date.slice(0,10)+'</td><td>'+x.party+'</td><td>'+(x.description||'')+'</td>'
                +'<td>'+Number(x.amount||0).toFixed(2)+'</td><td>'+Number(x.balance||0).toFixed(2)+'</td>'
                +'<td>'+x.month+'/'+x.year+'</td>';
    tb.appendChild(tr);
  }
}
async function createPP(e){
  e.preventDefault();
  const f=new FormData(e.target);
  const body=Object.fromEntries(f.entries());
  for(const k of ['amount','balance']) body[k]=parseFloat(body[k]||0);
  if(body.month) body.month=parseInt(body.month); if(body.year) body.year=parseInt(body.year);
  const r=await fetch('/api/prepayments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok) return alert(await r.text());
  e.target.reset(); loadPP();
}
loadPP();
</script>
    """
    return HTMLResponse(render_layout("prepayments", html, "Accounting — Prepayments"))


@app.get("/accounting/tb", response_class=HTMLResponse)
def accounting_tb_page():
    html = """
    <h1>Accounting — Trial Balance</h1>
    <div class="card">
      <form class="row" onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)">
        <input id="y" placeholder="Year (YYYY)">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="tbTbl">
          <thead><tr><th>Account</th><th>Dr</th><th>Cr</th><th>Value</th><th>Balance (Dr-Cr)</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
function goFilter(){
  const m=document.getElementById('m').value.trim();
  const y=document.getElementById('y').value.trim();
  loadTB(m||null, y||null);
  return false;
}
async function loadTB(m,y){
  const qs=new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
  const r=await fetch('/api/tb'+(qs.toString()?('?'+qs.toString()):'')); const data=await r.json();
  const tb=document.querySelector('#tbTbl tbody'); tb.innerHTML='';
  for(const x of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+x.account+'</td><td>'+Number(x.dr||0).toFixed(2)+'</td>'
                +'<td>'+Number(x.cr||0).toFixed(2)+'</td><td>'+Number(x.value||0).toFixed(2)+'</td>'
                +'<td>'+Number(x.balance||0).toFixed(2)+'</td>';
    tb.appendChild(tr);
  }
}
loadTB();
</script>
    """
    return HTMLResponse(render_layout("tb", html, "Accounting — TB"))


@app.get("/sales", response_class=HTMLResponse)
def sales_page():
    html = """
    <h1>Sales</h1>
    <div class="card">
      <form class="row" onsubmit="return goFilter()">
        <input id="m" placeholder="Month (1-12)">
        <input id="y" placeholder="Year (YYYY)">
        <button type="submit">Filter</button>
      </form>
    </div>
    <div class="card">
      <h3>Import from Sellerboard/Amazon (JSON)</h3>
      <p>Через <code>POST /api/sales/import</code> можно загрузить массив records[]. Минимум: <b>external_id</b>, <b>date</b> (YYYY-MM-DD), <b>asin</b>, <b>amount</b>, <b>type</b>, <b>party</b>, <b>units_sold</b>.</p>
      <pre style="white-space:pre-wrap;background:#0f111a;border-radius:8px;padding:10px;border:1px solid #333;">
POST /api/sales/import
{"records":[
  {"external_id":"A1","date":"2025-10-28","asin":"B00XXXX","description":"Order #1","amount":19.99,"type":"Order","party":"Amazon","units_sold":1}
]}
      </pre>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="salesTbl">
          <thead>
            <tr>
              <th>ID</th><th>Date</th><th>ASIN</th><th>Description</th><th>Amount</th><th>TYPE</th><th>Party</th><th>Month</th>
              <th>Units sold</th><th>COGS</th><th>FBA</th><th>Amazon fee</th><th>AFTER FEES</th><th>NET per unit</th>
              <th>Payment to Supplier</th><th>Prep</th><th>Shipping to Amazon</th><th>PO</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

<script>
function goFilter(){
  const m=document.getElementById('m').value.trim();
  const y=document.getElementById('y').value.trim();
  loadSales(m||null, y||null);
  return false;
}
async function loadSales(m,y){
  const qs=new URLSearchParams(); if(m) qs.set('month',m); if(y) qs.set('year',y);
  const r=await fetch('/api/sales'+(qs.toString()?('?'+qs.toString()):'')); const data=await r.json();
  const tb=document.querySelector('#salesTbl tbody'); tb.innerHTML='';
  for(const s of data){
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+s.id+'</td><td>'+s.date.slice(0,10)+'</td><td>'+s.asin+'</td><td>'+(s.description||'')+'</td>'
                +'<td>'+Number(s.amount||0).toFixed(2)+'</td><td>'+(s.type||'')+'</td><td>'+(s.party||'')+'</td>'
                +'<td>'+s.month+'</td><td>'+s.units_sold+'</td><td>'+Number(s.cogs_per_unit||0).toFixed(2)+'</td>'
                +'<td>'+Number(s.fba_fee_per_unit||0).toFixed(2)+'</td><td>'+Number(s.amazon_fee_per_unit||0).toFixed(2)+'</td>'
                +'<td>'+Number(s.after_fees_per_unit||0).toFixed(2)+'</td><td>'+Number(s.net_per_unit||0).toFixed(2)+'</td>'
                +'<td>'+Number(s.pay_supplier_per_unit||0).toFixed(2)+'</td><td>'+Number(s.prep_per_unit||0).toFixed(2)+'</td>'
                +'<td>'+Number(s.ship_to_amz_per_unit||0).toFixed(2)+'</td><td>'+(s.po_id||'')+'</td>';
    tb.appendChild(tr);
  }
}
loadSales();
</script>
    """
    return HTMLResponse(render_layout("sales", html, "Sales"))


# ---------- API: Purchase Orders ----------
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

@app.get("/api/po/items")
def api_po_items(db: Session = Depends(get_db)):
    items = db.query(PurchaseOrderItem).all()
    out = []
    for it in items:
        out.append({
            "id": it.id,
            "po_id": it.po_id,
            "asin": it.asin,
            "listing_title": it.listing_title,
            "quantity": it.quantity,
            "purchase_price": it.purchase_price,
            "unit_cogs": it.unit_cogs or 0.0,
        })
    return out

@app.post("/api/po/labeling")
def api_po_labeling(body: LabelingIn, db: Session = Depends(get_db)):
    lc = po_svc.add_labeling_cost(db, body.po_item_id, body.note, body.cost_total)
    return {"ok": True, "labeling_id": lc.id}

# Доп. эндпоинт для "Transportation" — используем ту же таблицу LabelingCost (note="transport")
@app.post("/api/po/transport")
def api_po_transport(body: LabelingIn, db: Session = Depends(get_db)):
    note = body.note or "transport"
    lc = po_svc.add_labeling_cost(db, body.po_item_id, note, body.cost_total)
    return {"ok": True, "transport_id": lc.id}


# ---------- API: Accounting ----------
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


# ---------- API: Sales ----------
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


# ---------- Admin ----------
@app.post("/admin/init-db")
def admin_init_db():
    init_db()
    return {"ok": True, "message": "DB initialized"}
