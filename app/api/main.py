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


# ---------- layout ----------
def render_layout(active: str, content_html: str, title="AWM"):
    menu_items = [
        ("Dashboard", "/", "dashboard"),
        ("Purchase Orders", "/po", "po"),
        ("Label / Prep", "/label", "label"),
        ("Transportation Costs", "/transport", "transport"),
        ("Inventory", "/inventory", "inventory"),
    ]
    sidebar = ""
    for name, link, key in menu_items:
        cls = "active" if key == active else ""
        sidebar += f'<a href="{link}" class="menu-item {cls}">{name}</a>'

    return f"""
<!doctype html><html><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
body {{
  margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  background:#121212;color:#fff;display:flex;height:100vh;
}}
.sidebar{{width:240px;background:#1e1e1e;padding:20px;display:flex;flex-direction:column}}
.menu-item{{color:#bbb;text-decoration:none;padding:10px 0;display:block;border-left:3px solid transparent}}
.menu-item.active{{color:#fff;font-weight:600;border-left:3px solid #007bff}}
.menu-item:hover{{color:#fff}}
.content{{flex:1;overflow-y:auto;padding:20px 30px}}
.card{{background:#1e1e1e;border-radius:10px;padding:16px;margin-bottom:20px;box-shadow:0 0 10px rgba(0,0,0,.3)}}
table{{width:100%;border-collapse:collapse;color:#fff}}
th,td{{border-bottom:1px solid #333;padding:8px;text-align:left}}
th{{background:#2a2a2a}}
input,button,select{{background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px;padding:8px}}
button:hover{{background:#007bff;border-color:#007bff}}
</style></head>
<body>
  <div class="sidebar">
    <h2 style="color:#fff;margin-bottom:20px;">AWM</h2>
    {sidebar}
  </div>
  <div class="content">{content_html}</div>
</body></html>
"""


# ---------- страницы ----------
@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    html = """
    <h1>Dashboard</h1>
    <div class="card">
      <p>Добро пожаловать в Amazon Wholesale Manager.</p>
      <p>Используйте меню слева для навигации между разделами.</p>
    </div>
    """
    return HTMLResponse(render_layout("dashboard", html))


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


@app.post("/admin/init-db")
def admin_init_db():
    init_db()
    return {"ok": True, "message": "DB initialized"}
