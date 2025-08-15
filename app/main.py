# app/main.py
from __future__ import annotations

import os
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import select, func, text, inspect
from sqlalchemy.orm import Session

from starlette.middleware.sessions import SessionMiddleware
import secrets

# --- アプリ内 ---
# DB: engine / SessionLocal / get_db は既存の app.db にある想定
try:
    from .db import engine, SessionLocal, get_db
except Exception:
    # もし app.db に get_db がなければ簡易定義（通常は不要）
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine as _create_engine

    _url = os.environ.get("DATABASE_URL", "")
    if _url and _url.startswith("postgres://"):
        _url = _url.replace("postgres://", "postgresql+psycopg://", 1)
    engine = _create_engine(_url) if _url else None
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

from .models import Base, User, Artist, Post  # type: ignore

# 埋め込みやサムネ解決ユーティリティ
try:
    from .utils import (
        hash_password,
        verify_password,
        youtube_embed,
        spotify_embed,
        apple_embed,                   # (url, height) を返す想定
        resolve_thumbnail_for_post,    # Post -> 画像URL
        thumb_of,                      # テンプレから呼ぶヘルパ
    )
except ImportError:
    # 互換: apple_music_embed という名前の環境向けフォールバック
    from .utils import (
        hash_password,
        verify_password,
        youtube_embed,
        spotify_embed,
        apple_music_embed as apple_embed,
        resolve_thumbnail_for_post,
        thumb_of,
    )

# ------------------------------------------------------------------------------
# 基本セットアップ
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

app = FastAPI(title="chilaq API")

from starlette.middleware.sessions import SessionMiddleware
import secrets

# --- Session (cookieベースのサーバーサイドセッション) ---
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="chilaq_session",
    same_site="lax",
    https_only=False,          # 本番(https)では True 推奨（Render では True にしてOK）
    max_age=60*60*24*30,       # 30日
)

# /static をマウント（CSS/JS/画像など）
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

# テンプレート（HTML）
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
# テンプレから thumb_of(post) を直接呼べるようにする
templates.env.globals["thumb_of"] = thumb_of

# --- CORS（環境変数 ALLOW_ORIGINS にカンマ区切りで指定）
_raw = os.environ.get("ALLOW_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# --- Security headers ---
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains; preload"
    return resp

import uuid

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    # 既にあれば尊重、無ければ発行
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = rid
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
    # クライアントJSから参照したい場合に備えて露出（必要なければ外してもOK）
    resp.headers.setdefault("Access-Control-Expose-Headers", "X-Request-ID")
    return resp

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        resp = await call_next(request)
        status = resp.status_code
    except Exception:
        status = 500
        raise
    finally:
        ms = (time.time() - start) * 1000
        rid = getattr(request.state, "request_id", "-")
        ua = request.headers.get("user-agent", "-")
        ip = request.client.host if request.client else "-"
        logger.info(
            f'rid={rid} {request.method} {request.url.path} {status} {ms:.1f}ms ip="{ip}" ua="{ua}"'
        )
    return resp

# --- Error handlers ---
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code, "path": request.url.path},
    )

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong."})

# ------------------------------------------------------------------------------
# Step 2 の要点：likes/hearts の表記ゆれを likes に統一
# 起動時に likes 列を保証し、必要なら hearts→likes バックフィル
# ------------------------------------------------------------------------------
def ensure_likes_column_and_backfill():
    """posts.likes を“正”として保証。hearts があれば likes に取り込む。"""
    if not engine:
        return
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("posts")}
    except Exception:
        cols = set()

    with engine.begin() as conn:
        if "likes" not in cols:
            # SQLite/PG 共通で通るシンプルな追加
            conn.execute(text("ALTER TABLE posts ADD COLUMN likes INTEGER DEFAULT 0"))
        # hearts から likes へバックフィル（likes が未セット or 0 のものを対象）
        if "hearts" in cols:
            conn.execute(
                text(
                    """
                    UPDATE posts
                       SET likes = COALESCE(NULLIF(likes, 0), hearts, 0)
                     WHERE likes IS NULL OR likes = 0
                    """
                )
            )

# --- DB: テーブル作成（初回用）＋ likes バックフィル ---
@app.on_event("startup")
def on_startup():
    if engine:
        Base.metadata.create_all(engine)
        ensure_likes_column_and_backfill()
        logger.info("tables ensured & likes backfilled")
    else:
        logger.warning("DATABASE_URL not set")

# ------------------------------------------------------------------------------
# 基本ルート
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "healthy"}

# トップページ：公開フィード（削除済みは除外）
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    posts = (
        db.execute(
            select(Post).where(getattr(Post, "is_deleted", False) == False)  # noqa: E712
            .order_by(getattr(Post, "created_at", Post.id).desc())
            .limit(30)
        )
        .scalars()
        .all()
    )
    # テンプレでは posts をループし、thumb は {{ thumb_of(post) }} で取得
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "posts": posts,
            # OGP/タイトルは base.html 側のデフォルトでOK（必要なら page_title を渡す）
        },
    )

# 投稿詳細
@app.get("/p/{post_id}", response_class=HTMLResponse)
def post_detail(post_id: int, request: Request, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post or getattr(post, "is_deleted", False):
        raise HTTPException(404, "post_not_found")

    yt = youtube_embed(getattr(post, "url_youtube", None))
    sp = spotify_embed(getattr(post, "url_spotify", None))
    am_url, am_h = apple_embed(getattr(post, "url_apple", None))  # (url, height) or (None, None)

    embeds = {
        "youtube": yt,
        "spotify": sp,
        "apple": am_url,
        "apple_h": am_h or 450,
    }
    og_image_url = resolve_thumbnail_for_post(post)

    return templates.TemplateResponse(
        "post_detail.html",
        {
            "request": request,
            "post": post,
            "embeds": embeds,
            "og_image_url": og_image_url,
            # ページタイトル/OGPはテンプレ側ブロックで生成
        },
    )

# ------------------------------------------------------------------------------
# Like API（likes に統一）
# フロントJSは .like-btn[data-post-id] を使い、POST すると JSON {"liked": true, "likes": int}
# カウント取得は GET /posts/{id}/likes -> {"post_id": id, "likes": int}
# ------------------------------------------------------------------------------
def _inc_like(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if not post or getattr(post, "is_deleted", False):
        raise HTTPException(404, "post_not_found")
    post.likes = (post.likes or 0) + 1
    db.add(post)
    db.commit()
    db.refresh(post)
    return post

@app.post("/p/{post_id}/like")
def like_post_legacy(post_id: int, request: Request, db: Session = Depends(get_db)):
    """後方互換：投稿詳細で使っていたレガシーURL。likes を返す。"""
    post = _inc_like(db, post_id)
    return {"liked": True, "likes": post.likes}

from fastapi.responses import JSONResponse

def _like_core(post_id: int, request: Request, db: Session) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    try:
        post = db.get(Post, post_id)
        if not post or post.is_deleted:
            return JSONResponse({"ok": False, "liked": False, "hearts": 0, "post_id": post_id}, status_code=404)

        # 既にCookieがあれば再加算しない（UI 側の連打もここで抑止）
        cookie_key = f"liked_{post_id}"
        already = request.cookies.get(cookie_key) == "1"

        if not already:
            post.likes = (post.likes or 0) + 1
            db.add(post)
            db.commit()
            liked_now = True
        else:
            liked_now = True  # 既にLike済みという扱い

        resp = JSONResponse(
            {"ok": True, "liked": liked_now, "hearts": post.likes or 0, "post_id": post_id},
            headers={"Cache-Control": "no-store"}  # 念のため
        )
        # 1年保持
        resp.set_cookie(cookie_key, "1", max_age=60*60*24*365, httponly=False, samesite="Lax", path="/", secure=False)
        logger.info(f"rid={rid} like ok post_id={post_id} hearts={post.likes}")
        return resp
    except Exception:
        logger.exception(f"rid={rid} like failed post_id={post_id}")
        return JSONResponse({"ok": False, "liked": False, "hearts": 0, "post_id": post_id}, status_code=500)

@app.post("/api/posts/{post_id}/like")
def api_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    return _like_core(post_id, request, db)

@app.post("/p/{post_id}/like")
def page_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    return _like_core(post_id, request, db)

@app.get("/posts/{post_id}/likes")
def get_likes(post_id: int, request: Request, db: Session = Depends(get_db)):
    rid = getattr(request.state, "request_id", "-")
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        logger.info(f"rid={rid} likes miss post_id={post_id}")
        raise HTTPException(status_code=404, detail="not_found")
    logger.info(f"rid={rid} likes ok post_id={post_id} hearts={post.likes or 0}")
    return JSONResponse({"post_id": post_id, "likes": post.likes or 0}, headers={"Cache-Control": "no-store"})

# ------------------------------------------------------------------------------
# About（統計：likes / posts / artists）
# テンプレ about.html では {{ stats.likes }} / {{ stats.posts }} / {{ stats.artists }} を使用
# ------------------------------------------------------------------------------
@app.get("/about", response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    total_likes = db.scalar(select(func.coalesce(func.sum(Post.likes), 0))) or 0
    total_posts = db.scalar(select(func.count(Post.id))) or 0
    total_artists = db.scalar(select(func.count(Artist.id))) or 0
    stats = {"likes": total_likes, "posts": total_posts, "artists": total_artists}

    return templates.TemplateResponse(
        "about.html",
        {
            "request": request,
            "stats": stats,
            "page_title": "About | Chilaq - もっと、好きな音楽をディグる",
        },
    )

# ------------------------------------------------------------------------------
# （必要に応じて）管理・認証ルート等が別にある場合は、この下で include する
# 例:
# from .routers import admin as admin_router
# app.include_router(admin_router.router)
# ------------------------------------------------------------------------------