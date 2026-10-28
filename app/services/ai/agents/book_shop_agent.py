"""Агент поиска по магазинам (Беларусь).

Получает ТОЛЬКО названия/авторов книг (никакого сырого текста пользователя),
ищет в интернете, где книгу можно купить/найти (бумажную и электронную),
фильтрует ссылки по белому списку доменов и возвращает карточки со ссылками.
При недоступности web-поиска — стабильные ссылки-шаблоны на страницы поиска.
"""

import asyncio
import logging
from urllib.parse import quote, urlsplit

from app.core.config import settings, BOOK_SHOP_SEARCH_TEMPLATES
from app.services.ai import PROJECT_ROOT
from app.services.ai.clients.llm import chat_completion
from app.services.ai.guard import parse_json_llm, wrap_untrusted
from app.services.ai.tools import web_search

logger = logging.getLogger("shop_agent")

SHOP_PROMPT_TEMPLATE = (PROJECT_ROOT / "prompts" / "book_shop_agent_prompt.txt").read_text(
    encoding="utf-8"
)


def _safe_urlsplit(url: str):
    """urlsplit, возвращающий None на заведомо битых URL."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    return parsed


def _template_stores(book: dict) -> list[dict]:
    q = quote(f"{book.get('title', '')} {book.get('author', '')}".strip())
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
        seen_hosts: set[str] = set()
        for store in item.get("stores", []) or []:
            if not isinstance(store, dict):
                continue
            url = str(store.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            parsed = _safe_urlsplit(url)
            if parsed is None:
                continue
            host = parsed.netloc.lower().removeprefix("www.")
            if not any(dom in host for dom in whitelist):
                continue
            # Голый домен или главная страница — не ссылка на книгу; у шаблонов
            # путь поиска всегда есть.
            if parsed.path in ("", "/"):
                continue
            # Дублирующиеся магазины (например, два oz.by) — не нужны.
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            stores.append(
                {
                    "name": str(store.get("name", "")).strip()
                    or host.split(".")[0].capitalize(),
                    "url": url,
                    "kind": "ebook" if str(store.get("kind", "")) == "ebook" else "paper",
                }
            )
        if stores:
            result[title] = stores[:3]
    return result


async def find_stores(books: list[dict]) -> list[dict]:
    """Возвращает books со ссылками магазинов:
    [{"title", "author", "stores": [{"name", "url", "kind"}]}].

    Web-поиск дорогой и медленный, поэтому ограничиваем количество книг
    (SHOP_MAX_BOOKS) и жёсткий таймаут этапа (SHOP_TIMEOUT_SECONDS).
    """
    if not books:
        return []
    if not settings.SHOP_SEARCH_ENABLED:
        return [{**b, "stores": _template_stores(b)} for b in books]

    # Web-поиск дорогой и медленный: занимаемся им только для первых
    # SHOP_MAX_BOOKS книг, остальным сразу даём шаблонные ссылки.
    web_books = books[: settings.SHOP_MAX_BOOKS]
    queries = [
        f"{b.get('title', '')} {b.get('author', '')} купить Беларусь книжный магазин".strip()
        for b in web_books
    ]

    search_results: list[str] = []
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    web_search.search(q, max_results=settings.SHOP_SEARCH_MAX_RESULTS)
                    for q in queries
                ),
                return_exceptions=True,
            ),
            timeout=settings.SHOP_TIMEOUT_SECONDS,
        )
        search_results = [r if isinstance(r, str) else "" for r in results]
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        logger.warning("Пакетный web-поиск не удался: %s", exc)

    joined = "\n\n".join(
        f"--- Книга: «{b.get('title', '')}»\n{t}"
        for b, t in zip(web_books, search_results)
        if t
    )

    if not joined:
        # Фолбэк: модель с :online ищет сама.
        try:
            lines = "\n".join(
                f"- {b.get('title', '')} — {b.get('author', '')}" for b in web_books
            )
            joined = await asyncio.wait_for(
                web_search.search_via_online_model(
                    "Найди в интернете, где в Беларуси купить каждую из этих книг онлайн "
                    "(бумажная и электронная). Верни ссылки на магазины.\n" + lines
                ),
                timeout=settings.SHOP_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
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
            raw = await asyncio.wait_for(
                chat_completion(
                    settings.EXTRACTOR_MODEL,
                    shop_prompt,
                    content,
                    json_mode=True,
                    temperature=0.1,
                ),
                timeout=settings.SHOP_TIMEOUT_SECONDS,
            )
            by_title = _apply_whitelist(parse_json_llm(raw))
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            logger.warning("Извлечение ссылок из результатов не удалось: %s", exc)

    out = []
    for b in books:
        title_key = str(b.get("title", "")).strip().lower()
        stores = by_title.get(title_key) if b in web_books else None
        out.append({**b, "stores": stores if stores else _template_stores(b)})
    return out
