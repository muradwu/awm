from __future__ import annotations
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db, init_db
from ..services import purchase_orders as po_svc
from ..services import accounting as acc_svc
from ..services import sales as sales_svc
from ..models import PurchaseOrderItem

app = FastAPI(title="AWM API")

@app.on_event("startup")
def _startup_create_tables():
    init_db()

# ---------- Pydantic models ----------
class POItemIn(BaseModel):
    asin: str
    listing_title: str
    amazon_link: str | None = None
    supplier_mfr_code: str | None = None
    quantity: int
    purchase_price: float

class POCreate(BaseModel):
    supplier_name: str | None = None
    po_name: str
    invoice_number: str | None = None
    order_date: str | None = None
    sales_tax: float | None = 0.0
    shipping: float | None = 0.0
    discount: float | None = 0.0
    items: list[POItemIn]

class LabelingIn(BaseModel):
    po_item_id: int
    note: str | None = None
    cost_total: float

# ---------- Layout ----------
def render_layout(active: str, content_html: str, title="AWM"):
    menu = [
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
    for name, link, key in menu:
        if key == "sep":
            sidebar += '<div style="border-top:1px solid #2a2a2a;margin:12px 0;"></div>'
        else:
            cls = "menu-item active" if key == active else "menu-item"
            sidebar += f'<a href="{link}" class="{cls}">{name}</a>'
    return f"""
<!doctype html><html><head><meta charset='utf-8'/>
<title>{title}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#121212;color:#fff;display:flex;height:100vh;}}
.sidebar{{width:260px;background:#1e1e1e;padding:20px;display:flex;flex-direction:column}}
.menu-item{{color:#bbb;text-decoration:none;padding:10px 0;display:block;border-left:3px solid transparent}}
.menu-item.active{{color:#fff;font-weight:600;border-left:3px solid #007bff}}
.menu-item:hover{{color:#fff}}
.content{{flex:1;overflow-y:auto;padding:20px 30px}}
.card{{background:#1e1e1e;border-radius:10px;padding:16px;margin-bottom:20px;
box-shadow:0 0 10px rgba(0,0,0,.3)}}
.table-wrap{{width:100%;overflow:auto}}
table{{width:100%;border-collapse:collapse;color:#fff;min-width:900px}}
th,td{{border-bottom:1px solid #333;padding:8px;text-align:left;white-space:nowrap}}
th{{background:#2a2a2a;position:sticky;top:0}}
input,button,select,textarea{{background:#2a2a2a;color:#fff;border:1px solid #444;
border-radius:6px;padding:8px}}
button:hover{{background:#007bff;border-color:#007bff}}
.row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.badge{{background:#222;border:1px solid #444;border-radius:999px;padding:2px 8px}}
</style></head><body>
<div class='sidebar'><h2 style='color:#fff;margin-bottom:20px;'>AWM</h2>{sidebar}</div>
<div class='content'>{content_html}</div></body></html>
"""

# ---------- Dashboard ----------
@app.get("/", response_class=HTMLResponse)
def dashboard_page():
    html = """
    <h1>Dashboard</h1>
    <div class='card'>
      <p>Добро пожаловать в Amazon Wholesale Manager.</p>
      <p>Используйте левое меню для навигации.</p>
    </div>
    """
    return HTMLResponse(render_layout("dashboard", html))

# ---------- Purchase Orders ----------
@app.get("/po", response_class=HTMLResponse)
def po_page():
    html = """
<h1>Purchase Orders</h1>
<div class='card'>
<h3>New Purchase Order</h3>
<form id='poForm' onsubmit='return createPO(event)'>
<div class='row'>
<input name='supplier_name' placeholder='Supplier name'>
<input name='po_name' placeholder='PO name *' required>
<input name='invoice_number' placeholder='Invoice #'>
<input name='order_date' type='date'>
<input name='sales_tax' placeholder='Sales Tax'>
<input name='shipping' placeholder='Shipping'>
<input name='discount' placeholder='Discount'>
</div>
<div style='margin-top:15px;border-top:1px solid #333;padding-top:10px;'>
<h4>Items</h4>
<div class='table-wrap'><table id='itemsTbl'>
<thead><tr><th>ASIN *</th><th>Title *</th><th>Qty</th><th>Price</th><th></th></tr></thead><tbody></tbody>
</table></div>
<button type='button' onclick='addItem()'>+ Add ASIN</button>
</div>
<div style='margin-top:10px;'><button type='submit'>Create PO</button></div>
</form></div>
<div class='card'><h3>All Purchase Orders</h3>
<div class='table-wrap'><table id='tbl'>
<thead><tr><th>ID</th><th>Name</th><th>Supplier</th><th>Date</th><th>Status</th><th>Total</th></tr></thead>
<tbody></tbody></table></div></div>
<script>
function addItem(){
const tb=document.querySelector("#itemsTbl tbody");
const tr=document.createElement("tr");
tr.innerHTML='<td><input name="asin" required></td>'
+'<td><input name="title" required></td>'
+'<td><input name="qty" type="number" min="1" step="1" value="1"></td>'
+'<td><input name="price" type="number" step="0.01" value="0"></td>'
+'<td><button type="button" onclick="this.closest(\\'tr\\').remove()">🗑</button></td>';
tb.appendChild(tr);
}
function collectItems(){
const rows=document.querySelectorAll("#itemsTbl tbody tr");const arr=[];
for(const r of rows){
const asin=r.querySelector('input[name="asin"]').value.trim();
const title=r.querySelector('input[name="title"]').value.trim();
const qty=Number(r.querySelector('input[name="qty"]').value||0);
const price=Number(r.querySelector('input[name="price"]').value||0);
if(!asin||!title)continue;
arr.push({asin,listing_title:title,quantity:qty,purchase_price:price});
}return arr;}
async function createPO(e){
e.preventDefault();const f=new FormData(e.target);
const payload={supplier_name:f.get('supplier_name')||null,
po_name:f.get('po_name'),invoice_number:f.get('invoice_number')||null,
order_date:f.get('order_date')||null,sales_tax:parseFloat(f.get('sales_tax')||0),
shipping:parseFloat(f.get('shipping')||0),discount:parseFloat(f.get('discount')||0),
items:collectItems()};
if(payload.items.length===0){alert("Add at least one ASIN");return false;}
const r=await fetch('/api/purchase-orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
if(r.ok){alert('PO created');loadPOs();e.target.reset();document.querySelector("#itemsTbl tbody").innerHTML='';addItem();}
else alert(await r.text());return false;}
async function loadPOs(){
const r=await fetch('/api/purchase-orders');const data=await r.json();
const tb=document.querySelector('#tbl tbody');tb.innerHTML='';
for(const po of data){
const tr=document.createElement('tr');
tr.innerHTML='<td>'+po.id+'</td><td>'+po.name+'</td><td>'+(po.supplier||'')+'</td>'
+'<td>'+(po.order_date?po.order_date.split('T')[0]:'')+'</td><td>'+po.status+'</td>'
+'<td>'+Number(po.total_expense||0).toFixed(2)+'</td>';tb.appendChild(tr);}
}
loadPOs();addItem();
</script>
"""
    return HTMLResponse(render_layout("po", html, "Purchase Orders"))

# ---------- Label / Prep ----------
@app.get("/label", response_class=HTMLResponse)
def label_page():
    html = """
<h1>Label / Prep</h1>
<div class='card'><div class='table-wrap'><table id='labelTbl'>
<thead><tr><th>ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Price</th><th>Prep center</th><th>Prep cost</th><th></th></tr></thead><tbody></tbody></table></div></div>
<script>
async function loadItems(){
const r=await fetch('/api/po/items');const data=await r.json();
const tb=document.querySelector('#labelTbl tbody');tb.innerHTML='';
for(const it of data){
const tr=document.createElement('tr');
tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
+'<td>'+it.quantity+'</td><td>'+Number(it.purchase_price||0).toFixed(2)+'</td>'
+'<td><input data-k="note" placeholder="Prep center"></td>'
+'<td><input data-k="cost_total" type="number" step="0.01" placeholder="0.00"></td>'
+'<td><button type="button" class="save-btn">Save</button></td>';tb.appendChild(tr);}
tb.querySelectorAll('.save-btn').forEach(b=>b.addEventListener('click',async e=>{
const tr=e.target.closest('tr');const id=Number(tr.children[0].textContent);
const note=tr.querySelector('[data-k="note"]').value||null;
const cost_total=parseFloat(tr.querySelector('[data-k="cost_total"]').value||0);
const rr=await fetch('/api/po/labeling',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({po_item_id:id,note:note,cost_total:cost_total})});
if(!rr.ok)alert(await rr.text());else alert('Saved');}));
}
loadItems();
</script>"""
    return HTMLResponse(render_layout("label", html, "Label / Prep"))

# ---------- Transportation ----------
@app.get("/transport", response_class=HTMLResponse)
def transport_page():
    html = """
<h1>Transportation Costs</h1>
<div class='card'><div class='table-wrap'><table id='transTbl'>
<thead><tr><th>ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Price</th><th>Shipping to FBA</th><th>Note</th><th></th></tr></thead><tbody></tbody></table></div></div>
<script>
async function loadItems(){
const r=await fetch('/api/po/items');const data=await r.json();
const tb=document.querySelector('#transTbl tbody');tb.innerHTML='';
for(const it of data){
const tr=document.createElement('tr');
tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
+'<td>'+it.quantity+'</td><td>'+Number(it.purchase_price||0).toFixed(2)+'</td>'
+'<td><input data-k="cost_total" type="number" step="0.01"></td>'
+'<td><input data-k="note" placeholder="transport"></td>'
+'<td><button type="button" class="save-btn">Save</button></td>';tb.appendChild(tr);}
tb.querySelectorAll('.save-btn').forEach(b=>b.addEventListener('click',async e=>{
const tr=e.target.closest('tr');const id=Number(tr.children[0].textContent);
const note=tr.querySelector('[data-k="note"]').value||'transport';
const cost_total=parseFloat(tr.querySelector('[data-k="cost_total"]').value||0);
const rr=await fetch('/api/po/labeling',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({po_item_id:id,note:note,cost_total:cost_total})});
if(!rr.ok)alert(await rr.text());else alert('Saved');}));
}
loadItems();
</script>"""
    return HTMLResponse(render_layout("transport", html, "Transportation Costs"))

# ---------- Inventory ----------
@app.get("/inventory", response_class=HTMLResponse)
def inventory_page():
    html = """
<h1>Inventory</h1>
<div class='card'><div class='table-wrap'><table id='invTbl'>
<thead><tr><th>ID</th><th>ASIN</th><th>Title</th><th>Qty</th><th>Unit COGS</th><th>Total</th></tr></thead><tbody></tbody></table></div></div>
<script>
async function loadItems(){
const r=await fetch('/api/po/items');const data=await r.json();
const tb=document.querySelector('#invTbl tbody');tb.innerHTML='';
for(const it of data){
const unit=Number(it.unit_cogs||0);const total=unit*Number(it.quantity||0);
const tr=document.createElement('tr');
tr.innerHTML='<td>'+it.id+'</td><td>'+it.asin+'</td><td>'+it.listing_title+'</td>'
+'<td>'+it.quantity+'</td><td>'+unit.toFixed(4)+'</td><td>'+total.toFixed(2)+'</td>';
tb.appendChild(tr);}
}
loadItems();
</script>"""
    return HTMLResponse(render_layout("inventory", html, "Inventory"))
# ---------- ACCOUNTING: GL ----------
@app.get("/accounting/gl", response_class=HTMLResponse)
def accounting_gl_page():
    html = """
<h1>General Ledger (GL)</h1>
<div class='card'>
<form class='row' onsubmit='return goFilter()'>
  <input id='m' placeholder='Month (1-12)'>
  <input id='y' placeholder='Year (YYYY)'>
  <button type='submit'>Filter</button>
</form>
</div>
<div class='card'>
<h3>Add Transaction</h3>
<form id='glForm' onsubmit='return addGL(event)'>
<div class='row'>
<input name='date' type='date' required>
<input name='nc' placeholder='NC code' required>
<input name='account_name' placeholder='Account name' required>
<input name='reference' placeholder='Reference'>
<input name='description' placeholder='Description'>
<input name='amount' type='number' step='0.01' placeholder='Amount' required>
<select name='drcr'>
  <option value='Dr'>Dr</option>
  <option value='Cr'>Cr</option>
</select>
<input name='month' placeholder='Month'>
<input name='year' placeholder='Year'>
<button type='submit'>Add</button>
</div>
</form>
</div>
<div class='card'>
<div class='table-wrap'>
<table id='glTbl'>
<thead><tr><th>ID</th><th>Date</th><th>NC</th><th>Account</th><th>Description</th>
<th>Amount</th><th>Dr/Cr</th><th>Month</th><th>Year</th></tr></thead><tbody></tbody></table>
</div></div>
<script>
function goFilter(){
 const m=document.getElementById('m').value.trim();
 const y=document.getElementById('y').value.trim();
 loadGL(m||null,y||null);return false;
}
async function addGL(e){
 e.preventDefault();
 const f=new FormData(e.target);
 const data={date:f.get('date'),nc:f.get('nc'),account_name:f.get('account_name'),
 reference:f.get('reference')||null,description:f.get('description')||null,
 amount:parseFloat(f.get('amount')),drcr:f.get('drcr'),
 month:parseInt(f.get('month')||0),year:parseInt(f.get('year')||0)};
 const r=await fetch('/api/accounting/gl',{method:'POST',
 headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 if(r.ok){alert('Added');loadGL();e.target.reset();}else alert(await r.text());
 return false;
}
async function loadGL(m,y){
 const qs=new URLSearchParams();if(m)qs.set('month',m);if(y)qs.set('year',y);
 const r=await fetch('/api/accounting/gl'+(qs.toString()?('?'+qs.toString()):''));const d=await r.json();
 const tb=document.querySelector('#glTbl tbody');tb.innerHTML='';
 for(const t of d){
 const tr=document.createElement('tr');
 tr.innerHTML='<td>'+t.id+'</td><td>'+t.date+'</td><td>'+t.nc+'</td>'
 +'<td>'+t.account_name+'</td><td>'+(t.description||'')+'</td>'
 +'<td>'+Number(t.amount||0).toFixed(2)+'</td><td>'+t.drcr+'</td>'
 +'<td>'+t.month+'</td><td>'+t.year+'</td>';tb.appendChild(tr);
 }
}
loadGL();
</script>
"""
    return HTMLResponse(render_layout("gl", html, "Accounting - GL"))

# ---------- ACCOUNTING: Prepayments ----------
@app.get("/accounting/prepayments", response_class=HTMLResponse)
def accounting_prepayments_page():
    html = """
<h1>Prepayments</h1>
<div class='card'><div class='table-wrap'>
<table id='prepTbl'><thead><tr>
<th>ID</th><th>Date</th><th>Account</th><th>Description</th>
<th>Amount</th><th>Status</th></tr></thead><tbody></tbody></table></div></div>
<script>
async function loadPrepayments(){
const r=await fetch('/api/accounting/prepayments');const d=await r.json();
const tb=document.querySelector('#prepTbl tbody');tb.innerHTML='';
for(const p of d){
const tr=document.createElement('tr');
tr.innerHTML='<td>'+p.id+'</td><td>'+p.date+'</td><td>'+p.account+'</td>'
+'<td>'+(p.description||'')+'</td><td>'+Number(p.amount||0).toFixed(2)+'</td>'
+'<td>'+(p.status||'')+'</td>';tb.appendChild(tr);}
}
loadPrepayments();
</script>
"""
    return HTMLResponse(render_layout("prepayments", html, "Accounting - Prepayments"))

# ---------- ACCOUNTING: TB ----------
@app.get("/accounting/tb", response_class=HTMLResponse)
def accounting_tb_page():
    html = """
<h1>Trial Balance (TB)</h1>
<div class='card'>
<form class='row' onsubmit='return goFilterTB()'>
  <input id='m' placeholder='Month (1-12)'>
  <input id='y' placeholder='Year (YYYY)'>
  <button type='submit'>Filter</button>
</form>
</div>
<div class='card'>
<div class='table-wrap'>
<table id='tbTbl'><thead><tr>
<th>Account</th><th>Total Dr</th><th>Total Cr</th><th>Balance</th></tr></thead><tbody></tbody></table>
</div></div>
<script>
function goFilterTB(){
 const m=document.getElementById('m').value.trim();
 const y=document.getElementById('y').value.trim();
 loadTB(m||null,y||null);return false;
}
async function loadTB(m,y){
 const qs=new URLSearchParams();if(m)qs.set('month',m);if(y)qs.set('year',y);
 const r=await fetch('/api/accounting/tb'+(qs.toString()?('?'+qs.toString()):''));const d=await r.json();
 const tb=document.querySelector('#tbTbl tbody');tb.innerHTML='';
 for(const a of d){
 const tr=document.createElement('tr');
 tr.innerHTML='<td>'+a.account_name+'</td>'
 +'<td>'+Number(a.total_dr||0).toFixed(2)+'</td>'
 +'<td>'+Number(a.total_cr||0).toFixed(2)+'</td>'
 +'<td>'+Number(a.balance||0).toFixed(2)+'</td>';
 tb.appendChild(tr);}
}
loadTB();
</script>
"""
    return HTMLResponse(render_layout("tb", html, "Accounting - TB"))
# ---------- SALES ----------
@app.get("/sales", response_class=HTMLResponse)
def sales_page():
    html = """
<h1>Sales</h1>
<div class='card'>
<form class='row' onsubmit='return goFilter()'>
  <input id='m' placeholder='Month (1-12)'>
  <input id='y' placeholder='Year (YYYY)'>
  <button type='submit'>Filter</button>
</form>
</div>
<div class='card'>
<h3>Import from Sellerboard (CSV)</h3>
<p>В Sellerboard: <b>Reports → Orders</b> → Export CSV. Поддерживаются колонки:
ID/Date/ASIN/Units/Amount/FBA/Amazon Fee.</p>
<div class='row'><input type='file' id='sbfile' accept='.csv'>
<button type='button' onclick='importSellerboard()'>Import CSV</button></div>
<div id='impstatus' class='badge' style='display:none;margin-top:8px;'></div>
</div>
<div class='card'>
<div class='table-wrap'>
<table id='salesTbl'>
<thead><tr>
<th>ID</th><th>Date</th><th>ASIN</th><th>Description</th><th>Amount</th><th>TYPE</th><th>Party</th><th>Month</th>
<th>Units sold</th><th>COGS</th><th>FBA</th><th>Amazon fee</th><th>AFTER FEES</th><th>NET per unit</th>
<th>Payment to Supplier</th><th>Prep</th><th>Shipping</th><th>PO</th></tr></thead><tbody></tbody></table>
</div></div>
<script>
function goFilter(){const m=document.getElementById('m').value.trim();
const y=document.getElementById('y').value.trim();loadSales(m||null,y||null);return false;}
function setStatus(msg,ok=true){
const el=document.getElementById('impstatus');
el.style.display='inline-block';el.style.borderColor=ok?'#2e7d32':'#b71c1c';
el.style.color=ok?'#a5d6a7':'#ef9a9a';el.textContent=msg;}
function parseCSV(txt){
const rows=[];let row=[],cur='',q=false;
for(let i=0;i<txt.length;i++){
const ch=txt[i];
if(ch=='"'){if(q&&txt[i+1]=='"'){cur+='"';i++;}else q=!q;continue;}
if(!q&&(ch==','||ch==';')){row.push(cur);cur='';continue;}
if(!q&&(ch=='\\n'||ch=='\\r')){if(cur||row.length){row.push(cur);rows.push(row);row=[];cur='';}continue;}
cur+=ch;}if(cur||row.length){row.push(cur);rows.push(row);}return rows;}
function parseFloatSafe(v){if(!v)return 0;v=String(v).replace(',','.');const n=parseFloat(v);return isNaN(n)?0:n;}
function parseIntSafe(v){const n=parseInt(v,10);return isNaN(n)?0:n;}
function toISODate(s){if(!s)return null;s=s.trim();
if(/^\\d{4}-\\d{2}-\\d{2}/.test(s))return s.slice(0,10);
const m1=s.match(/^(\\d{1,2})\\.(\\d{1,2})\\.(\\d{4})/);if(m1)return m1[3]+'-'+m1[2].padStart(2,'0')+'-'+m1[1].padStart(2,'0');
const m2=s.match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);if(m2)return m2[3]+'-'+m2[1].padStart(2,'0')+'-'+m2[2].padStart(2,'0');
return s;}
async function importSellerboard(){
const f=document.getElementById('sbfile').files[0];
if(!f){alert('Choose CSV');return;}
const text=await f.text();const rows=parseCSV(text);if(rows.length<2){setStatus('Empty file',false);return;}
const head=rows[0].map(x=>x.trim().toLowerCase());
function find(...names){for(const n of names){const i=head.indexOf(n.toLowerCase());if(i>=0)return i;}return -1;}
const idx={id:find('id','order id','номер заказа'),date:find('date','дата'),asin:find('asin'),
desc:find('title','описание'),units:find('units','qty','кол-во'),amount:find('sales','amount','выручка'),
fba:find('fba','fba fee'),amz:find('amazon fee','commission')};
if(idx.id<0||idx.date<0||idx.asin<0){setStatus('Не найдены ключевые колонки',false);return;}
const recs=[];
for(let r=1;r<rows.length;r++){
const c=rows[r];if(!c||!c.length)continue;
const asin=c[idx.asin]?.trim();if(!asin)continue;
const units=parseIntSafe(c[idx.units]);
const fba=parseFloatSafe(c[idx.fba]);
const amz=parseFloatSafe(c[idx.amz]);
const rec={external_id:c[idx.id],date:toISODate(c[idx.date]),asin:asin,
description:c[idx.desc]||'',amount:parseFloatSafe(c[idx.amount]),
type:'Order',party:'Amazon',units_sold:units||1,
fba_fee_per_unit:units?fba/units:0,amazon_fee_per_unit:units?amz/units:0,
cogs_per_unit:0,after_fees_per_unit:0,net_per_unit:0,
pay_supplier_per_unit:0,prep_per_unit:0,ship_to_amz_per_unit:0};
recs.push(rec);}
if(!recs.length){setStatus('No valid rows',false);return;}
const r=await fetch('/api/sales/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({records:recs})});
if(!r.ok){setStatus('Import failed',false);return;}
const d=await r.json();setStatus('Imported: '+d.imported,true);loadSales();
}
async function loadSales(m,y){
const qs=new URLSearchParams();if(m)qs.set('month',m);if(y)qs.set('year',y);
const r=await fetch('/api/sales'+(qs.toString()?('?'+qs.toString()):''));const d=await r.json();
const tb=document.querySelector('#salesTbl tbody');tb.innerHTML='';
for(const s of d){
const tr=document.createElement('tr');
tr.innerHTML='<td>'+s.id+'</td><td>'+s.date+'</td><td>'+s.asin+'</td>'
+'<td>'+(s.description||'')+'</td><td>'+Number(s.amount||0).toFixed(2)+'</td>'
+'<td>'+(s.type||'')+'</td><td>'+(s.party||'')+'</td>'
+'<td>'+s.month+'</td><td>'+s.units_sold+'</td>'
+'<td>'+Number(s.cogs_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.fba_fee_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.amazon_fee_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.after_fees_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.net_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.pay_supplier_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.prep_per_unit||0).toFixed(2)+'</td>'
+'<td>'+Number(s.ship_to_amz_per_unit||0).toFixed(2)+'</td>'
+'<td>'+(s.po_id||'')+'</td>';tb.appendChild(tr);}
}
loadSales();
</script>
"""
    return HTMLResponse(render_layout("sales", html, "Sales"))

# ---------- API ENDPOINTS ----------
@app.get("/api/po/items")
def api_po_items(db: Session = Depends(get_db)):
    return db.query(PurchaseOrderItem).all()

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

@app.post("/api/po/labeling")
def api_po_labeling(body: LabelingIn, db: Session = Depends(get_db)):
    lc = po_svc.add_labeling_cost(db, body.po_item_id, body.note, body.cost_total)
    return {"ok": True, "labeling_id": lc.id}

# Accounting
@app.post("/api/accounting/gl")
def api_gl_add(txn: dict, db: Session = Depends(get_db)):
    return acc_svc.add_gl_transaction(db, txn)

@app.get("/api/accounting/gl")
def api_gl_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return acc_svc.list_gl(db, month, year)

@app.get("/api/accounting/prepayments")
def api_prepayments_list(db: Session = Depends(get_db)):
    return acc_svc.list_prepayments(db)

@app.get("/api/accounting/tb")
def api_tb_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return acc_svc.trial_balance(db, month, year)

# Sales
@app.post("/api/sales/import")
def api_sales_import(data: dict, db: Session = Depends(get_db)):
    recs = data.get("records", [])
    imported = sales_svc.import_sales(db, recs)
    return {"imported": imported}

@app.get("/api/sales")
def api_sales_list(month: int | None = None, year: int | None = None, db: Session = Depends(get_db)):
    return sales_svc.list_sales(db, month, year)

# ---------- ADMIN ----------
@app.post("/admin/init-db")
def admin_init_db():
    init_db()
    return {"ok": True, "message": "DB initialized"}
