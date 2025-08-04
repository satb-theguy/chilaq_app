from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging, time

app = FastAPI(title="chilaq API")

# --- 防犯カメラ（アクセスログ） ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = (time.time() - start) * 1000
    logger.info(
        f'{request.method} {request.url.path} {response.status_code} {ms:.1f}ms '
        f'ip="{request.client.host}" ua="{request.headers.get("user-agent","")}"'
    )
    return response

# --- 救護室（エラーハンドリングを統一） ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code, "path": str(request.url.path)},
    )

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")  # スタックトレースをログへ
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "Something went wrong."},
    )

@app.get("/")
def root():
    return {"ok": True, "message": "Hello from chilaq.jp! v3"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# 動作確認用のエンドポイント（わざとエラーにする）
@app.get("/boom")
def boom():
    raise HTTPException(status_code=400, detail="bad_request")

@app.get("/crash")
def crash():
    raise RuntimeError("kaboom")
    
@app.get("/version")
def version():
    return {"app": "chilaq", "version": "0.1.2"}