"""Агент-экстрактор: из текста пользователя достаёт жанры/тропы/исключения."""

import logging

from config import settings
from app.services.ai import PROJECT_ROOT
from app.services.ai.clients.llm import chat_completion
from app.services.ai.guard import clean_string_list, parse_json_llm, wrap_untrusted

logger = logging.getLogger("extractor")

EXTRACTOR_PROMPT = (PROJECT_ROOT / "prompts" / "extractor_prompt.txt").read_text(encoding="utf-8")


async def extract_metadata(
    user_text: str | None,
    untrusted_text: str | None = None,
) -> dict:
    """Возвращает {"genres": [...], "tropes": [...], "exclude": [...]}.

    user_text — сообщение пользователя; untrusted_text — содержимое файла/аудио
    (оборачивается как недоверенные данные).
    """
    parts: list[str] = []
    if user_text:
        parts.append(f"Сообщение пользователя:\n{user_text}")
    if untrusted_text:
        parts.append("\n\n" + wrap_untrusted(untrusted_text, "вложение (файл/аудио)"))
    content = "\n\n".join(parts) or "(пустой запрос)"

    try:
        raw = await chat_completion(
            settings.EXTRACTOR_MODEL, EXTRACTOR_PROMPT, content, json_mode=True, temperature=0.1
        )
        parsed = parse_json_llm(raw) or {}
    except Exception as exc:
        logger.warning("Extractor call failed: %s", exc)
        parsed = {}

    return {
        "genres": clean_string_list(parsed.get("genres")),
        "tropes": clean_string_list(parsed.get("tropes")),
        "exclude": clean_string_list(parsed.get("exclude"), max_items=8, max_chars=80),
    }
