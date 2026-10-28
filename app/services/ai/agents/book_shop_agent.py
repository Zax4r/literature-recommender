"""Агент поиска по магазинам (Беларусь).

Получает ТОЛЬКО названия/авторов книг (никакого сырого текста пользователя),
ищет в интернете, где книгу можно купить/найти (бумажную и электронную),
фильтрует ссылки по белому списку доменов и возвращает карточки со ссылками.
При недоступности web-поиска — стабильные ссылки-шаблоны на страницы поиска.
"""

import asyncio
import logging
from urllib.parse import quote

from config import settings, BOOK_SHOP_SEARCH_TEMPLATES
from app.services.ai import PROJECT_ROOT
from app.services.ai.clients.llm import chat_completion
from app.services.ai.guard import parse_json_llm, wrap_untrusted
from app.services.ai.tools import web_search

logger = logging.getLogger("shop_agent")

SHOP_PROMPT_TEMPLATE = (PROJECT_ROOT / "prompts" / "book_shop_agent_prompt.txt").read_text(
    encoding="utf-8"
)


def template_stores(book: dict) -> list[dict]:
    """Ссылки на поиск книги по названию в магазинах (автор в запрос не входит: ломает выдачу)."""
    q = quote(str(book.get("title", "")).strip())
    return [
        {"name": name, "url": template.format(q=q), "kind": "paper"}
        for name, template in BOOK_SHOP_SEARCH_TEMPLATES.items()
    ]


def _apply_whitelist(parsed: dict | list | None) -> dict[str, list[dict]]:
    """Разрешает только ссылки с доменами из белого списка.

    Принимает: список книг, объект {"books": [...]} или одиночный объект книги."""
    whitelist = settings.BOOK_SHOP_WHITELIST
    result: dict[str, list[dict]] = {}
    if not parsed:
        return result

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        if isinstance(parsed.get("books"), list):
            items = parsed["books"]
        elif "title" in parsed or "stores" in parsed:
            items = [parsed]
        else:
            items = []
    else:
        return result

    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip().lower()
        if not title:
            continue
        stores: list[dict] = []
        for store in item.get("stores", []) or []:
            if not isinstance(store, dict):
                continue
            url = str(store.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            if not any(dom in url for dom in whitelist):
                continue
            stores.append(
                {
                    "name": str(store.get("name", "")).strip()
                    or url.split("/")[2],
                    "url": url,
                    "kind": "ebook" if str(store.get("kind", "")) == "ebook" else "paper",
                }
            )
        if stores:
            result[title] = stores[:3]
    return result


async def find_stores(books: list[dict]) -> list[dict]:
    """Возвращает books со ссылками магазинов:
    [{"title", "author", "stores": [{"name", "url", "kind"}]}]."""
    if not books:
        return []
    queries = [
        f"{b.get('title', '')} {b.get('author', '')} купить Беларусь книжный магазин".strip()
        for b in books
    ]

    search_results: list[str] = []
    try:
        results = await asyncio.gather(
            *(web_search.search(q, max_results=5) for q in queries),
            return_exceptions=True,
        )
        search_results = [r if isinstance(r, str) else "" for r in results]
    except Exception as exc:
        logger.warning("Пакетный web-поиск не удался: %s", exc)

    joined = "\n\n".join(
        f"--- Книга: «{b.get('title', '')}»\n{t}" for b, t in zip(books, search_results) if t
    )

    if not joined:
        # Фолбэк: модель с :online ищет сама.
        try:
            lines = "\n".join(f"- {b.get('title', '')} — {b.get('author', '')}" for b in books)
            joined = await web_search.search_via_online_model(
                "Найди в интернете, где в Беларуси купить каждую из этих книг онлайн "
                "(бумажная и электронная). Верни ссылки на магазины.\n" + lines
            )
        except Exception as exc:
            logger.warning("Онлайн-фолбэк поиска магазинов не удался: %s", exc)

    by_title: dict[str, list[dict]] = {}
    if joined:
        content = (
            "Ниже результаты web-поиска. Извлеки ссылки на магазины из белого списка.\n\n"
            + wrap_untrusted(joined, "результаты web-поиска")
        )
        shop_prompt = SHOP_PROMPT_TEMPLATE.replace(
            "{whitelist}", ", ".join(settings.BOOK_SHOP_WHITELIST)
        )
        try:
            raw = await chat_completion(
                settings.EXTRACTOR_MODEL,
                shop_prompt,
                content,
                json_mode=True,
                temperature=0.1,
            )
            by_title = _apply_whitelist(parse_json_llm(raw))
        except Exception as exc:
            logger.warning("Извлечение ссылок из результатов не удалось: %s", exc)

    out = []
    for b in books:
        stores = by_title.get(str(b.get("title", "")).strip().lower())
        out.append({**b, "stores": stores if stores else template_stores(b)})
    return out
