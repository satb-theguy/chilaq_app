from __future__ import annotations
from pathlib import Path
import os, random, logging, time
from typing import Optional

from app.utils import youtube_embed, spotify_embed, apple_embed, resolve_thumbnail_for_post

from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, desc
from sqlalchemy.exc import IntegrityError

from .db import Base, engine, get_db, SessionLocal
from .models import User, Artist, Post, slugify
from .utils import hash_password, verify_password

# =========================
# アプリ基本設定
# =========================
BASE_DIR = Path(__file__).parent
app = FastAPI(title="Chilaq 🎵 — 音楽ディグ SNS (MVP)")

# セッション (Cookie) — ログイン状態を保持
# 👉 SECRET_KEY は Render 環境では環境変数に設定してください
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="chilaq_sess", https_only=False)

# 静的ファイル / テンプレート
app.mount("/static", StaticFiles(directory=BASE_DIR / "../static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "../templates"))

# ログ
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chilaq")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _like_post_core(db: Session, post_id: int, request: Request, response: Response):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    # 同一ブラウザの二重加算をクッキーで防止（既に押していたら加算しない）
    already = request.cookies.get(f"liked_{post_id}") == "1"
    if not already:
        post.likes = (post.likes or 0) + 1
        db.add(post)
        db.commit()
        response.set_cookie(
            key=f"liked_{post_id}", value="1",
            max_age=60*60*24*365*5,  # 5年
            httponly=False, samesite="Lax", secure=True  # 本番HTTPS想定
        )
    return {"likes": post.likes or 0, "liked": True}

# =========================
# ヘルパ：現在のユーザー
# =========================
def current_user(request: Request, db: Session) -> Optional[User]:
    """セッションから user_id を読み、DB からユーザーを取得します。"""
    uid = request.session.get("user_id")
    if not uid: return None
    return db.get(User, uid)

def require_login(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="login_required")
    return user


# =========================
# 初期化：テーブル作成 & ダミーデータ
# =========================
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(engine)
    # 既にユーザーがいれば seed 済みとみなす
    with next(get_db()) as db:
        if not db.execute(select(func.count(User.id))).scalar():
            # 管理者ユーザー作成（パスワードは demo1234）
            admin = User(email="admin@chilaq.jp", password_hash=hash_password("demo1234"), is_admin=True)
            db.add(admin); db.flush()  # flush すると admin.id が取れる

            # アーティスト 3名（A/B/C）を用意し、C は admin の所有にしてみる
            a1 = Artist(name="City Wanderer", slug=slugify("City Wanderer"), twitter="https://x.com/citywand")
            a2 = Artist(name="Neon Loft", slug=slugify("Neon Loft"), instagram="https://instagram.com/neonloft")
            a3 = Artist(name="Echo Lake", slug=slugify("Echo Lake"), spotify="https://open.spotify.com/artist/2N9...")
            a3.owner_id = admin.id
            db.add_all([a1,a2,a3]); db.flush()

            # 各アーティスト 3投稿（YouTube/Spotify/Apple を混在）
            posts_data = [
                (a1, "Night Drive", "https://youtu.be/dQw4w9WgXcQ", None, None),
                (a1, "City Lights", None, "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl", None),
                (a1, "Early Morning", None, None, "https://embed.music.apple.com/jp/album/1450695604?i=1450695605"),
                (a2, "Loft Jazz", "https://www.youtube.com/watch?v=aqz-KE-bpKQ", None, None),
                (a2, "Rain on Window", None, "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b", None),
                (a2, "Wooden Floor", None, None, "https://embed.music.apple.com/jp/album/1440881047?i=1440881052"),
                (a3, "Waveforms", "https://youtu.be/3JZ_D3ELwOQ", None, None),
                (a3, "Quiet Bay", None, "https://open.spotify.com/track/7ouMYWpwJ422jRcDASZB7P", None),
                (a3, "Foggy Noon", None, None, "https://embed.music.apple.com/jp/album/1440651591?i=1440651592"),
            ]
            for art, title, yt, sp, am in posts_data:
                p = Post(title=title, artist_id=art.id, url_youtube=yt, url_spotify=sp, url_apple=am, hearts=random.randint(0,50))
                db.add(p)
            db.commit()
            logger.info("Seeded admin user and sample artists/posts.")


# =========================
# 公開ページ
# =========================
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    # 公開フィード用の投稿を取得（削除除外）
    posts = db.execute(
        select(Post).where(Post.is_deleted == False).order_by(Post.created_at.desc()).limit(30)
    ).scalars().all()

    # テンプレに渡す用：サムネURL付きの辞書へ
    cards = [
        {"post": p, "thumb": resolve_thumbnail_for_post(p)}
        for p in posts
    ]

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "cards": cards}
    )

@app.get("/p/{post_id}", response_class=HTMLResponse)
def post_detail(post_id: int, request: Request, db: Session = Depends(get_db)):
    """
    投稿の詳細ページ。
    - DBから該当の Post を取得
    - 各サービス用の埋め込みURLを生成
    - Appleは高さも一緒にテンプレへ渡す（曲=175px、アルバム/プレイリスト=450px）
    """
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")

    # 1) 各サービスの埋め込みURLを生成（utils側で正規化）
    yt_src = youtube_embed(post.url_youtube)     # 例: "https://www.youtube.com/embed/xxxx" or None
    sp_src = spotify_embed(post.url_spotify)     # 例: "https://open.spotify.com/embed/track/..." or None
    am_src, am_h = apple_embed(post.url_apple)   # 例: ("https://embed.music.apple.com/..", 175/450) or (None, None)

    # 2) テンプレに渡す辞書を組み立て
    embeds = {
        "youtube": yt_src,       # <iframe src="{{ embeds.youtube }}"> で使う
        "spotify": sp_src,       # <iframe src="{{ embeds.spotify }}"> で使う
        "apple": am_src,         # <iframe src="{{ embeds.apple   }}"> で使う
        "apple_h": am_h or 450,  # 高さ。None のときの保険として 450 を既定に
    }

    # 3) テンプレへ渡す
    return templates.TemplateResponse(
        "post_detail.html",
        {
            "request": request,  # Jinja2 のお作法：必ず request を渡す
            "post": post,        # タイトル、アーティスト表示などで利用
            "embeds": embeds,    # 上で作った埋め込み情報
        },
    )

@app.get("/artist/{slug}", response_class=HTMLResponse)
def artist_page(slug: str, request: Request, db: Session = Depends(get_db)):
    artist = db.execute(select(Artist).where(Artist.slug == slug)).scalar_one_or_none()
    if not artist:
        raise HTTPException(404, "artist_not_found")
    posts = db.execute(select(Post).where(Post.artist_id == artist.id, Post.is_deleted == False).order_by(desc(Post.created_at))).scalars().all()
    return templates.TemplateResponse("artist.html", {
        "request": request,
        "artist": artist,
        "posts": posts,
    })


@app.get("/about", response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    """Aboutページ用の簡易統計を出してテンプレに渡す。"""
    artists = db.execute(select(func.count(Artist.id))).scalar() or 0
    posts   = db.execute(select(func.count(Post.id)).where(Post.is_deleted == False)).scalar() or 0
    likes   = db.execute(select(func.sum(Post.hearts)).where(Post.is_deleted == False)).scalar() or 0
    stats = {"artists": artists, "posts": posts, "likes": likes or 0}
    return templates.TemplateResponse("about.html", {
        "request": request,
        "stats": stats,
        "title": "About | Chilaq",
    })

# =========================
# いいね(♥) — 認証不要の簡易 API
# =========================
@app.post("/api/like/{post_id}")
def api_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")

    # --- 連打レート制限（1.5秒） ---
    now = time.time()
    last_ts = request.session.get("last_like_ts", 0)
    if now - last_ts < 1.5:
        return {"ok": False, "reason": "rate_limited", "hearts": post.hearts, "liked": False}

    # --- 1投稿1回ルール（セッション） ---
    liked_posts = set(request.session.get("liked_posts", []))
    if post_id in liked_posts:
        # 既にいいね済み → カウントは増やさない
        request.session["last_like_ts"] = now
        return {"ok": False, "reason": "already_liked", "hearts": post.hearts, "liked": True}

    # まだなら加算＆記録
    post.hearts += 1
    db.commit()
    liked_posts.add(post_id)
    request.session["liked_posts"] = list(liked_posts)
    request.session["last_like_ts"] = now

    return {"ok": True, "hearts": post.hearts, "liked": True}


@app.post("/posts/{post_id}/like", name="like_post")
def like_post(post_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    return _like_post_core(db, post_id, request, response)

# 互換：/api/posts/{id}/like
@app.post("/api/posts/{post_id}/like", include_in_schema=False)
def like_post_api(post_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    return _like_post_core(db, post_id, request, response)

# 互換：/p/{id}/like
@app.post("/p/{post_id}/like", include_in_schema=False)
def like_post_short(post_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    return _like_post_core(db, post_id, request, response)


# =========================
# ログイン / ログアウト
# =========================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def do_login(request: Request, db: Session = Depends(get_db), email: str = Form(...), password: str = Form(...)):
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "メールまたはパスワードが違います"}, status_code=400)
    request.session["user_id"] = user.id
    request.session["is_admin"] = bool(user.is_admin)
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/logout")
def do_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


# =========================
# ダッシュボード（招待アーティスト / 管理）
# =========================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if user.is_admin:
        total_hearts = db.execute(
            select(func.sum(Post.hearts)).where(Post.is_deleted == False)
        ).scalar() or 0
        my_posts_count = db.execute(
            select(func.count(Post.id)).where(Post.is_deleted == False)
        ).scalar() or 0
    else:
        artist_ids = [a.id for a in user.artists]
        if artist_ids:
            cond = (Post.is_deleted == False, Post.artist_id.in_(artist_ids))
            total_hearts = db.execute(
                select(func.sum(Post.hearts)).where(*cond)
            ).scalar() or 0
            my_posts_count = db.execute(
                select(func.count(Post.id)).where(*cond)
            ).scalar() or 0
        else:
            total_hearts = 0
            my_posts_count = 0

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_hearts": total_hearts,
        "my_posts_count": my_posts_count
    })

@app.get("/dashboard/posts", response_class=HTMLResponse)
def dashboard_posts(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    q = select(Post).where(Post.is_deleted == False).options(joinedload(Post.artist)).order_by(desc(Post.created_at))
    if not user.is_admin:
        artist_ids = [a.id for a in user.artists]
        if artist_ids:
            q = q.where(Post.artist_id.in_(artist_ids))
        else:
            q = q.where(Post.id == -1)  # 所有なし→空

    posts = db.execute(q).scalars().all()
    return templates.TemplateResponse("dashboard_posts.html", {"request": request, "user": user, "posts": posts})

@app.post("/dashboard/posts/{post_id}/delete")
def dashboard_delete_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post_not_found")
    if not user.is_admin:
        # 所有アーティストの投稿のみ削除可
        if post.artist_id not in [a.id for a in user.artists]:
            raise HTTPException(403, "forbidden")
    post.is_deleted = True
    db.commit()
    return RedirectResponse(url="/dashboard/posts", status_code=302)

@app.get("/dashboard/new", response_class=HTMLResponse)
def dashboard_new(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    # 管理者は全アーティストに代理投稿可能。一般は自分のアーティストのみ。
    artists = db.execute(select(Artist) if user.is_admin else select(Artist).where(Artist.owner_id == user.id)).scalars().all()
    return templates.TemplateResponse("dashboard_new.html", {"request": request, "user": user, "artists": artists})

@app.post("/dashboard/new")
def dashboard_create_post(
    request: Request, db: Session = Depends(get_db),
    title: str = Form(...), artist_id: int = Form(...),
    url_youtube: str = Form(None), url_spotify: str = Form(None), url_apple: str = Form(None),
):
    user = require_login(request, db)
    artist = db.get(Artist, artist_id)
    if not artist:
        raise HTTPException(400, "artist_not_found")
    if not user.is_admin and artist.owner_id != user.id:
        raise HTTPException(403, "forbidden")
    p = Post(title=title.strip(), artist_id=artist.id,
             url_youtube=(url_youtube or None),
             url_spotify=(url_spotify or None),
             url_apple=(url_apple or None))
    db.add(p); db.commit()
    return RedirectResponse(url=f"/p/{p.id}", status_code=302)


# =========================
# 管理：アーティスト管理（作成・紐づけ）
# =========================
@app.get("/admin/artists", response_class=HTMLResponse)
def admin_artists(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not user.is_admin:
        raise HTTPException(403, "forbidden")
    artists = db.execute(select(Artist).order_by(Artist.name)).scalars().all()
    users = db.execute(select(User).order_by(User.email)).scalars().all()
    return templates.TemplateResponse("admin_artists.html", {"request": request, "artists": artists, "users": users})

@app.post("/admin/artists/create")
def admin_create_artist(request: Request, db: Session = Depends(get_db), name: str = Form(...)):
    user = require_login(request, db)
    if not user.is_admin:
        raise HTTPException(403, "forbidden")
    name = name.strip()
    if not name:
        raise HTTPException(400, "name_required")
    artist = Artist(name=name, slug=slugify(name))
    db.add(artist); db.commit()
    return RedirectResponse(url="/admin/artists", status_code=302)

@app.post("/admin/artists/link")
def admin_link_artist(request: Request, db: Session = Depends(get_db), artist_id: int = Form(...), user_id: int = Form(...)):
    user = require_login(request, db)
    if not user.is_admin:
        raise HTTPException(403, "forbidden")
    artist = db.get(Artist, artist_id)
    target = db.get(User, user_id)
    if not artist or not target:
        raise HTTPException(400, "not_found")
    artist.owner_id = target.id
    db.commit()
    return RedirectResponse(url="/admin/artists", status_code=302)

# --- Artist: 編集ページ 表示 ---
@app.get("/admin/artists/{artist_id}/edit", name="admin_artist_edit_page")
def admin_artist_edit_page(artist_id: int, request: Request):
    require_admin(request)
    with SessionLocal() as db:
        artist = db.get(Artist, artist_id)
        if not artist:
            raise HTTPException(status_code=404, detail="artist not found")
    return templates.TemplateResponse("artist_edit.html", {
        "request": request,
        "title": "アーティスト編集",
        "artist": artist,
    })

# --- Artist: 更新保存 ---
@app.post("/admin/artists/{artist_id}/edit", name="admin_artist_update")
def admin_artist_update(
    artist_id: int,
    request: Request,
    name: str = Form(...),
    website: str | None = Form(None),
    x_url: str | None = Form(None),          # X(Twitter)
    spotify_url: str | None = Form(None),
    bio: str | None = Form(None),
):
    require_admin(request)
    with SessionLocal() as db:
        artist = db.get(Artist, artist_id)
        if not artist:
            raise HTTPException(status_code=404, detail="artist not found")

        # 必須：名前
        name = (name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        artist.name = name
        # 名前が変わったら slug も更新（models.py の slugify を利用）
        artist.slug = slugify(name)
        artist.website = (website or "").strip() or None
        artist.x_url = (x_url or "").strip() or None
        artist.spotify_url = (spotify_url or "").strip() or None
        artist.bio = (bio or "").strip() or None

        db.add(artist)
        db.commit()

    # 一覧に戻す（既存の一覧ルート名が別なら合わせて変更）
    return RedirectResponse(url=request.url_for("admin_artists"), status_code=303)

# =========================
# 投稿の編集（所有 or 管理者）
# =========================
from fastapi import Form  # 既にインポート済みなら重複OK

@app.get("/dashboard/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_page(post_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)  # ログイン必須
    post = db.get(Post, post_id)       # 編集対象の投稿データ
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")
    # 権限: 管理者 or 自分がオーナーのアーティストの投稿
    if (not user.is_admin) and (post.artist_id not in [a.id for a in user.artists]):
        raise HTTPException(403, "forbidden")
    return templates.TemplateResponse(
        "dashboard_post_edit.html",
        {"request": request, "user": user, "post": post}
    )

@app.post("/dashboard/posts/{post_id}/edit")
def edit_post(
    post_id: int, request: Request, db: Session = Depends(get_db),
    title: str = Form(...),
    url_youtube: str = Form(None),
    url_spotify: str = Form(None),
    url_apple: str = Form(None),
):
    user = require_login(request, db)
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(404, "post_not_found")
    if (not user.is_admin) and (post.artist_id not in [a.id for a in user.artists]):
        raise HTTPException(403, "forbidden")
    # 保存（入力→DB）
    post.title = title.strip()
    post.url_youtube = (url_youtube or None)
    post.url_spotify = (url_spotify or None)
    post.url_apple = (url_apple or None)
    db.commit()
    return RedirectResponse(url=f"/p/{post.id}", status_code=302)


# =========================
# アーティスト情報の編集
# - 管理者: すべてのアーティストを編集 & 所有ユーザーの再割当が可能
# - 一般ユーザー: 自分が owner のアーティストのみ編集可（名前・SNSリンク）
# =========================
@app.get("/admin/users/{user_id}/password", response_class=HTMLResponse)
def admin_user_password_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    me = require_login(request, db)
    if not me.is_admin:
        raise HTTPException(403, "forbidden")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "user_not_found")
    return templates.TemplateResponse("admin_user_password.html", {
        "request": request,
        "user": me,        # 現在ログイン中
        "target": target,  # 対象ユーザー
        "error": None
    })

@app.post("/admin/users/{user_id}/password")
def admin_user_password(
    user_id: int, request: Request, db: Session = Depends(get_db),
    password: str = Form(...), password2: str = Form(...)
):
    me = require_login(request, db)
    if not me.is_admin:
        raise HTTPException(403, "forbidden")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "user_not_found")

    pwd = password.strip()
    if pwd != password2:
        return templates.TemplateResponse("admin_user_password.html", {
            "request": request, "user": me, "target": target,
            "error": "パスワードが一致しません。"
        }, status_code=400)
    if len(pwd) < 8:
        return templates.TemplateResponse("admin_user_password.html", {
            "request": request, "user": me, "target": target,
            "error": "8文字以上にしてください。"
        }, status_code=400)

    target.password_hash = hash_password(pwd)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@app.post("/admin/users/{user_id}/delete")
def admin_user_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    """ユーザー削除（管理者のみ）
    - 自分自身は削除不可（誤爆防止）
    - 最後のadminは削除不可（ロックアウト防止）
    """
    me = require_login(request, db)
    if not me.is_admin:
        raise HTTPException(403, "forbidden")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "user_not_found")

    # 自分は削除させない
    if target.id == me.id:
        raise HTTPException(400, "cannot_delete_self")

    # 最後のadminの削除を防止
    if target.is_admin:
        others_admins = db.execute(
            select(func.count(User.id)).where(User.is_admin == True, User.id != target.id)
        ).scalar() or 0
        if others_admins == 0:
            raise HTTPException(400, "cannot_delete_last_admin")

    # FK は Artist.owner_id ON DELETE SET NULL のため、そのまま削除OK
    db.delete(target)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


# （任意）一覧で「何人がadminか」をテンプレで使う場合は /admin/users をこうしておくと便利：
@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db)):
    me = require_login(request, db)
    if not me.is_admin:
        raise HTTPException(403, "forbidden")
    users = db.execute(select(User).order_by(User.id.asc())).scalars().all()
    admin_count = db.execute(select(func.count(User.id)).where(User.is_admin == True)).scalar() or 0
    return templates.TemplateResponse("admin_users.html", {
        "request": request, "user": me, "users": users, "admin_count": admin_count
    })


@app.post("/admin/users/new")
def admin_users_new(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    is_admin: str | None = Form(None),   # ← ここがポイント：チェックボックス対策
):
    me = require_login(request, db)
    if not me.is_admin:
        raise HTTPException(403, "forbidden")

    email = email.strip().lower()
    if password != password2:
        return templates.TemplateResponse(
            "admin_user_new.html",
            {
                "request": request, "user": me,
                "error": "パスワードが一致しません。",
                "email": email, "is_admin": (is_admin is not None)
            },
            status_code=400
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "admin_user_new.html",
            {
                "request": request, "user": me,
                "error": "8文字以上にしてください。",
                "email": email, "is_admin": (is_admin is not None)
            },
            status_code=400
        )

    # 既存チェック（アプリ側）
    exists = db.execute(select(User).where(User.email == email)).scalar()
    if exists:
        return templates.TemplateResponse(
            "admin_user_new.html",
            {
                "request": request, "user": me,
                "error": "このメールアドレスは既に登録されています。",
                "email": email, "is_admin": (is_admin is not None)
            },
            status_code=400
        )

    # 登録
    u = User(
        email=email,
        password_hash=hash_password(password),
        is_admin=bool(is_admin is not None),  # ← "on" 等の文字列を True に
    )
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "admin_user_new.html",
            {
                "request": request, "user": me,
                "error": "このメールアドレスは既に登録されています。（一意制約）",
                "email": email, "is_admin": (is_admin is not None)
            },
            status_code=400
        )

    return RedirectResponse(url="/admin/users", status_code=302)

def require_admin(request: Request):
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin only")
