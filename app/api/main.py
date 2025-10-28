from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..services import purchase_orders as po_svc
from ..db import get_db

app = FastAPI(title="AWM API")

# ---------- MODELS ----------

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
    order_date: str | None = None
    sales_tax: float | None = 0.0
    shipping: float | None = 0.0
    discount: float | None = 0.0
    items: list[POItemIn]

# ---------- ROUTES ----------

@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    html = """
<!doctype html><html><head><meta charset="utf-8"/>
<title>AWM — Dashboard</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto;margin:20px}
h1{margin-bottom:10px}
a{text-decoration:none;color:#007bff}
a:hover{text-decoration:underline}
.card{border:1px solid #ddd;border-radius:12px;padding:16px;margin-bottom:16px}
table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #eee;padding:8px;text-align:left}
th{background:#fafafa}
</style>
</head>
<body>
  <nav style="display:flex;gap:12px;margin-bottom:12px">
    <a href="/">Dashboard</a>
    <span style="color:#999">•</span>
    <a href="/po">Purchase Orders</a>
  </nav>

  <h1>AWM — Dashboard</h1>
  <div class="card">
    <p>This is your Amazon Wholesale Manager dashboard.</p>
    <p>Use the link above to manage Purchase Orders.</p>
  </div>
</body></html>
    """
    return HTMLResponse(html)


@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = r"""
<!doctype html><html><head><meta charset="utf-8"/>
<title>Purchase Orders</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto;margin:20px}
h1{margin-bottom:12px}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{border-bottom:1px solid #eee;padding:8px}
th{text-align:left;background:#fafafa}
input,button{padding:8px;border:1px solid #ddd;border-radius:8px}
.card{border:1px solid #eee;border-radius:12px;padding:12px;margin-bottom:12px}
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
  const e=document.createElement(tag);
  for(const [k,v] of Object.entries(attrs)){
    if(k==='class') e.className=v;
    else if(k==='html') e.innerHTML=v;
    else e.setAttribute(k,v);
  }
  for(const c of children){if(typeof c==='string') e.appendChild(document.createTextNode(c)); else if(c) e.appendChild(c);}
  return e;
}

function itemRow(){
  const row = el('tr',{class:'item-row'});
  row.appendChild(el('td',{},el('input',{name:'asin',placeholder:'ASIN *',required:true,style:'width:120px'})));
  row.appendChild(el('td',{},el('input',{name:'title',placeholder:'Title *',required:true,style:'width:220px'})));
  row.appendChild(el('td',{},el('input',{name:'link',placeholder:'Amazon link',style:'width:200px'})));
  row.appendChild(el('td',{},el('input',{name:'mfr',placeholder:'MFR code',style:'width:120px'})));
  row.appendChild(el('td',{},el('input',{name:'qty',type:'number',min:'1',step:'1',value:'1',required:true,style:'width:80px'})));
  row.appendChild(el('td',{},el('input',{name:'price',type:'number',step:'0.0001',placeholder:'0.00',required:true,style:'width:80px'})));
  row.appendChild(el('td',{},el('input',{name:'tax',type:'number',step:'0.0001',placeholder:'Tax',style:'width:80px'})));
  row.appendChild(el('td',{},el('input',{name:'ship',type:'number',step:'0.0001',placeholder:'Ship',style:'width:80px'})));
  row.appendChild(el('td',{},el('input',{name:'disc',type:'number',step:'0.0001',value:'0',style:'width:80px'})));
  const rm = el('button',{type:'button',class:'btn danger'},'Remove');
  rm.onclick=()=>row.remove();
  row.appendChild(el('td',{},rm));
  return row;
}

function collectItems(){
  const rows=document.querySelectorAll('.item-row');
  const items=[];
  for(const r of rows){
    const i=r.querySelectorAll('input');
    if(!i[0].value.trim()||!i[1].value.trim()) continue;
    items.push({
      asin:i[0].value.trim(),
      listing_title:i[1].value.trim(),
      amazon_link:i[2].value.trim()||null,
      supplier_mfr_code:i[3].value.trim()||null,
      quantity:Number(i[4].value||0),
      purchase_price:Number(i[5].value||0),
      sales_tax:i[6].value?Number(i[6].value):null,
      shipping:i[7].value?Number(i[7].value):null,
      discount:i[8].value?Number(i[8].value):0
    });
  }
  return items;
}

async function createPO(ev){
  ev.preventDefault();
  const f=new FormData(ev.target);
  const items=collectItems();
  if(items.length===0){alert('Add at least one item');return;}
  const payload={
    supplier_name:f.get('supplier_name'),
    po_name:f.get('po_name'),
    invoice_number:f.get('invoice_number'),
    order_date:f.get('order_date'),
    sales_tax:Number(f.get('sales_tax')||0),
    shipping:Number(f.get('shipping')||0),
    discount:Number(f.get('discount')||0),
    items
  };
  const r=await fetch(window.location.origin+'/api/purchase-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!r.ok){const t=await r.text();alert('Error creating PO: '+t);return;}
  await loadPOs();
  ev.target.reset();
  document.getElementById('items-body').innerHTML='';
  addItem();
}

async function loadPOs(){
  const r=await fetch(window.location.origin+'/api/purchase-orders');
  const data=await r.json();
  const tb=document.getElementById('tbody');
  tb.innerHTML='';
  for(const x of data){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="mono">#${x.id}</td><td>${x.name}</td><td>${x.supplier??''}</td><td>${x.order_date?.split('T')[0]??''}</td><td>${x.status}</td><td class="right">${x.total_expense.toFixed(2)}</td>`;
    tb.appendChild(tr);
  }
}

function addItem(){
  document.getElementById('items-body').appendChild(itemRow());
}

window.addEventListener('DOMContentLoaded',()=>{
  addItem();
  loadPOs();
});
</script>
</head><body>
  <nav style="display:flex;gap:12px;margin-bottom:12px">
    <a href="/">Dashboard</a>
    <span style="color:#999">•</span>
    <a href="/po">Purchase Orders</a>
  </nav>

  <h1>Purchase Orders</h1>

  <div class="card">
    <h3>New Purchase Order</h3>
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
          <thead><tr>
            <th>ASIN *</th><th>Title *</th><th>Amazon link</th><th>MFR</th><th>Qty *</th><th>Price *</th><th>Tax</th><th>Ship</th><th>Discount</th><th></th>
          </tr></thead>
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
    <h3>All Purchase Orders</h3>
    <table>
      <thead><tr><th>ID</th><th>PO name</th><th>Supplier</th><th>Date</th><th>Status</th><th class="right">Total</th></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</body></html>
    """
    return HTMLResponse(html)

# ---------- API ----------

@app.post("/api/purchase-orders")
def api_po_create(body: POCreate, db: Session = Depends(get_db)):
    po = po_svc.create_purchase_order(db, body.model_dump())
    return {"ok": True, "po_id": po.id}

@app.get("/api/purchase-orders")
def api_po_list(db: Session = Depends(get_db)):
    return po_svc.list_purchase_orders(db)
