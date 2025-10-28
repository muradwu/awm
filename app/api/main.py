from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db, init_db
from ..services import purchase_orders as po_svc

app = FastAPI(title="AWM API")


# ---------- авто-инициализация БД ----------
@app.on_event("startup")
def _startup_create_tables():
    # Создаст недостающие таблицы при каждом запуске
    init_db()


# ---------- request models ----------
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


class POStatusPatch(BaseModel):
    status: str  # NEW | CLOSED


class LabelingIn(BaseModel):
    po_item_id: int
    note: str | None = None
    cost_total: float


# ---------- pages ----------
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
</style></head><body>
  <nav style="display:flex;gap:12px;margin-bottom:12px">
    <a href="/">Dashboard</a><span style="color:#999">•</span><a href="/po">Purchase Orders</a>
  </nav>
  <h1>AWM — Dashboard</h1>
  <div class="card">
    <p>Use <b>Purchase Orders</b> to add orders and calculate COGS.</p>
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
    if(k==='class') e.className=v; else if(k==='html') e.innerHTML=v; else e.setAttribute(k,v);
  }
  for(const c of children){ if(typeof c==='string') e.appendChild(document.createTextNode(c)); else if(c) e.appendChild(c); }
  return e;
}
function itemRow(){
  const r=el('tr',{class:'item-row'});
  r.appendChild(el('td',{},el('input',{name:'asin',placeholder:'ASIN *',required:true,style:'width:120px'})));
  r.appendChild(el('td',{},el('input',{name:'title',placeholder:'Title *',required:true,style:'width:220px'})));
  r.appendChild(el('td',{},el('input',{name:'link',placeholder:'Amazon link',style:'width:200px'})));
  r.appendChild(el('td',{},el('input',{name:'mfr',placeholder:'MFR code',style:'width:120px'})));
  r.appendChild(el('td',{},el('input',{name:'qty',type:'number',min:'1',step:'1',value:'1',required:true,style:'width:80px'})));
  r.appendChild(el('td',{},el('input',{name:'price',type:'number',step:'0.0001',placeholder:'0.00',required:true,style:'width:90px'})));
  r.appendChild(el('td',{},el('input',{name:'tax',type:'number',step:'0.0001',placeholder:'Tax',style:'width:90px'})));
  r.appendChild(el('td',{},el('input',{name:'ship',type:'number',step:'0.0001',placeholder:'Ship',style:'width:90px'})));
  r.appendChild(el('td',{},el('input',{name:'disc',type:'number',step:'0.0001',value:'0',style:'width:90px'})));
  const rm=el('button',{type:'button',class:'btn danger'},'Remove'); rm.onclick=()=>r.remove();
  r.appendChild(el('td',{},rm));
  return r;
}
function collectItems(){
  const rows=document.querySelectorAll('.item-row'); const arr=[];
  for(const r of rows){
    const i=r.querySelectorAll('input');
    const obj={
      asin:i[0].value.trim(),
      listing_title:i[1].value.trim(),
      amazon_link:i[2].value.trim()||null,
      supplier_mfr_code:i[3].value.trim()||null,
      quantity:Number(i[4].value||0),
      purchase_price:Number((i[5].value||'0').replace(',','.')),
      sales_tax:i[6].value?Number((i[6].value).replace(',','.')):null,
      shipping:i[7].value?Number((i[7].value).replace(',','.')):null,
      discount:i[8].value?Number((i[8].value).replace(',','.')):0
    };
    if(!obj.asin||!obj.listing_title||!obj.quantity||!obj.purchase_price){ alert('Fill ASIN, Title, Qty, Price'); return null; }
    arr.push(obj);
  }
  return arr;
}
async function createPO(ev){
  ev.preventDefault();
  const f=new FormData(ev.target);
  const items=collectItems(); if(!items) return;
  const payload={
    supplier_name:f.get('supplier_name')||null,
    po_name:f.get('po_name'),
    invoice_number:f.get('invoice_number')||null,
    order_date:f.get('order_date')||null,
    sales_tax:Number((f.get('sales_tax')||'0').replace(',','.')),
    shipping:Number((f.get('shipping')||'0').replace(',','.')),
    discount:Number((f.get('discount')||'0').replace(',','.')),
    items
  };
  const r=await fetch(window.location.origin+'/api/purchase-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!r.ok){ const t=await r.text(); alert('Error creating PO: '+t); return; }
  await loadPOs(); ev.target.reset(); document.getElementById('items-body').innerHTML=''; addItem();
}
async function loadPOs(){
  const r=await fetch(window.location.origin+'/api/purchase-orders'); const data=await r.json();
  const tb=document.getElementById('tbody'); tb.innerHTML='';
  for(const x of data){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td class="mono">#${x.id}</td><td>${x.name}</td><td>${x.supplier??''}</td><td>${x.order_date?.split('T')[0]??''}</td><td><span class="badge">${x.status}</span></td><td class="right">${x.total_expense.toFixed(2)}</td><td><a href="/po/${x.id}">Open</a></td>`;
    tb.appendChild(tr);
  }
}
function addItem(){ document.getElementById('items-body').appendChild(itemRow()); }
window.addEventListener('DOMContentLoaded',()=>{ addItem(); loadPOs(); });
</script>
</head><body>
  <nav style="display:flex;gap:12px;margin-bottom:12px">
    <a href="/">Dashboard</a><span style="color:#999">•</span><a href="/po">Purchase Orders</a>
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
      <thead><tr><th>ID</th><th>PO name</th><th>Supplier</th><th>Date</th><th>Status</th><th class="right">Total Expense</th><th></th></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</body></html>
    """
    return HTMLResponse(html)


@app.get("/po/{po_id}", response_class=HTMLResponse)
def po_detail(po_id: int, db: Session = Depends(get_db)):
    po = po_svc.get_po_with_items(db, po_id)
    rows = ""
    for it in po.items:
        rows += f"<tr><td>{it.asin}</td><td>{it.listing_title}</td><td>{it.quantity}</td><td>{it.purchase_price:.4f}</td><td>{it.unit_cogs:.4f}</td><td class='mono'>{it.id}</td></tr>"
    html = f"""
<!doctype html><html><head><meta charset="utf-8"/>
<title>PO #{po.id}</title>
<style>
body{{font-family:system-ui,Segoe UI,Roboto;margin:20px}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
th,td{{border-bottom:1px solid #eee;padding:8px}}
th{{text-align:left;background:#fafafa}}
input,button{{padding:8px;border:1px solid #ddd;border-radius:8px}}
.card{{border:1px solid #eee;border-radius:12px;padding:12px;margin-bottom:12px}}
.mono{{font-family:ui-monospace,Menlo,Consolas,monospace}}
</style>
<script>
async function setStatus(status) {{
  await fetch('/api/purchase-orders/{po.id}/status', {{method:'PATCH', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{status}})}})
  location.reload();
}}
async function addLabeling(e){{
  e.preventDefault();
  const f=new FormData(e.target);
  const payload={{ po_item_id:Number(f.get('po_item_id')), note:f.get('note')||null, cost_total:Number(f.get('cost_total')) }};
  const r=await fetch('/api/po/labeling',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
  if(!r.ok){{alert('Error');return;}}
  location.reload();
}}
</script>
</head><body>
  <nav style="display:flex;gap:12px;margin-bottom:12px">
    <a href="/">Dashboard</a><span style="color:#999">•</span><a href="/po">Purchase Orders</a>
  </nav>
  <div class="card">
    <h2 style="margin:0">PO #{po.id} — {po.name} <span class="mono">[{po.status.value}]</span></h2>
    <div>Supplier: {po.supplier.name if po.supplier else ''}</div>
    <div>Date: {po.order_date.date()}</div>
    <div>Total expense: <b>{po.total_expense:.2f}</b> (subtotal {po.subtotal:.2f} + tax {po.sales_tax:.2f} + ship {po.shipping:.2f} - disc {po.discount:.2f} + labeling {po.labeling_total:.2f})</div>
    <div style="margin-top:8px;display:flex;gap:8px">
      <button onclick="setStatus('NEW')">Set NEW</button>
      <button onclick="setStatus('CLOSED')">Set CLOSED</button>
      <a href="/po" style="margin-left:auto">← Back</a>
    </div>
  </div>
  <div class="card">
    <h3 style="margin:0">Items</h3>
    <table><thead><tr><th>ASIN</th><th>Title</th><th>Qty</th><th>Price</th><th>Unit COGS</th><th>PO Item ID</th></tr></thead>
    <tbody>{rows}</tbody></table>
  </div>
  <div class="card">
    <h3 style="margin:0">Labeling / Prep</h3>
    <form onsubmit="addLabeling(event)">
      <div>PO Item ID: <input name="po_item_id" required></div>
      <div>Cost total: <input name="cost_total" required type="number" step="0.0001"></div>
      <div>Note: <input name="note"></div>
      <div style="margin-top:8px"><button type="submit">Add labeling</button></div>
    </form>
  </div>
</body></html>
    """
    return HTMLResponse(html)


# ---------- API ----------
@app.post("/api/purchase-orders")
def api_po_create(body: POCreate, db: Session = Depends(get_db)):
    try:
        po = po_svc.create_purchase_order(db, body.model_dump())
        return {"ok": True, "po_id": po.id}
    except Exception as e:
        # Вернём понятную ошибку вместо 500
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


# ---------- admin ----------
@app.post("/admin/run-seed")
def admin_run_seed(db: Session = Depends(get_db)):
    """Выполняет scripts/seed_demo.py без shell (Render Free)."""
    try:
        import importlib.util, sys
        from pathlib import Path
        base_dir = Path(__file__).resolve().parents[2]
        script = base_dir / "scripts" / "seed_demo.py"
        if not script.exists():
            raise RuntimeError("scripts/seed_demo.py not found")
        spec = importlib.util.spec_from_file_location("seed_demo", script)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["seed_demo"] = mod
        spec.loader.exec_module(mod)
        if hasattr(mod, "run"):
            mod.run(db)
        elif hasattr(mod, "main"):
            mod.main()
        else:
            raise RuntimeError("seed_demo has no run()/main()")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/init-db")
def admin_init_db():
    """Явно создать недостающие таблицы (idempotent)."""
    init_db()
    return {"ok": True, "message": "DB initialized (tables created if missing)"}
