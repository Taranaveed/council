from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.auth import router as auth_router
from app.api.briefs import router as briefs_router
from app.api.debate import router as debate_router
from app.api.focus_group import router as focus_group_router
from app.api.geo import router as geo_router
from app.api.marketplaces import router as marketplaces_router
from app.api.modes import router as modes_router
from app.api.watchlist import router as workspace_router
from app.core.alerts_service import alerts_background_loop
from app.db.briefs import init_briefs_db
from app.db.marketplaces import init_marketplaces_db
from app.db.notifications import init_notifications_db
from app.db.users import init_db
from app.db.watchlist import init_watchlist_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    init_marketplaces_db()
    init_briefs_db()
    init_watchlist_db()
    init_notifications_db()
    task = asyncio.create_task(alerts_background_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Synthetic Focus Group",
    description="AI-powered market validation for e-commerce merchants",
    version="2.0.0",
    lifespan=lifespan,
)

_default_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:3000",
    "https://project-nsy5u.vercel.app",
]
_extra = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "").split(",")
    if o.strip()
]
_frontend = (os.getenv("FRONTEND_ORIGIN") or "").strip()
if _frontend:
    _extra.append(_frontend)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_default_origins, *_extra],
    # Local Vite: localhost, 127.0.0.1, and private LAN IPs (phone/tablet on same Wi‑Fi).
    allow_origin_regex=(
        r"http://("
        r"localhost|127\.0\.0\.1|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r"):\d+"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(geo_router)
app.include_router(modes_router)
app.include_router(briefs_router)
app.include_router(workspace_router)
app.include_router(marketplaces_router)
app.include_router(debate_router)
app.include_router(focus_group_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/market/ping")
async def market_ping():
    """Wake / check the market-service (used by the frontend before searches)."""
    from app.core.market_client import wake_market_service

    market = (os.getenv("MARKET_SERVICE_URL") or "").rstrip("/") or "unset"
    ok = await wake_market_service(60.0)
    return {"status": "ok" if ok else "waking", "market": market}
