# app/utils.py
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

# ---- Password Hashing ----
def _pbkdf2_sha256(password: str, salt: bytes, iterations: int = 260000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def hash_password(password: str) -> str:
    iterations = 260000
    salt = os.urandom(16)
    dk = _pbkdf2_sha256(password, salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("plain:"):
        return stored[6:] == password
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
            iterations = int(iters_s)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            calc = _pbkdf2_sha256(password, salt, iterations)
            return hmac.compare_digest(calc, expected)
        except Exception:
            return False
    return stored == password  # 開発時の平文フォールバック

# ---- Embeds ----
def _extract_youtube_id(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "youtube.com/watch" in url and "v=" in url:
        return url.split("v=")[1].split("&")[0]
    return None

def youtube_embed(url: Optional[str]) -> Optional[str]:
    vid = _extract_youtube_id(url)
    if not vid:
        return None
    return f"https://www.youtube.com/embed/{vid}"

def spotify_embed(url: Optional[str]) -> Optional[str]:
    """
    Spotify URLからembed URLを生成
    対応フォーマット:
    - https://open.spotify.com/track/xxx
    - https://open.spotify.com/intl-ja/track/xxx
    - https://open.spotify.com/album/xxx
    - https://open.spotify.com/playlist/xxx
    - https://open.spotify.com/episode/xxx
    """
    if not url:
        return None
    
    try:
        # 正規表現でSpotify URLをパース
        # intl-xx などの国際化パスにも対応
        pattern = r'https://open\.spotify\.com/(?:intl-[a-z]{2}/)?([a-z]+)/([a-zA-Z0-9]+)'
        match = re.match(pattern, url)
        
        if match:
            content_type = match.group(1)  # track, album, playlist, episode など
            content_id = match.group(2)    # ID部分
            
            # クエリパラメータを除去（?si=xxxなど）
            content_id = content_id.split('?')[0]
            
            # embed URLを生成
            return f"https://open.spotify.com/embed/{content_type}/{content_id}"
        
        # 旧形式の処理（後方互換性のため残す）
        if "open.spotify.com/" in url:
            parts = url.split("open.spotify.com/")[1]
            # intl-xx/ を除去
            parts = re.sub(r'^intl-[a-z]{2}/', '', parts)
            # クエリパラメータを除去
            parts = parts.split('?')[0]
            return f"https://open.spotify.com/embed/{parts}"
            
    except Exception:
        pass
    
    return None

def apple_embed(url: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """
    Apple Music URLからembed URLを生成
    対応フォーマット:
    - https://music.apple.com/jp/album/xxx/123456789
    - https://music.apple.com/jp/album/xxx/123456789?i=987654321
    - https://music.apple.com/us/album/xxx/123456789
    - https://embed.music.apple.com/xxx (既にembed URL)
    """
    if not url:
        return (None, None)
    
    try:
        # 既にembed URLの場合はそのまま返す
        if "embed.music.apple.com" in url:
            return (url, 450)
        
        # 通常のApple Music URLをembed URLに変換
        if "music.apple.com" in url:
            # URLパターンをパース
            # 例: https://music.apple.com/jp/album/name/123456789?i=987654321
            pattern = r'https://music\.apple\.com/([a-z]{2})/([a-z]+)/[^/]+/(\d+)(?:\?i=(\d+))?'
            match = re.match(pattern, url)
            
            if match:
                country = match.group(1)    # jp, us など
                content_type = match.group(2)  # album, playlist など
                album_id = match.group(3)    # アルバムID
                track_id = match.group(4)    # トラックID（オプショナル）
                
                # embed URLを生成
                if track_id:
                    # 特定のトラックの場合
                    embed_url = f"https://embed.music.apple.com/{country}/{content_type}/{album_id}?i={track_id}"
                else:
                    # アルバム全体の場合
                    embed_url = f"https://embed.music.apple.com/{country}/{content_type}/{album_id}"
                
                return (embed_url, 450)
            
            # パターンにマッチしない場合でも、music.apple.comが含まれていれば変換を試みる
            # 単純な置換で対応
            embed_url = url.replace("music.apple.com", "embed.music.apple.com")
            return (embed_url, 450)
            
    except Exception:
        pass
    
    return (None, None)

# ---- Thumbnails ----
def resolve_thumbnail_for_post(post) -> str:
    for key in ("thumbnail_url", "image_url", "thumb_url", "cover_url"):
        v = getattr(post, key, None)
        if v:
            return v
    yt = _extract_youtube_id(getattr(post, "url_youtube", None))
    if yt:
        return f"https://img.youtube.com/vi/{yt}/hqdefault.jpg"
    return "/static/ogp.png"

def thumb_of(post) -> str:
    return resolve_thumbnail_for_post(post)

import random
import string

def generate_slug(length: int = 10) -> str:
    """ランダムなslugを生成（大文字・小文字・数字）"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))
