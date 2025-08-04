from fastapi import FastAPI

app = FastAPI(title="chilaq API")

@app.get("/")
def root():
    return {"ok": True, "message": "Hello from chilaq.jp! v2"}  # ← v2 と追記

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/version")
def version():
    return {"app": "chilaq", "version": "0.1.1"}  # ← バージョンを 0.1.1 に