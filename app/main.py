from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
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

@app.get("/")
def root():
    return {"ok": True, "message": "Hello from chilaq.jp! with DB and routers"}

# --- Mount routers ---
app.include_router(notes_router.router)
app.include_router(auth_router.router)
app.include_router(compare_router.router)