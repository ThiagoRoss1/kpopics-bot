import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from scripts.init_db import init_db
from api.routes.photos import router as photos_router
from api.routes.idols import router as idols_router
from bot import run_bots
from scrapers.kpopping import poll_all_idols

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _int_env(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)

def build_scheduler():
    # In-process replacement for the old Railway cron. Two independent gates:
    #   ENABLE_SCHEDULER -> the bot-post job (posts approved photos). On in prod.
    #   ENABLE_SCRAPER   -> the scraper-poll job. Off by default: server-side scraping is retired in
    #                       favour of the local ingestion script (Railway egress reduction), but
    #                       flipping ENABLE_SCRAPER=true re-enables it with no code change.
    # Both default off so running the app locally never fires real posts/scrapes by accident.
    # A BackgroundScheduler runs jobs in their own thread so the blocking requests/tweepy calls
    # don't stall the FastAPI event loop.
    scheduler = BackgroundScheduler()

    if os.getenv("ENABLE_SCHEDULER", "false").lower() in ("1", "true", "yes"):
        scheduler.add_job(run_bots, "interval", hours=_int_env("POST_INTERVAL_HOURS", 6),
                          id="bot_post", replace_existing=True)

    if os.getenv("ENABLE_SCRAPER", "false").lower() in ("1", "true", "yes"):
        scheduler.add_job(poll_all_idols, "interval", hours=_int_env("SCRAPE_INTERVAL_HOURS", 6),
                          id="scraper_poll", replace_existing=True)

    return scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Ensure the schema is migrated, then start the in-process scheduler (bot + scraper jobs).
    init_db()
    scheduler = build_scheduler()
    scheduler.start()
    for job in scheduler.get_jobs():
        print(f"Scheduler job {job.id} next run at {job.next_run_time}")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app = FastAPI(title="Kpopics API", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def index():
    # The approval webapp (single self-contained page; it calls the /photos endpoints).
    return FileResponse(STATIC_DIR / "index.html")

app.include_router(photos_router)
app.include_router(idols_router)
