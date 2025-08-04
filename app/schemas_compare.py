from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone

class ItemInput(BaseModel):
    asin: Optional[str] = None
    url: Optional[HttpUrl] = None
    manual: Optional[dict] = None  # {"title":"A","price":1980,"currency":"JPY","rating":4.2,"reviews":120}

class CompareOptions(BaseModel):
    marketplace: Literal["JP","US","UK","DE","FR","IT","ES","CA","AU","IN"] = "JP"

class CompareRequest(BaseModel):
    items: List[ItemInput] = Field(..., min_items=2, max_items=5)
    options: CompareOptions = CompareOptions()

class ItemResult(BaseModel):
    asin: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    source: Literal["manual","unknown"] = "unknown"
    error: Optional[str] = None

class CompareResponse(BaseModel):
    marketplace: str
    generated_at: str
    items: List[ItemResult]
    highlights: dict | None = None
    summary: str | None = None

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()