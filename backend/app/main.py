from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()

from app.api.auth import router as auth_router
from app.api.debate import router as debate_router
from app.api.focus_group import router as focus_group_router
from app.api.geo import router as geo_router
from app.api.marketplaces import router as marketplaces_router
from app.api.modes import router as modes_router
from app.db.users import init_db
from app.db.marketplaces import init_marketplaces_db

app = FastAPI(
    title="Synthetic Focus Group",
    description="AI-powered market validation for e-commerce merchants",
    version="2.0.0",
)

_default_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
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
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(geo_router)
app.include_router(modes_router)
app.include_router(marketplaces_router)
app.include_router(debate_router)
app.include_router(focus_group_router)


@app.on_event("startup")
def on_startup():
    init_db()
    init_marketplaces_db()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
