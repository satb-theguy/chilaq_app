# app/routers/auth.py
from fastapi import APIRouter, Response, Cookie, Depends, HTTPException

router = APIRouter(tags=["auth"])

DEMO_TOKEN = "demo-token-123"

@router.post("/login")
def login(resp: Response):
    resp.set_cookie(
        key="session", value=DEMO_TOKEN,
        httponly=True, secure=True, samesite="None", path="/",
        max_age=60*60*24,
    )
    return {"ok": True}

def require_session(session: str | None = Cookie(default=None)):
    if session != DEMO_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

@router.get("/me")
def me(_=Depends(require_session)):
    return {"user": "demo"}

@router.post("/logout")
def logout(resp: Response):
    resp.delete_cookie(key="session", path="/", samesite="None", secure=True)
    return {"ok": True}