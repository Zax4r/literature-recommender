from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.router import api_router
from app.api.routes import health


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Прогрев модели эмбеддингов при старте, чтобы первый запрос чата
    # не загружал её «на горячую» внутри пользовательского запроса.
    try:
        from app.services.search import qdrant_search

        await qdrant_search.embed_query("старт")
    except Exception:  # noqa: BLE001
        pass
    yield


app = FastAPI(title="Literature Recommender", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(api_router)
app.include_router(chat_router)

# Mounted last so it only serves paths no API route matched.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
