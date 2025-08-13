"""小さなユーティリティ集。

- パスワードハッシュ（最低限）
- 埋め込みURLの生成（YouTube / Spotify / Apple Music）
"""
from __future__ import annotations
import hashlib, hmac, os, re, httpx
from urllib.parse import urlparse, parse_qs
from functools import lru_cache

def hash_password(password: str) -> str:
    """デモ用の簡易ハッシュ。実運用では passlib[bcrypt] を推奨。"""
    salt = os.environ.get("PWD_SALT", "chilaq-dev-salt").encode()
    return hashlib.sha256(salt + password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), password_hash)

_YT_ID_PATTERNS = [
    re.compile(r"(?:v=|vi=)([A-Za-z0-9_-]{11})"),          # youtube.com/watch?v=XXXX
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),          # youtu.be/XXXX
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"), # youtube.com/embed/XXXX
]

def youtube_embed(url: str | None) -> str | None:
    if not url: return None
    # https://www.youtube.com/watch?v=XXXX → https://www.youtube.com/embed/XXXX
    q = urlparse(url)
    if "youtube.com" in q.netloc:
        vid = parse_qs(q.query).get("v", [None])[0]
        if vid: return f"https://www.youtube.com/embed/{vid}"
    if "youtu.be" in q.netloc:
        vid = q.path.lstrip("/")
        if vid: return f"https://www.youtube.com/embed/{vid}"
    return None

def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    for pat in _YT_ID_PATTERNS:
        m = pat.search(u)
        if m:
            return m.group(1)
    # 予備: v= がクエリにいるか
    try:
        pr = urlparse(u)
        vid = parse_qs(pr.query).get("v", [None])[0]
        if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            return vid
    except Exception:
        pass
    return None

def youtube_thumbnail(url: str | None) -> str | None:
    vid = youtube_id(url)
    if not vid:
        return None
    # maxres は存在しないことがあるので hqdefault を採用（安定）
    return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

def spotify_embed(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    pr = urlparse(u)
    if pr.scheme not in ("http", "https"):
        return None
    if pr.netloc != "open.spotify.com":
        return None

    # パスを分解
    parts = [p for p in pr.path.split("/") if p]
    # 例:
    #  - ["embed", "track", "{ID}"]
    #  - ["track", "{ID}"]
    #  - ["intl-ja", "track", "{ID}"]

    def build(kind: str, sid: str) -> str:
        return f"https://open.spotify.com/embed/{kind}/{sid}"

    if not parts:
        return None

    # embed 形式（そのまま正規化して返す）
    if parts[0] == "embed" and len(parts) >= 3 and parts[1] in ("track", "album", "playlist"):
        kind, sid = parts[1], parts[2]
        return build(kind, sid)

    # intl-xx をスキップ
    idx = 0
    if parts[0].startswith("intl-"):
        idx = 1

    if len(parts) >= idx + 2 and parts[idx] in ("track", "album", "playlist"):
        kind, sid = parts[idx], parts[idx + 1]
        return build(kind, sid)

    return None


@lru_cache(maxsize=512)
def spotify_thumbnail(url: str | None) -> str | None:
    if not url:
        return None
    try:
        r = httpx.get("https://open.spotify.com/oembed", params={"url": url}, timeout=3.0)
        if r.status_code == 200:
            t = r.json().get("thumbnail_url")
            if t:
                return t.replace("http://", "https://")
    except Exception:
        pass
    return None



def apple_embed(url: str | None) -> tuple[str | None, int | None]:
    if not url:
        return None, None
    u = url.strip()
    pr = urlparse(u)
    if pr.scheme not in ("http", "https"):
        return None, None
    if pr.netloc not in ("music.apple.com", "embed.music.apple.com"):
        return None, None

    # 埋め込み用ホストに正規化
    src = f"https://embed.music.apple.com{pr.path}"
    if pr.query:
        src += f"?{pr.query}"

    path = pr.path.lower()
    # ルール:
    # - /album/ か /playlist/（かつ ?i= が無い）→ 一覧型 → 450px
    # - /song/ または /album/... ?i=...（単曲） → 175px
    if "/playlist/" in path:
        height = 450
    elif "/album/" in path and "i=" not in (pr.query or ""):
        height = 450
    else:
        height = 175

    return src, height

# --- Apple Music: 埋め込みからは安全に画像が取れないので今は None ------------
def apple_thumbnail(url: str | None) -> str | None:
    # 将来: iTunes Search API 等で取得する（現状はプレースホルダにフォールバック）
    return None


# --- 優先順位で決定 --------------------------------------------

def resolve_thumbnail_for_post(post) -> str:
    """
    優先順位: YouTube → Spotify → Apple → プレースホルダ
    戻り値は表示用の画像URL
    """
    for getter, src in (
        (youtube_thumbnail, post.url_youtube),
        (spotify_thumbnail, post.url_spotify),
        (apple_thumbnail,   post.url_apple),
    ):
        if not src:
            continue
        img = getter(src)
        if img:
            return img
    # ローカルのプレースホルダ
    return "/static/placeholder.svg"