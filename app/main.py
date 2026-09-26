from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import ROOT, Settings
from .models import RunRequest, RunResult
from .pipeline import AttentionPipeline

settings = Settings.load()
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "attention-leverage/0.1"},
    ) as client:
        app.state.pipeline = AttentionPipeline(client, settings)
        yield


app = FastAPI(title="Attention Leverage", version="0.1.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health(request: Request):
    pipeline: AttentionPipeline = request.app.state.pipeline
    return {
        "ok": True,
        "sources": list(pipeline.sources),
        "llm_configured": pipeline.llm.available,
    }


@app.get("/api/sources")
async def sources(request: Request):
    pipeline: AttentionPipeline = request.app.state.pipeline
    return {"sources": list(pipeline.sources)}


@app.post("/api/run", response_model=RunResult)
async def run(request: Request, body: RunRequest):
    pipeline: AttentionPipeline = request.app.state.pipeline
    return await pipeline.run(body)
