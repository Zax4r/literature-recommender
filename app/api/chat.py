"""Эндпоинты чата: POST /api/v1/chat (мультипарт) + отладка whisper."""

import json
import logging

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.services.ai import orchestrator
from app.services.files import uploader

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
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
):
    text, untrusted, source = await uploader.process_chat_input(message=message, file=file)
    result = await orchestrator.run_chat(
        user_text=text,
        untrusted_text=untrusted,
        source=source,
        user_id=x_user_id,
        history=_parse_history(history),
    )
    return result


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
