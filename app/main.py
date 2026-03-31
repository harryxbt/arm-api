import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.config import settings
from app.routes.auth import router as auth_router
from app.routes.videos import router as videos_router
from app.routes.gameplay import router as gameplay_router
from app.routes.jobs import router as jobs_router
from app.routes.clips import router as clips_router
from app.routes.clusters import router as clusters_router
from app.routes.analytics import router as analytics_router
from app.routes.dubbing import router as dubbing_router
from app.routes.clippers import router as clippers_router, assignments_router
from app.routes.clipper_portal import router as clipper_portal_router

app = FastAPI(title="Armageddon API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(videos_router)
app.include_router(gameplay_router)
app.include_router(jobs_router)
app.include_router(clips_router)
app.include_router(clusters_router)
app.include_router(analytics_router)
app.include_router(dubbing_router)
app.include_router(clippers_router)
app.include_router(assignments_router)
app.include_router(clipper_portal_router)

# Serve storage files
storage_path = os.path.abspath(settings.storage_dir)
os.makedirs(storage_path, exist_ok=True)
app.mount("/storage", StaticFiles(directory=storage_path), name="storage")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path) as f:
        return f.read()


@app.get("/clipper", include_in_schema=False)
def clipper_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "clipper.html"))


@app.get("/health")
def health():
    return {"status": "ok"}
