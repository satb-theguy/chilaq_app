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
body{font-family:sans-serif;max-width:920px;margin:20px auto;padding:0 12px}
textarea{width:100%} table{border-collapse:collapse;width:100%}
th,td{border:1px solid #ddd;padding:6px} th{background:#f5f5f5}
</style>
<h1>1分比較表メーカー（MVP）</h1>
<p>テキスト欄のJSONを編集して「生成する」を押すと <code>/api/compare</code> を呼びます。</p>
<textarea id="in" rows="8">
{"items":[
 {"url":"https://www.amazon.co.jp/dp/B0AAA","manual":{"title":"商品A","price":1980,"currency":"JPY","rating":4.2,"reviews":120}},
 {"url":"https://www.amazon.co.jp/dp/B0BBB","manual":{"title":"商品B","price":2480,"currency":"JPY","rating":4.4,"reviews":80}}
],"options":{"marketplace":"JP"}}</textarea>
<p><button id="go">生成する</button></p>
<div id="out"></div>
<script>
document.getElementById('go').onclick = async () => {
  let payload;
  try { payload = JSON.parse(document.getElementById('in').value); }
  catch(e){ alert('JSONの形式が不正です'); return; }
  const res = await fetch('/api/compare', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  const rows = (data.items||[]).map(x => `<tr>
    <td>${x.title||""}</td>
    <td>${x.price??""} ${x.currency||""}</td>
    <td>${x.rating??""}</td>
    <td>${x.reviews??""}</td>
  </tr>`).join('');
  const hl = data.highlights || {};
  document.getElementById('out').innerHTML = `
    <p>生成時刻: ${data.generated_at}</p>
    <p>ハイライト: 最安=${hl.lowest_price_index ?? "-"} / 最高評価=${hl.highest_rating_index ?? "-"}</p>
    <table><thead><tr><th>商品名</th><th>価格</th><th>評価</th><th>レビュー</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p>${data.summary || ""}</p>
  `;
};
</script>
"""

# --- Mount routers ---
app.include_router(notes_router.router)
app.include_router(auth_router.router)
app.include_router(compare_router.router)