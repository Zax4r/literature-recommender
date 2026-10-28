"""Обёртки над OpenRouter (chat completions)."""

import asyncio
import logging

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger("llm")

llm_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
    timeout=settings.LLM_TIMEOUT_SECONDS,
)

DEFAULT_CHAT_MODEL = settings.EXTRACTOR_MODEL

# Коды, после которых имеет смысл повторить запрос (см. exception.status_code).
# Зависания/таймауты НЕ ретраим — иначе один сбой съедает все 60+ секунд.
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


async def chat_completion(
    model: str,
    system_prompt: str,
    user_content: str,
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    max_retries: int | None = None,
) -> str:
    """Один вызов chat/completions с ограниченными ретраями (по умолчанию 2)."""
    if max_retries is None:
        max_retries = settings.LLM_MAX_RETRIES
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "extra_body": {"provider": {"allow_fallbacks": True}},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await llm_client.chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            code = getattr(exc, "status_code", None)
            retryable = code in _RETRYABLE_CODES
            if attempt < max_retries - 1 and retryable:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc
