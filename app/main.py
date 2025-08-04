from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import logging, time, os

# --- SQLAlchemy (同期版) ---
from sqlalchemy import create_engine, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

# ===== App =====
app = FastAPI(title="chilaq API")

# --- CORS (顔パス名簿) ---
_raw = os.environ.get("ALLOW_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

# --- セキュリティ看板 ---
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains; preload"
    return resp

# --- Logging (防犯カメラ) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    resp = await call_next(request)
    ms = (time.time() - start) * 1000
    logger.info(f'{request.method} {request.url.path} {resp.status_code} {ms:.1f}ms ip="{request.client.host}"')
    return resp

# --- Unified error handlers (救護室) ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status_code": exc.status_code, "path": request.url.path})

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error":"internal_error","message":"Something went wrong."})

# ===== Database setup =====
# Renderで設定した環境変数
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    # 念のため自動補正（ローカルで貼り間違えてもOK）
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)

if not db_url:
    # ローカル実行時など、DBが未設定なら起動時に分かるように
    logger.warning("DATABASE_URL is not set. The /notes endpoints will fail.")

engine = create_engine(db_url, pool_pre_ping=True) if db_url else None

class Base(DeclarativeBase):
    pass

class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)

# 起動時にテーブル作成（本番ではマイグレーション推奨）
@app.on_event("startup")
def on_startup():
    if engine:
        Base.metadata.create_all(engine)
        logger.info("tables ensured")

# ===== Schemas =====
class NoteIn(BaseModel):
    title: str
    content: str

class NoteOut(NoteIn):
    id: int

# ===== Routes =====
@app.get("/")
def root():
    return {"ok": True, "message": "Hello from chilaq.jp! with DB"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# CRUD: Notes
@app.get("/notes")
def list_notes() -> list[NoteOut]:
    if not engine: raise HTTPException(500, "database_not_configured")
    with Session(engine) as s:
        rows = s.query(Note).order_by(Note.id.desc()).all()
        return [NoteOut(id=r.id, title=r.title, content=r.content) for r in rows]

@app.post("/notes", status_code=201)
def create_note(note: NoteIn) -> NoteOut:
    if not engine: raise HTTPException(500, "database_not_configured")
    with Session(engine) as s:
        row = Note(title=note.title, content=note.content)
        s.add(row)
        s.commit()
        s.refresh(row)
        return NoteOut(id=row.id, title=row.title, content=row.content)

@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int):
    if not engine: raise HTTPException(500, "database_not_configured")
    with Session(engine) as s:
        row = s.get(Note, note_id)
        if not row:
            raise HTTPException(404, "not_found")
        s.delete(row)
        s.commit()
        return JSONResponse(status_code=204, content=None)