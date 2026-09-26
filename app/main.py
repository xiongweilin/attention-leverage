from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import ROOT, Settings
from .models import FeedbackRequest, RunRequest, RunResult, SavedGoal
from .pipeline import AttentionPipeline
from .store import Store

settings = Settings.load()
store = Store(settings.database_path)
templates = Jinja2Templates(directory=str(ROOT / 'app' / 'templates'))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds, follow_redirects=True,
        headers={'User-Agent': 'attention-leverage/0.3 (+https://github.com/xiongweilin/attention-leverage)'},
    ) as client:
        app.state.pipeline = AttentionPipeline(client, settings, store)
        yield


app = FastAPI(title='Attention Leverage', version='0.3.0', lifespan=lifespan)


@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


@app.get('/api/health')
async def health(request: Request):
    p: AttentionPipeline = request.app.state.pipeline
    return {'ok': True, 'sources': len(p.sources), 'llm_configured': p.llm.available,
            'database': settings.database_path}


@app.get('/api/sources')
async def sources(request: Request):
    p: AttentionPipeline = request.app.state.pipeline
    health_map = {x['source']: x for x in store.health()}
    return {'sources': [profile.model_dump() | {'health': health_map.get(name)} for name, profile in p.profiles.items()]}


@app.post('/api/run', response_model=RunResult)
async def run(request: Request, body: RunRequest):
    p: AttentionPipeline = request.app.state.pipeline
    return await p.run(body)


@app.get('/api/history')
async def history(limit: int = 20):
    return {'runs': store.recent_runs(max(1, min(limit, 100)))}


@app.get('/api/history/{run_id}')
async def history_run(run_id: str):
    data = store.get_run(run_id)
    if not data:
        raise HTTPException(404, 'run not found')
    return data


@app.post('/api/feedback')
async def feedback(body: FeedbackRequest):
    store.add_feedback(body)
    return {'ok': True}


@app.get('/api/goals')
async def goals():
    return {'goals': [g.model_dump() for g in store.list_goals()]}


@app.post('/api/goals')
async def save_goal(goal: SavedGoal):
    store.save_goal(goal)
    return {'ok': True}


@app.delete('/api/goals/{name}')
async def delete_goal(name: str):
    store.delete_goal(name)
    return {'ok': True}
