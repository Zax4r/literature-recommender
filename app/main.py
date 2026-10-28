"""FastAPI-приложение.

Ваша зона: чат (app/api/chat.py + агенты). Остальные роутеры
(auth, профиль, списки, голосования) добавит владелец бэкенда —
подключайте их здесь же через app.include_router(...).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router

app = FastAPI(
    title="Literature Recommender — Chat API",
    description="Агенты рекомендаций: гибридный поиск, whisper, поиск по магазинам.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/")
async def root():
    return {"service": "literature-recommender", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health():
    return {"status": "ok"}
