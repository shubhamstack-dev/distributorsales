"""The app, and the one gate in front of it."""
from __future__ import annotations

import os
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import config, models as M, models_master  # noqa: F401 — registers the tables
from .database import Base, SessionLocal, engine
from .routers import api, master_upload, masters
from .services import migrate, seed
from .services.auth import read_token

app = FastAPI(title="Distributor sales", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Reachable with nobody signed in. Everything else needs a token, decided here
# rather than route by route — a route added later is closed by default.
PUBLIC = [("GET", r"/api/health"), ("POST", r"/api/login")]
_PUBLIC = [(m, re.compile(p + r"/?$")) for m, p in PUBLIC]


@app.middleware("http")
async def gate(request: Request, call_next):
    path, method = request.url.path, request.method
    if not path.startswith("/api/") or method == "OPTIONS" \
            or any(m == method and rx.match(path) for m, rx in _PUBLIC):
        return await call_next(request)
    auth = request.headers.get("authorization") or ""
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    if not read_token(token):
        return JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(api.router)
app.include_router(master_upload.router)      # before masters: /masters/upload is not a master
app.include_router(masters.router)

Base.metadata.create_all(engine)
try:
    for added in migrate.ensure_columns(engine):
        print(f"[startup] {added}", flush=True)
except Exception as e:
    print(f"[startup] could not bring the tables up to date: {e}", flush=True)
os.makedirs(config.STAGING_DIR, exist_ok=True)

try:
    _db = SessionLocal()
    try:
        seed.ensure(_db)
        for done in seed.update_rules(_db):
            print(f"[startup] {done}", flush=True)
        seed.ensure_masters(_db)
        for done in seed.ensure_master_ids(_db):
            print(f"[startup] {done}", flush=True)
    finally:
        _db.close()
except Exception as e:                       # never stop the API booting over seeding
    print(f"[startup] could not seed distributors: {e}", flush=True)
