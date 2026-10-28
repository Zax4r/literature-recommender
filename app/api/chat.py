"""Эндпоинты чата: POST /api/v1/chat (мультипарт) + отладка whisper."""

import json
import logging

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import OptionalUser
from app.db.session import SessionLocal
from app.services.ai import orchestrator
from app.services.files import uploader
from app.services.history import save_recommendation, source_idx_to_book_id

logger = logging.getLogger("chat_api")

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("")
async def chat_endpoint(
    message: str | None = Form(default=None, description="Текстовое сообщение (опционально)"),
    file: UploadFile | None = File(
        default=None, description="Файл: аудио (распознается), txt/pdf/docx/md"
    ),
    history: str | None = Form(
        default=None, description="Предыдущие сообщения списком JSON для контекста"
    ),
    user: OptionalUser = None,
):
    """Анонимам чат отвечает без исключения прочитанного и без истории; с токеном — с ними."""
    text, untrusted, source = await uploader.process_chat_input(message=message, file=file)
    result = await orchestrator.run_chat(
        user_text=text,
        untrusted_text=untrusted,
        source=source,
        user_id=str(user.id) if user else None,
        history=_parse_history(history),
    )
    if result.get("recommendations"):
        query = text or untrusted or ""
        await run_in_threadpool(
            _attach_catalog_ids, result, user.id if user else None, query, source
        )
    return result


def _attach_catalog_ids(result: dict, user_id: int | None, query: str, source: str) -> None:
    """Adds `book_id` (catalog id) to each card and saves the answer in the user's history."""
    cards = result["recommendations"]
    with SessionLocal() as db:
        ids = source_idx_to_book_id(
            db, [c["source_idx"] for c in cards if c.get("source_idx") is not None]
        )
        for card in cards:
            card["book_id"] = ids.get(card.get("source_idx"))
        if user_id is not None:
            saved = save_recommendation(
                db, user_id, query[:2000], source[:16], result.get("answer", ""), cards
            )
            result["recommendation_id"] = saved.id


@router.post("/transcribe", summary="Отладка: только распознавание речи")
async def transcribe_endpoint(file: UploadFile = File(...)):
    text = await uploader.transcribe_audio(file)
    return {"text": text}


@router.get("/health")
async def chat_health():
    return {"status": "ok"}


def _parse_history(raw: str | None) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict)][-20:]
