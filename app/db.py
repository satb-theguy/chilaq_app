# app/db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

def make_engine_from_env() -> "Engine|None":
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    return create_engine(db_url, pool_pre_ping=True)

engine = make_engine_from_env()

def get_session():
    if engine is None:
        raise RuntimeError("database_not_configured")
    with Session(engine) as s:
        yield s