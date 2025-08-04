# app/routers/compare.py
from fastapi import APIRouter
from app.schemas_compare import CompareRequest, CompareResponse, ItemResult, now_iso

router = APIRouter(prefix="/api", tags=["compare"])

@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest):
    out = []
    for it in req.items:
        # まだPA-APIを使わないので manual だけ受け取って返す
        if it.manual:
            price = None
            try:
                if "price" in it.manual:
                    price = float(it.manual["price"])
            except Exception:
                pass
            out.append(ItemResult(
                asin=it.asin,
                url=str(it.url) if it.url else None,
                title=it.manual.get("title"),
                price=price,
                currency=it.manual.get("currency","JPY"),
                rating=it.manual.get("rating"),
                reviews=it.manual.get("reviews"),
                source="manual",
            ))
        else:
            out.append(ItemResult(
                asin=it.asin,
                url=str(it.url) if it.url else None,
                error="manual_required",
                source="unknown",
            ))
    return CompareResponse(
        marketplace=req.options.marketplace,
        generated_at=now_iso(),
        items=out
    )