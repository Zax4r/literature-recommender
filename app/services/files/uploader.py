"""Ввод в чат: текстовое сообщение и/или вложенный файл.

Аудио -> whisper (текст), прочие файлы -> парсер. Результаты считаются
недоверенным контентом и передаются в агенты отдельно от сообщения.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.services.files import parser, whisper
from config import settings

logger = logging.getLogger("uploader")

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".webm", ".mp4"}

TEMP_DIR = Path(__file__).resolve().parents[3] / "storage" / "temp_upload"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

MAX_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024


def _is_audio(file: UploadFile) -> bool:
    suffix = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "").lower()
    return suffix in AUDIO_EXTS or content_type.startswith("audio/")


async def process_chat_input(
    *,
    message: str | None,
    file: UploadFile | None,
) -> tuple[str, str | None, str]:
    """Возвращает (текст_сообщения, недоверенный_текст_вложения | None, источник)."""
    text = (message or "").strip()
    if file is None:
        if not text:
            raise HTTPException(status_code=400, detail="Отправьте текст или файл.")
        return text, None, "chat"

    if file.size and file.size > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Файл слишком большой.")

    if _is_audio(file):
        return text, await transcribe_audio(file), "whisper"

    return text, await extract_text_upload(file), "file"


async def transcribe_audio(file: UploadFile) -> str:
    """Сохраняет аудио во временную папку, транскрибирует и удаляет."""
    suffix = Path(file.filename or "audio.mp3").suffix.lower() or ".mp3"
    path = TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        await _save(file, path)
        return await whisper.transcribe(path)
    finally:
        _unlink(path)


async def extract_text_upload(file: UploadFile) -> str:
    """Сохраняет файл, извлекает текст и удаляет."""
    suffix = Path(file.filename or "file.txt").suffix.lower()
    path = TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        await _save(file, path)
        return parser.extract_text(path, filename=file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        _unlink(path)


async def _save(file: UploadFile, path: Path) -> None:
    total = 0
    with path.open("wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                raise HTTPException(status_code=413, detail="Файл слишком большой.")
            out.write(chunk)
    await file.close()


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
