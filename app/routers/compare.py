# app/routers/compare.py
from fastapi import APIRouter
from app.schemas_compare import CompareRequest, CompareResponse, ItemResult, now_iso

def simple_summary(items: list[ItemResult], hl: dict | None) -> str:
    if not items:
        return "比較対象がありません。"
    msgs = []
    lp = (hl or {}).get("lowest_price_index")
    hr = (hl or {}).get("highest_rating_index")
    if isinstance(lp, int) and 0 <= lp < len(items):
        x = items[lp]
        price = f"{x.price:g} {x.currency}" if (x.price is not None and x.currency) else (
                 f"{x.price:g}" if x.price is not None else "価格不明")
        msgs.append(f"最安は「{x.title or '商品'}」で {price}。")
    if isinstance(hr, int) and 0 <= hr < len(items):
        y = items[hr]
        rating = f"{y.rating:.1f}★" if y.rating is not None else "評価不明"
        msgs.append(f"評価が最も高いのは「{y.title or '商品'}」で {rating}。")
    if not msgs:
        return "価格や評価の情報が不足しています。手動入力を増やすと比較精度が上がります。"
    return " ".join(msgs)

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

        lowest_price = None
        lowest_idx = None
        highest_rating = None
        highest_idx = None

        for i, r in enumerate(out):
            if r.price is not None and (lowest_price is None or r.price < lowest_price):
                lowest_price, lowest_idx = r.price, i
            if r.rating is not None and (highest_rating is None or r.rating > highest_rating):
                highest_rating, highest_idx = r.rating, i

        highlights = {
            "lowest_price_index": lowest_idx,       # 例: 0, 1 …
            "highest_rating_index": highest_idx     # 例: 0, 1 …
        }
        summary = simple_summary(out, highlights)

    return CompareResponse(
        marketplace=req.options.marketplace,
        generated_at=now_iso(),
        items=out,
        highlights=highlights,
        summary=summary
    )