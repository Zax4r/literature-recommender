"""Локальное распознавание речи через faster-whisper (CPU)."""

import asyncio
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger("whisper")

_model = None
_model_lock = asyncio.Lock()


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
        logger.info(
            "Whisper загружен: %s (device=%s, compute=%s)",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
            settings.WHISPER_COMPUTE_TYPE,
        )
    return _model


async def transcribe(path: str | Path) -> str:
    """Транскрибирует аудиофайл в текст. Тяжёлая работа — в потоке."""
    path = Path(path)

    def _run() -> str:
        segments, _info = _get_model().transcribe(str(path))
        return " ".join(seg.text.strip() for seg in segments).strip()

    return await asyncio.to_thread(_run)
