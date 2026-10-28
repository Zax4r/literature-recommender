"""Web-поиск через OpenRouter (Responses API + web-плагин и фолбэки).

Основной путь — POST /api/v1/responses с plugins: [{"id": "web"}], который
работает для любой модели на OpenRouter. Фолбэк — chat completions с моделью
с суффиксом :online.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("web_search")


async def search(query: str, max_results: int = 5) -> str:
    """Выполняет web-поиск и возвращает текст результата (с найденными ссылками)."""
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")
    url = "https://openrouter.ai/api/v1/responses"
    payload = {
        "model": settings.SHOP_SEARCH_WEB_MODEL,
        "input": query,
        "plugins": [{"id": "web", "max_results": max_results}],
        "max_output_tokens": 3000,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    text = _extract_text(data)
    if not text:
        raise RuntimeError(
            f"Web-поиск вернул пустой результат (model={settings.SHOP_SEARCH_WEB_MODEL!r})"
        )
    return text


async def search_via_online_model(query: str) -> str:
    """Фолбэк: chat-completions с моделью, поддерживающей суффикс :online."""
    from app.services.ai.clients.llm import chat_completion

    return await chat_completion(settings.SHOP_SEARCH_ONLINE_MODEL, "", query, temperature=0.2)


def _extract_text(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    result = data.get("result")
    if isinstance(result, str):
        return result
    out = data.get("output")
    if isinstance(out, list):
        for item in out:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") in ("output_text", "text", "message"):
                        txt = block.get("text")
                        if txt:
                            return txt
    return ""
