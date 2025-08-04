from fastapi import FastAPI

app = FastAPI(title="chilaq API")

@app.get("/")
def root():
    return {"ok": True, "message": "ここにいろいろ載せたいなぁ Hello from Chilaq!"}

@app.get("/health")
def health():
    return {"status": "healthy"}