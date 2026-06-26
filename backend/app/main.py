from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

load_dotenv()

from app.api.debate import router as debate_router
from app.api.focus_group import router as focus_group_router

app = FastAPI(
    title="Synthetic Focus Group",
    description="AI-powered market validation for e-commerce merchants",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(debate_router)
app.include_router(focus_group_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
