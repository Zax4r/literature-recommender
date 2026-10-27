from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.api.routes import health

app = FastAPI(title="Literature Recommender")
app.include_router(health.router)
app.include_router(api_router)

# Mounted last so it only serves paths no API route matched.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
