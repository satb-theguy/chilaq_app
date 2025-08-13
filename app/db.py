"""Database setup (SQLite for local dev).

- Render(Postgres) への移行時は DATABASE_URL を使うように差し替えてください。
- ローカルでは ./chilaq.db に保存されます。
"""
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# 環境変数があれば使う（将来の Render 移行用）
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Render(Postgres) を想定。URL 文字列を SQLAlchemy 形式に補正
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    # ローカル SQLite（ファイル）
    engine = create_engine("sqlite:///./chilaq.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

def get_db():
    """FastAPI の依存関数。with で自動 close します。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
