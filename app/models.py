"""SQLAlchemy models.

※ フィールド変更時は Alembic 等のマイグレーションを導入してください。
今回のローカル用は create_all で自動作成します。
"""
from __future__ import annotations
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Text, Boolean, ForeignKey, DateTime
from datetime import datetime
from .db import Base
import re, unicodedata
from typing import Optional, List

def slugify(s: str) -> str:
    """雑なスラッグ生成（日本語もOKだが簡易）。"""
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = re.sub(r"[^a-z0-9一-龥ぁ-んァ-ヶー\s-]", "", s)
    s = re.sub(r"[\sー-]+", "-", s)
    return s[:50] or "artist"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    artists: Mapped[list[Artist]] = relationship("Artist", back_populates="owner", cascade="all,delete", passive_deletes=True)

class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    # ここを Optional[...] に統一（nullable=True も付けるとスキーマ意図が明確）
    twitter: Mapped[Optional[str]]   = mapped_column(String(255), nullable=True, default=None)
    instagram: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    spotify: Mapped[Optional[str]]   = mapped_column(String(255), nullable=True, default=None)

    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner: Mapped[Optional["User"]] = relationship("User", back_populates="artists")

    posts: Mapped[List["Post"]] = relationship(
        "Post", back_populates="artist", cascade="all,delete", passive_deletes=True
    )

class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), index=True)  # 曲名
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    url_youtube: Mapped[Optional[str]] = mapped_column(Text, default=None)
    url_spotify: Mapped[Optional[str]] = mapped_column(Text, default=None)
    url_apple: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    artist: Mapped[Artist] = relationship("Artist", back_populates="posts")
    likes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")