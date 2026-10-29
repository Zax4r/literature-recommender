"""Агент-форматтер: превращает карточки рекомендаций в краткий текстовый ответ."""

import json
import logging
import re

from app.core.config import settings
from app.services.ai import PROJECT_ROOT
from app.services.ai.clients.llm import chat_completion
from app.services.ai.guard import parse_json_llm, wrap_untrusted

logger = logging.getLogger("formatter")

FORMATTER_PROMPT = (PROJECT_ROOT / "prompts" / "formatter_prompt.txt").read_text(encoding="utf-8")


def _cards_payload(cards: list[dict], stores_by_title: dict) -> list[dict]:
    return [
        {
            "title": c.get("title", ""),
            "author": c.get("author", ""),
            "genres": c.get("genres", []),
            "tropes": c.get("tropes", []),
            "description": (c.get("description") or "")[:600],
            "stores": stores_by_title.get(str(c.get("title", "")).strip().lower(), []),
        }
        for c in cards
    ]


def _default_answer(cards: list[dict]) -> str:
    titles = ", ".join(f"«{c.get('title', '')}»" for c in cards)
    return f"По вашему запросу нашёл такие книги: {titles}. Подробнее — в карточках ниже."


def _is_echo(answer: str, summary: str) -> bool:
    """True, если ответ LLM — по сути дословный повтор summary (типичный сбой модели:
    вместо объяснения она копирует суть запроса вида «Пользователь ищет книгу…»)."""
    if not answer or not summary:
        return False

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().strip('"\'!?.,;:«» ').lower()

    a, s = norm(answer), norm(summary)
    if not a or not s:
        return False
    if a == s or a in s:
        return True
    return s in a and len(s) / len(a) > 0.6


async def compose_answer(
    cards: list[dict],
    stores_by_title: dict,
    summary: str,
    matched_genres: list[str] | None = None,
    matched_tropes: list[str] | None = None,
    matched_settings: list[str] | None = None,
) -> str:
    """Возвращает связный текстовый ответ. LLM НЕ получает сырой ввод пользователя."""
    if not cards:
        return "К сожалению, по вашему запросу ничего не нашлось. Попробуйте переформулировать."

    payload = {
        "user_summary": (summary or "")[:300],
        "matched_genres": (matched_genres or [])[:8],
        "matched_tropes": (matched_tropes or [])[:8],
        "matched_settings": (matched_settings or [])[:8],
        "books": _cards_payload(cards, stores_by_title),
    }
    content = wrap_untrusted(json.dumps(payload, ensure_ascii=False), "данные рекомендаций")

    try:
        raw = await chat_completion(
            settings.FORMATTER_MODEL, FORMATTER_PROMPT, content, json_mode=True, temperature=0.4
        )
        parsed = parse_json_llm(raw) or {}
        answer = str(parsed.get("answer", "")).strip()
        if answer and not _is_echo(answer, summary):
            return answer
        if answer:
            logger.warning("Formatter вернул эхо запроса; использую запасной ответ")
    except Exception as exc:
        logger.warning("Formatter call failed: %s", exc)
    return _default_answer(cards)
