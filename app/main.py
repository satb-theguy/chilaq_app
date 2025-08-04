from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import logging, time, os

from app.db import engine
from app.models import Base
from app.routers import notes as notes_router
from app.routers import auth as auth_router
from app.routers import compare as compare_router

app = FastAPI(title="chilaq API")

# --- CORS ---
_raw = os.environ.get("ALLOW_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# --- Security headers ---
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains; preload"
    return resp

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    resp = await call_next(request)
    ms = (time.time() - start) * 1000
    logger.info(f'{request.method} {request.url.path} {resp.status_code} {ms:.1f}ms ip="{request.client.host}"')
    return resp

# --- Error handlers ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status_code": exc.status_code, "path": request.url.path})

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error":"internal_error","message":"Something went wrong."})

# --- DB: テーブル作成（初回用）
@app.on_event("startup")
def on_startup():
    if engine:
        Base.metadata.create_all(engine)
        logger.info("tables ensured")
    else:
        logger.warning("DATABASE_URL not set")

# --- Basic routes ---
@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html><meta charset="utf-8">
<title>1分比較表メーカー</title>
<style>
  body{font-family:sans-serif;max-width:980px;margin:24px auto;padding:0 12px}
  .row{display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr;gap:8px;margin-bottom:8px}
  input[type=text],input[type=number]{width:100%;padding:6px}
  button{padding:8px 12px;margin-right:6px}
  table{border-collapse:collapse;width:100%;margin-top:16px}
  th,td{border:1px solid #ddd;padding:6px} th{background:#f7f7f7}
  .muted{color:#666;font-size:12px}
</style>

<h1>1分比較表メーカー</h1>
<p class="muted">最大5件まで。PA-API未承認のため、当面は手動入力で比較します。</p>

<div>
  <label>マーケットプレイス:
    <select id="market">
      <option value="JP" selected>JP</option>
      <option value="US">US</option>
    </select>
  </label>
</div>

<div id="items"></div>
<p>
  <button id="add" type="button">＋ 行を追加</button>
  <button id="gen" type="button">生成する</button>
  <button id="clear" type="button">クリア</button>
</p>

<div id="result"></div>

<script>
document.addEventListener('DOMContentLoaded', () => {
  const MAX = 5;
  const itemsEl = document.getElementById('items');

  function rowTemplate(i){
    return `
    <div class="row" data-i="${i}">
      <input type="text" placeholder="商品URL (https://www.amazon.co.jp/dp/...)" class="url">
      <input type="text" placeholder="商品名 (任意)" class="title">
      <input type="number" placeholder="価格 (例: 1980)" class="price" step="0.01" min="0">
      <input type="number" placeholder="評価 (例: 4.3)" class="rating" step="0.1" min="0" max="5">
      <input type="number" placeholder="レビュー数 (例: 120)" class="reviews" step="1" min="0">
    </div>`;
  }

  function ensureRows(n=2){
    itemsEl.innerHTML = "";
    for(let i=0;i<n;i++) itemsEl.insertAdjacentHTML('beforeend', rowTemplate(i));
  }
  ensureRows();

  document.getElementById('add').addEventListener('click', () => {
    const count = itemsEl.querySelectorAll('.row').length;
    if (count >= MAX) { alert('最大5件までです'); return; }
    itemsEl.insertAdjacentHTML('beforeend', rowTemplate(count));
  });

  document.getElementById('clear').addEventListener('click', () => ensureRows());

  function buildPayload(){
    const market = document.getElementById('market').value;
    const rows = Array.from(itemsEl.querySelectorAll('.row'));
    const items = rows.map(r => {
      const url = r.querySelector('.url').value.trim();
      const title = r.querySelector('.title').value.trim();
      const price = r.querySelector('.price').value.trim();
      const rating = r.querySelector('.rating').value.trim();
      const reviews = r.querySelector('.reviews').value.trim();
      const manual = {};
      if (title) manual.title = title;
      if (price) manual.price = Number(price);
      if (rating) manual.rating = Number(rating);
      if (reviews) manual.reviews = Number(reviews);
      return { url: url || null, manual: Object.keys(manual).length ? manual : null };
    }).filter(x => x.url || x.manual);
    return { items, options: { marketplace: market } };
  }

  function toCSV(items){
    const head = ["商品名","価格","通貨","評価","レビュー","ASIN","URL"];
    const rows = items.map(x => [
      x.title || "",
      (x.price ?? ""),
      (x.currency || ""),
      (x.rating ?? ""),
      (x.reviews ?? ""),
      (x.asin || ""),
      (x.url || "")
    ]);
    const all = [head, ...rows];
    const quoteRe = new RegExp('\"', 'g');        // " を二重に
    const needsRe = new RegExp('[\",\\n]');       // 「" か , か 改行」が含まれるか
    return all.map(r => r.map(v=>{
      const s = String(v).replace(quoteRe,'""');
      return needsRe.test(s) ? `"${s}"` : s;
    }).join(",")).join("\\n");
  }

  function copyText(text){
    navigator.clipboard.writeText(text)
      .then(()=> alert("コピーしました"))
      .catch(()=> alert("コピー失敗"));
  }

  document.getElementById('gen').addEventListener('click', async () => {
    const payload = buildPayload();
    if ((payload.items||[]).length < 2) { alert('少なくとも2件入力してください'); return; }
    const res = await fetch('/api/compare', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    const hl = data.highlights || {};
    const rows = (data.items||[]).map((x,i) => {
      const badge = [
        (hl.lowest_price_index === i ? '💰' : ''),
        (hl.highest_rating_index === i ? '⭐' : '')
      ].join('');
      return `<tr>
        <td>${badge} ${x.title||""}</td>
        <td>${x.price??""} ${x.currency||""}</td>
        <td>${x.rating??""}</td>
        <td>${x.reviews??""}</td>
        <td><a href="${x.url||'#'}" target="_blank" rel="noopener">リンク</a></td>
      </tr>`;
    }).join('');

    const csv = toCSV(data.items||[]);
    const box = document.getElementById('result');
    box.innerHTML = `
      <p>生成時刻: ${data.generated_at}</p>
      <p>${data.summary || ""}</p>
      <p>
        <button id="copy" type="button">表をコピー（CSV）</button>
        <a id="dl" download="compare.csv">CSVをダウンロード</a>
      </p>
      <table>
        <thead><tr><th>商品名</th><th>価格</th><th>評価</th><th>レビュー</th><th>URL</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
    document.getElementById('copy').addEventListener('click', ()=> copyText(csv));
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    document.getElementById('dl').href = URL.createObjectURL(blob);
  });
});
</script>
"""

# --- Mount routers ---
app.include_router(notes_router.router)
app.include_router(auth_router.router)
app.include_router(compare_router.router)