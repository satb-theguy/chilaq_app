from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, ForeignKey, Text, DateTime

class Base(DeclarativeBase):
    pass

# users
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    artists: Mapped[list["Artist"]] = relationship(back_populates="owner")

# artists
class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=True)  # 新規追加
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    owner: Mapped[Optional[User]] = relationship(back_populates="artists")
    posts: Mapped[list["Post"]] = relationship(back_populates="artist")

# posts
class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=True)  # 新規追加
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), nullable=False)
    artist: Mapped[Artist] = relationship(back_populates="posts")

    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    url_youtube: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    url_spotify: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    url_apple: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)