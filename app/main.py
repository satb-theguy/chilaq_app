# app/main.py
from __future__ import annotations

import os
import logging
import time
import uuid
import secrets
from pathlib import Path
from typing import Optional, Annotated

from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import create_engine, select, func, text, inspect
from sqlalchemy.orm import sessionmaker, Session

from starlette.middleware.sessions import SessionMiddleware

from .models import Base, User, Artist, Post
from .utils import (
    hash_password,
    verify_password,
    youtube_embed,
    spotify_embed,
    apple_embed,
    resolve_thumbnail_for_post,
    thumb_of,
    generate_slug,
)

# ------------------------------------------------------------------------------
# 基本セットアップ
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# DB接続
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{PROJECT_ROOT / 'app.db'}"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="chilaq (slim)")

# Session
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="chilaq_session",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 30,
)

# Static / Templates
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
templates.env.globals["thumb_of"] = thumb_of

# CORS
_raw = os.environ.get("ALLOW_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or [],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# startup時のマイグレーション関数を追加
def ensure_columns_and_slugs():
    """必要なカラムを追加してからslugを生成"""
    import re
    
    with engine.begin() as conn:
        insp = inspect(engine)
        
        # postsテーブルのカラム確認と追加
        try:
            cols = {c["name"] for c in insp.get_columns("posts")}
            
            # bodyカラムの追加（存在しない場合）
            if "body" not in cols:
                logger.info("Adding 'body' column to posts table")
                conn.execute(text("ALTER TABLE posts ADD COLUMN body TEXT"))
            
            # slugカラムの追加（存在しない場合）
            if "slug" not in cols:
                logger.info("Adding 'slug' column to posts table")
                conn.execute(text("ALTER TABLE posts ADD COLUMN slug VARCHAR(20)"))
                try:
                    conn.execute(text("CREATE UNIQUE INDEX ix_posts_slug ON posts(slug)"))
                except Exception:
                    pass  # インデックスが既に存在する場合
            
            # likesカラムの確認（既存の処理）
            if "likes" not in cols:
                logger.info("Adding 'likes' column to posts table")
                conn.execute(text("ALTER TABLE posts ADD COLUMN likes INTEGER DEFAULT 0"))
            
            # その他の必要なカラムの確認と追加
            if "url_youtube" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN url_youtube VARCHAR(512)"))
            if "url_spotify" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN url_spotify VARCHAR(512)"))
            if "url_apple" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN url_apple VARCHAR(512)"))
            if "thumbnail_url" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN thumbnail_url VARCHAR(512)"))
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE posts ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
                
        except Exception as e:
            logger.error(f"Error checking/adding posts columns: {e}")
        
        # artistsテーブルのカラム確認と追加
        try:
            cols = {c["name"] for c in insp.get_columns("artists")}
            
            # slugカラムの追加（存在しない場合）
            if "slug" not in cols:
                logger.info("Adding 'slug' column to artists table")
                conn.execute(text("ALTER TABLE artists ADD COLUMN slug VARCHAR(20)"))
                try:
                    conn.execute(text("CREATE UNIQUE INDEX ix_artists_slug ON artists(slug)"))
                except Exception:
                    pass  # インデックスが既に存在する場合
                    
            # created_atカラムの追加（存在しない場合）
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE artists ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
                
        except Exception as e:
            logger.error(f"Error checking/adding artists columns: {e}")
    
    def is_valid_slug(slug):
        """slugが英数字のみかチェック"""
        if not slug:
            return False
        return bool(re.match(r'^[a-zA-Z0-9]+$', slug))
    
    # slugの生成処理
    db = SessionLocal()
    try:
        # Postのslug生成・修正
        # SQLでslugがNULLまたは空のレコードを取得
        posts_without_slug = db.execute(
            text("SELECT id FROM posts WHERE slug IS NULL OR slug = ''")
        ).fetchall()
        
        for row in posts_without_slug:
            post_id = row[0]
            while True:
                slug = generate_slug()
                # 重複チェック
                existing = db.execute(
                    text("SELECT COUNT(*) FROM posts WHERE slug = :slug"),
                    {"slug": slug}
                ).scalar()
                if existing == 0:
                    db.execute(
                        text("UPDATE posts SET slug = :slug WHERE id = :id"),
                        {"slug": slug, "id": post_id}
                    )
                    logger.info(f"Generated slug for post {post_id}: {slug}")
                    break
        
        # Artistのslug生成・修正
        artists_without_slug = db.execute(
            text("SELECT id FROM artists WHERE slug IS NULL OR slug = ''")
        ).fetchall()
        
        for row in artists_without_slug:
            artist_id = row[0]
            while True:
                slug = generate_slug()
                # 重複チェック
                existing = db.execute(
                    text("SELECT COUNT(*) FROM artists WHERE slug = :slug"),
                    {"slug": slug}
                ).scalar()
                if existing == 0:
                    db.execute(
                        text("UPDATE artists SET slug = :slug WHERE id = :id"),
                        {"slug": slug, "id": artist_id}
                    )
                    logger.info(f"Generated slug for artist {artist_id}: {slug}")
                    break
        
        db.commit()
        logger.info("Column migration and slug generation completed")
        
    except Exception as e:
        logger.error(f"Error in slug generation: {e}")
        db.rollback()
    finally:
        db.close()

@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(engine)
        logger.info("Database tables created/verified")
        
        ensure_likes_column_and_backfill()
        logger.info("Likes column ensured and backfilled")
        
        ensure_columns_and_slugs()  # 名前を変更
        logger.info("All columns ensured and slugs generated")
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        # エラーが発生しても起動を続行
        pass

# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=15552000; includeSubDomains; preload"
    return resp

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = rid
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = rid
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
        logger.info(f'rid={rid} {request.method} {request.url.path} {status} {ms:.1f}ms ip="{ip}" ua="{ua}"')
    return resp

# Error handlers
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code, "path": request.url.path},
        headers=exc.headers or None,
    )

@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong."})

# ------------------------------------------------------------------------------
# likes 列の保証＆hearts→likes バックフィル
# ------------------------------------------------------------------------------
def ensure_likes_column_and_backfill():
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("posts")}
    except Exception:
        cols = set()
    with engine.begin() as conn:
        if "likes" not in cols:
            conn.execute(text("ALTER TABLE posts ADD COLUMN likes INTEGER DEFAULT 0"))
        if "hearts" in cols:
            conn.execute(text("""
                UPDATE posts
                   SET likes = COALESCE(NULLIF(likes, 0), hearts, 0)
                 WHERE likes IS NULL OR likes = 0
            """))

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(engine)
    ensure_likes_column_and_backfill()
    logger.info("tables ensured & likes backfilled")

# ------------------------------------------------------------------------------
# 認証/権限
# ------------------------------------------------------------------------------
def ctx(request: Request, **kw):
    d = {"request": request}
    d.update(kw)
    return d

def _current_user(db: Session, request: Request) -> Optional[User]:
    uid = request.session.get("user_id")
    return db.get(User, uid) if uid else None

def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = _current_user(db, request)
    if not user:
        raise HTTPException(status_code=303, detail="login_required", headers={"Location": "/login"})
    return user

def require_admin(user: User = Depends(require_login)) -> User:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="forbidden")
    return user

# ------------------------------------------------------------------------------
# 公開集計
# ------------------------------------------------------------------------------
def get_public_stats(db: Session) -> dict[str, int]:
    posts = db.scalar(select(func.count()).select_from(Post).where(Post.is_deleted == False)) or 0
    artists = db.scalar(select(func.count(func.distinct(Post.artist_id))).where(Post.is_deleted == False)) or 0
    likes = db.scalar(select(func.coalesce(func.sum(Post.likes), 0)).where(Post.is_deleted == False)) or 0
    return {"posts": posts, "artists": artists, "likes": likes}

# ------------------------------------------------------------------------------
# 公開ルート
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, db: Session = Depends(get_db)):
    posts = (
        db.execute(
            select(Post)
            .where(Post.is_deleted == False)
            .order_by(Post.created_at.desc())
            .limit(30)
        ).scalars().all()
    )
    user = _current_user(db, request)
    return templates.TemplateResponse("index.html", ctx(request, posts=posts, user=user))

@app.get("/p/{slug}", response_class=HTMLResponse, name="post_detail")
def post_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    # slugで検索、後方互換性のため数字の場合はIDとして扱う
    if slug.isdigit():
        post = db.get(Post, int(slug))
    else:
        post = db.query(Post).filter(Post.slug == slug).first()
    
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")
    
    yt = youtube_embed(post.url_youtube)
    sp = spotify_embed(post.url_spotify)
    am_url, am_h = apple_embed(post.url_apple)
    og_image_url = resolve_thumbnail_for_post(post)
    user = _current_user(db, request)
    return templates.TemplateResponse(
        "post_detail.html",
        ctx(
            request,
            post=post,
            embeds={"youtube": yt, "spotify": sp, "apple": am_url, "apple_h": am_h or 450},
            og_image_url=og_image_url,
            user=user,
        ),
    )

@app.get("/artist/{slug}", response_class=HTMLResponse, name="artist_public")
def artist_public(slug: str, request: Request, db: Session = Depends(get_db)):
    # slugで検索、後方互換性のため数字の場合はIDとして扱う
    if slug.isdigit():
        artist = db.get(Artist, int(slug))
    else:
        artist = db.query(Artist).filter(Artist.slug == slug).first()
    
    if not artist:
        raise HTTPException(404, "artist_not_found")
    
    posts = db.execute(
        select(Post).where(Post.is_deleted == False, Post.artist_id == artist.id).order_by(Post.id.desc())
    ).scalars().all()
    user = _current_user(db, request)
    return templates.TemplateResponse("artist.html", ctx(request, artist=artist, posts=posts, user=user))

@app.get("/about", response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    stats = get_public_stats(db)
    user = _current_user(db, request)
    return templates.TemplateResponse("about.html", ctx(request, stats=stats, user=user))

# ------------------------------------------------------------------------------
# Like API
# ------------------------------------------------------------------------------
def _like_core(post_id: int, request: Request, db: Session) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    try:
        post = db.get(Post, post_id)
        if not post or post.is_deleted:
            return JSONResponse({"ok": False, "liked": False, "likes": 0, "post_id": post_id}, status_code=404)
        cookie_key = f"liked_{post_id}"
        already = request.cookies.get(cookie_key) == "1"
        if not already:
            post.likes = (post.likes or 0) + 1
            db.add(post)
            db.commit()
        resp = JSONResponse({"ok": True, "liked": True, "likes": int(post.likes or 0), "post_id": post_id},
                            headers={"Cache-Control": "no-store"})
        resp.set_cookie(cookie_key, "1", max_age=60*60*24*365, httponly=False, samesite="Lax", path="/", secure=False)
        logger.info(f"rid={rid} like ok post_id={post_id} likes={post.likes}")
        return resp
    except Exception:
        logger.exception(f"rid={rid} like failed post_id={post_id}")
        return JSONResponse({"ok": False, "liked": False, "likes": 0, "post_id": post_id}, status_code=500)

@app.post("/api/posts/{post_id}/like")
def api_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    return _like_core(post_id, request, db)

@app.get("/posts/{post_id}/likes")
def get_likes(post_id: int, request: Request, db: Session = Depends(get_db)):
    rid = getattr(request.state, "request_id", "-")
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        logger.info(f"rid={rid} likes miss post_id={post_id}")
        raise HTTPException(status_code=404, detail="not_found")
    logger.info(f"rid={rid} likes ok post_id={post_id} likes={post.likes or 0}")
    return {"post_id": post_id, "likes": int(post.likes or 0)}

# ------------------------------------------------------------------------------
# 認証
# ------------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", ctx(request, title="ログイン", error=None))

@app.post("/login", response_class=HTMLResponse)
def login_action(
    request: Request,
    db: Session = Depends(get_db),
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", ctx(request, title="ログイン", error="メールまたはパスワードが違います。"), status_code=400)
    request.session["user_id"] = user.id
    request.session["is_admin"] = bool(user.is_admin)
    # ダッシュボードへリダイレクト
    return admin_root(request, user=user, db=db)

@app.get("/logout", response_class=HTMLResponse)
@app.post("/logout", response_class=HTMLResponse)
def logout(request: Request, db: Session = Depends(get_db)):
    request.session.clear()
    return index(request, db)

# ------------------------------------------------------------------------------
# 管理
# ------------------------------------------------------------------------------


def can_edit_post(user: User, post: Post, db: Session) -> bool:
    """ユーザーが投稿を編集できるかチェック"""
    if user.is_admin:
        return True
    
    # 投稿のアーティストがユーザーに紐付いているかチェック
    if post.artist and post.artist.owner_id == user.id:
        return True
    
    return False

def _fetch_posts_for_user(db: Session, user: User):
    if user.is_admin:
        q = select(Post).where(Post.is_deleted == False).order_by(Post.created_at.desc())
    else:
        q = (
            select(Post)
            .join(Artist, Post.artist_id == Artist.id)
            .where(Post.is_deleted == False, Artist.owner_id == user.id)
            .order_by(Post.created_at.desc())
        )
    return db.execute(q).scalars().all()

def _render_admin_home(request: Request, db: Session, user: User):
    posts = _fetch_posts_for_user(db, user)
    my_posts_count = len(posts)
    total_likes = sum(int(p.likes or 0) for p in posts)
    return templates.TemplateResponse(
        "admin.html",
        ctx(request, user=user, posts=posts, my_posts_count=my_posts_count, total_likes=total_likes),
    )

@app.get("/admin", response_class=HTMLResponse, name="admin_root")
def admin_root(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
    return _render_admin_home(request, db, user)

@app.get("/admin/posts", response_class=HTMLResponse, name="admin_posts")
def admin_posts(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
    posts = _fetch_posts_for_user(db, user)
    
    # 各投稿に編集可能フラグを追加
    posts_with_permission = []
    for post in posts:
        setattr(post, 'can_edit', can_edit_post(user, post, db))
        posts_with_permission.append(post)
    
    return templates.TemplateResponse("admin_posts.html", ctx(request, user=user, posts=posts_with_permission))

@app.get("/admin/new_post", response_class=HTMLResponse, name="admin_post_new")
def admin_post_new(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
    if user.is_admin:
        # 管理者の場合：全アーティストを表示（自分のものを優先）
        my_artists = db.scalars(
            select(Artist)
            .where(Artist.owner_id == user.id)
            .order_by(Artist.name.asc())
        ).all()
        
        other_artists = db.scalars(
            select(Artist)
            .where(
                (Artist.owner_id != user.id) | (Artist.owner_id == None)
            )
            .order_by(Artist.name.asc())
        ).all()
        
        artists = my_artists + other_artists
    else:
        # 一般ユーザーの場合：自分に紐付くアーティストのみ
        artists = db.scalars(
            select(Artist)
            .where(Artist.owner_id == user.id)
            .order_by(Artist.name.asc())
        ).all()
        my_artists = artists
    
    return templates.TemplateResponse(
        "admin_new.html", 
        ctx(request, user=user, artists=artists, my_artists=my_artists)
    )

@app.post("/admin/posts", response_class=HTMLResponse, name="admin_post_create")
def admin_post_create(
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    artist_id: Annotated[int, Form()] = 0,
    url_youtube: Annotated[Optional[str], Form()] = None,
    url_spotify: Annotated[Optional[str], Form()] = None,
    url_apple: Annotated[Optional[str], Form()] = None,
):
    artist = db.get(Artist, artist_id)
    if not artist:
        raise HTTPException(404, "artist_not_found")
    
    if not user.is_admin and artist.owner_id != user.id:
        raise HTTPException(403, "このアーティストで投稿する権限がありません")
    
    # ユニークなslugを生成
    while True:
        slug = generate_slug()
        if not db.query(Post).filter(Post.slug == slug).first():
            break
    
    post = Post(
        slug=slug,  # 追加
        title=title,
        body=body,
        artist_id=artist_id,
        likes=0,
        is_deleted=False,
        url_youtube=url_youtube,
        url_spotify=url_spotify,
        url_apple=url_apple,
    )
    db.add(post)
    db.commit()
    return admin_posts(request, user=user, db=db)


@app.get("/admin/posts/{post_id}/edit", response_class=HTMLResponse, name="admin_post_edit")
def admin_post_edit_page(
    post_id: int, 
    request: Request, 
    user: User = Depends(require_login),  # require_admin → require_login に変更
    db: Session = Depends(get_db)
):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")
    
    # 編集権限チェック
    if not can_edit_post(user, post, db):
        raise HTTPException(403, "このアーティストの投稿を編集する権限がありません")
    
    # 編集可能なアーティストのリストを取得
    if user.is_admin:
        artists = db.scalars(select(Artist).order_by(Artist.name.asc())).all()
    else:
        # 一般ユーザーは自分に紐付くアーティストのみ
        artists = db.scalars(
            select(Artist)
            .where(Artist.owner_id == user.id)
            .order_by(Artist.name.asc())
        ).all()
    
    return templates.TemplateResponse("admin_post_edit.html", ctx(request, user=user, post=post, artists=artists))


@app.post("/admin/posts/{post_id}/edit", response_class=HTMLResponse, name="admin_post_update")
def admin_post_update(
    post_id: int,
    request: Request,
    user: User = Depends(require_login),  # require_admin → require_login に変更
    db: Session = Depends(get_db),
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    artist_id: Annotated[int, Form()] = 0,
    url_youtube: Annotated[Optional[str], Form()] = None,
    url_spotify: Annotated[Optional[str], Form()] = None,
    url_apple: Annotated[Optional[str], Form()] = None,
):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")
    
    # 編集権限チェック
    if not can_edit_post(user, post, db):
        raise HTTPException(403, "このアーティストの投稿を編集する権限がありません")
    
    # アーティスト変更時の権限チェック
    if artist_id != post.artist_id:
        new_artist = db.get(Artist, artist_id)
        if not new_artist:
            raise HTTPException(404, "artist_not_found")
        
        # 管理者以外は自分に紐付くアーティストにしか変更できない
        if not user.is_admin and new_artist.owner_id != user.id:
            raise HTTPException(403, "このアーティストへの変更権限がありません")
    
    post.title = title
    post.body = body
    post.artist_id = artist_id
    post.url_youtube = url_youtube
    post.url_spotify = url_spotify
    post.url_apple = url_apple
    db.add(post)
    db.commit()
    return admin_posts(request, user=user, db=db)


@app.post("/admin/posts/{post_id}/delete", response_class=HTMLResponse, name="admin_post_delete")
def admin_post_delete(
    post_id: int,
    request: Request,
    user: User = Depends(require_login),  # require_admin → require_login に変更
    db: Session = Depends(get_db)
):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post_not_found")
    
    # 削除権限チェック
    if not can_edit_post(user, post, db):
        raise HTTPException(403, "このアーティストの投稿を削除する権限がありません")
    
    post.is_deleted = True
    db.add(post)
    db.commit()
    return admin_posts(request, user=user, db=db)

# アーティスト
@app.get("/admin/artists", response_class=HTMLResponse, name="admin_artists")
def admin_artists(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    artists = db.scalars(select(Artist).order_by(Artist.name.asc())).all()
    users = db.scalars(select(User).order_by(User.id.desc())).all()
    return templates.TemplateResponse("admin_artists.html", ctx(request, user=user, artists=artists, users=users))

@app.post("/admin/artists", response_class=HTMLResponse, name="admin_artist_create")
def admin_artist_create(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    name: Annotated[str, Form()] = "",
):
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name_required")
    exists = db.scalar(select(Artist).where(Artist.name == name))
    if not exists:
        # ユニークなslugを生成
        while True:
            slug = generate_slug()
            if not db.query(Artist).filter(Artist.slug == slug).first():
                break
        
        artist = Artist(slug=slug, name=name, owner_id=user.id)  # slugを追加
        db.add(artist)
        db.commit()
    return admin_artists(request, user=user, db=db)

@app.get("/api/admin/users/search", name="admin_user_search")
def admin_user_search(
    q: str = "",
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """管理者用：メールアドレスの部分一致検索API（全ユーザー対象）"""
    if not q or len(q) < 1:
        return {"users": []}
    
    # メールアドレスで部分一致検索（全ユーザー）
    users = db.query(User).filter(
        User.email.contains(q)
    ).limit(5).all()
    
    return {
        "users": [
            {"id": u.id, "email": u.email, "is_admin": u.is_admin}
            for u in users
        ]
    }


@app.get("/admin/artists/{artist_id}/edit", response_class=HTMLResponse, name="admin_artist_edit")
def admin_artist_edit_page(
    artist_id: int, 
    request: Request, 
    user: User = Depends(require_admin), 
    db: Session = Depends(get_db)
):
    artist = db.get(Artist, artist_id)
    if not artist:
        raise HTTPException(404, "artist_not_found")
    
    # 現在のオーナー情報を取得
    current_owner = None
    if artist.owner_id:
        current_owner = db.get(User, artist.owner_id)
    
    return templates.TemplateResponse(
        "artist_edit.html", 
        ctx(request, user=user, artist=artist, current_owner=current_owner, error=None)
    )


@app.post("/admin/artists/{artist_id}/edit", response_class=HTMLResponse, name="admin_artist_update")
def admin_artist_update(
    artist_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    name: Annotated[str, Form()] = "",
    owner_email: Annotated[str, Form()] = "",  # メールアドレスで受け取る
):
    artist = db.get(Artist, artist_id)
    if not artist:
        raise HTTPException(404, "artist_not_found")
    
    # 名前の更新
    artist.name = (name or "").strip()
    
    # オーナーの更新（メールアドレスから検索）
    owner_email = (owner_email or "").strip()
    if owner_email:
        # メールアドレスからユーザーを検索（管理者・一般問わず）
        owner = db.query(User).filter(User.email == owner_email).first()
        if owner:
            artist.owner_id = owner.id
        else:
            # 該当するユーザーが見つからない場合はエラー
            return templates.TemplateResponse(
                "artist_edit.html", 
                ctx(request, user=user, artist=artist, error="指定されたユーザーが見つかりません。")
            )
    else:
        # 空欄の場合は紐付け解除
        artist.owner_id = None
    
    db.add(artist)
    db.commit()
    return admin_artists(request, user=user, db=db)

# ユーザー
@app.get("/admin/users", response_class=HTMLResponse, name="admin_users")
def admin_users(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.id.desc())).all()
    admin_count = db.scalar(select(func.count()).select_from(User).where(User.is_admin == True)) or 0
    return templates.TemplateResponse("admin_users.html", ctx(request, user=user, users=users, admin_count=admin_count))

@app.get("/admin/users/new", response_class=HTMLResponse, name="admin_user_new")
def admin_user_new(request: Request, user: User = Depends(require_admin)):
    return templates.TemplateResponse("admin_user_new.html", ctx(request, user=user, error=None))

@app.post("/admin/users/new", response_class=HTMLResponse, name="admin_user_create")
def admin_user_create(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    password2: Annotated[str, Form()] = "",
    is_admin: Annotated[bool, Form()] = False,
):
    email = (email or "").strip().lower()
    if not email or not password:
        return templates.TemplateResponse("admin_user_new.html", ctx(request, user=user, error="必須項目が未入力です。"), status_code=400)
    if password != password2:
        return templates.TemplateResponse("admin_user_new.html", ctx(request, user=user, error="パスワードが一致しません。"), status_code=400)
    exists = db.query(User).filter(User.email == email).first()
    if exists:
        return templates.TemplateResponse("admin_user_new.html", ctx(request, user=user, error="そのメールは既に存在します。"), status_code=400)
    u = User(email=email, password_hash=hash_password(password), is_admin=bool(is_admin))
    db.add(u)
    db.commit()
    return admin_users(request, user=user, db=db)

@app.get("/admin/users/{uid}/password", response_class=HTMLResponse, name="admin_user_password_page")
def admin_user_password_page(uid: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, "user_not_found")
    return templates.TemplateResponse("admin_user_password.html", ctx(request, user=user, target=target, error=None))

@app.post("/admin/users/{uid}/password", response_class=HTMLResponse, name="admin_user_password_update")
def admin_user_password_update(
    uid: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    password: Annotated[str, Form()] = "",
    password2: Annotated[str, Form()] = "",
):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, "user_not_found")
    if not password:
        return templates.TemplateResponse("admin_user_password.html", ctx(request, user=user, target=target, error="パスワード必須"), status_code=400)
    if password != password2:
        return templates.TemplateResponse("admin_user_password.html", ctx(request, user=user, target=target, error="パスワードが一致しません"), status_code=400)
    target.password_hash = hash_password(password)
    db.add(target)
    db.commit()
    return admin_users(request, user=user, db=db)

@app.post("/admin/users/{uid}/delete", response_class=HTMLResponse, name="admin_user_delete")
def admin_user_delete(
    uid: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, "user_not_found")
    
    # 自分自身は削除できない
    if user.id == target.id:
        raise HTTPException(400, "cannot_delete_self")
    
    # 最後の管理者は削除できない
    if target.is_admin:
        admin_count = db.scalar(select(func.count()).select_from(User).where(User.is_admin == True)) or 0
        if admin_count <= 1:
            raise HTTPException(400, "cannot_delete_last_admin")
    
    db.delete(target)
    db.commit()
    return admin_users(request, user=user, db=db)
