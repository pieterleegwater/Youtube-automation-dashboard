import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import pipeline
from .dashboard import dashboard_context
from .config import settings
from .db import connect, init_db, insert_strategy, log
from .scheduler import JOB_NAMES, create_scheduler

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
scheduler = create_scheduler()

ACTIONS = {
    "generate": lambda: pipeline.generate_today(force=True),
    "upload": pipeline.upload_today,
    "stats": pipeline.sync_stats,
    "evolve": pipeline.evolve_strategies,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not settings.disable_scheduler:
        scheduler.start()
        log("Planner gestart")
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="ASMR Shorts Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def dashboard(request: Request):
    context = dashboard_context()
    if scheduler.running:
        for job in scheduler.get_jobs():
            context["jobs"].append({"name": JOB_NAMES.get(job.id, job.id), "next": job.next_run_time})
    return templates.TemplateResponse(request, "index.html", context)


@app.post("/actions/{name}")
def run_action(name: str):
    action = ACTIONS.get(name)
    if action is None:
        raise HTTPException(404)
    log(f"Handmatig gestart: {JOB_NAMES[name]}")
    threading.Thread(target=action, daemon=True).start()
    return RedirectResponse("/", status_code=303)


@app.post("/strategies")
def add_strategy(
    name: str = Form(...),
    theme: str = Form(...),
    prompt_template: str = Form(...),
    title_style: str = Form(""),
    hashtags: str = Form(""),
):
    with connect() as conn:
        insert_strategy(conn, name=name, theme=theme, prompt_template=prompt_template, title_style=title_style, hashtags=hashtags)
    log(f"Strategie '{name}' handmatig toegevoegd")
    return RedirectResponse("/#strategieen", status_code=303)


@app.post("/strategies/{strategy_id}/toggle")
def toggle_strategy(strategy_id: int):
    with connect() as conn:
        conn.execute("UPDATE strategies SET active = 1 - active WHERE id = ?", (strategy_id,))
    return RedirectResponse("/#strategieen", status_code=303)


@app.get("/media/{video_id}")
def media(video_id: int):
    with connect() as conn:
        row = conn.execute("SELECT file_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row or not row["file_path"] or not Path(row["file_path"]).exists():
        raise HTTPException(404)
    return FileResponse(row["file_path"], media_type="video/mp4")
