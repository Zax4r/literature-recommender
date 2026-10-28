"""Оркестратор чата: роутинг + конвейер рекомендаций с деградацией.

Пайплайн: input -> router -> extractor -> hybrid search -> магазины -> форматер.
Все AI-шаги изолированы try/except: сбой одного агента не роняет весь запрос.
"""

import logging

from config import settings
from app.services.ai import context
from app.services.ai.agents import book_shop_agent, extractor, formatter, router_agent
from app.services.search import qdrant_search

logger = logging.getLogger("orchestrator")


def build_search_query(
    summary: str | None,
    genres: list[str],
    tropes: list[str],
) -> str:
    parts = []
    if summary:
        parts.append(summary.strip())
    if genres:
        parts.append("ЖАНРЫ: " + ", ".join(genres))
    if tropes:
        parts.append("ТРОПЫ: " + ", ".join(tropes))
    return " ".join(p for p in parts if p)


def _base(user_text: str, untrusted_text: str | None, source: str) -> dict:
    return {
        "input": {
            "text": (user_text or "")[:2000],
            "has_file": bool(untrusted_text),
            "source": source,
        }
    }


def _simple(intent: str, answer: str, *, question: str | None = None, reason: str = "") -> dict:
    out = {"intent": intent, "answer": answer, "recommendations": [], "question": question}
    if reason:
        out["reason"] = reason
    return out


async def run_chat(
    *,
    user_text: str = "",
    untrusted_text: str | None = None,
    source: str = "chat",
    user_id: str | None = None,
    history: list | None = None,
) -> dict:
    base = _base(user_text, untrusted_text, source)
    full_input = "\n".join(
        p for p in (user_text or "", untrusted_text or "") if p
    )

    decision = await router_agent.route_request(
        full_input or "(пусто)", has_history=bool(history)
    )
    intent = decision["intent"]

    if intent in {"unsafe", "refuse"}:
        answer = (
            "Похоже, запрос пытается обойти ограничения помощника, поэтому я не стану "
            "его выполнять. Я умею только подбирать книги: опишите жанр, настроение "
            "или книгу, похожую на которую вы ищете."
            if intent == "unsafe"
            else "Я — помощник по подбору литературы и отвечаю только на книжные "
            "запросы. Расскажите, что бы вам хотелось почитать."
        )
        base.update(_simple(intent, answer, reason=decision.get("reason", "")))
        return base

    if intent == "clarify":
        question = (
            decision.get("user_summary")
            or "Уточните, пожалуйста, что вы ищете: жанр, настроение, "
            "или книга, на которую вы хотите что-то похожее?"
        )
        base.update(_simple(intent, question, question=question))
        return base

    if intent == "follow_up":
        base.update(
            _simple(
                intent,
                "Могу продолжить подбор. Опишите направление — жанр, автор, "
                "настроение — и я поищу похожие книги.",
            )
        )
        return base

    # --- recommend ---
    meta = await extractor.extract_metadata(user_text, untrusted_text)
    summary = decision.get("user_summary") or user_text or untrusted_text or ""
    query_text = build_search_query(summary, meta["genres"], meta["tropes"]).strip()

    if not query_text:
        base.update(
            _simple(
                "clarify",
                "Опишите, пожалуйста, что вы хотите почитать: жанр, настроение, "
                "или книгу, похожую на которую вы ищете.",
            )
        )
        return base

    exclude_ids: set[int] = set()
    if user_id:
        try:
            exclude_ids = await context.get_filtered_book_ids(user_id)
        except Exception as exc:
            logger.warning("get_filtered_book_ids(%s) failed: %s", user_id, exc)

    try:
        cards = await qdrant_search.hybrid_search(
            query_text,
            exclude_tropes=meta["exclude"],
            exclude_ids=sorted(exclude_ids),
            top_k=settings.SEARCH_TOP_K,
            prefetch_k=settings.SEARCH_PREFETCH_K,
        )
    except Exception as exc:
        logger.warning("hybrid_search fallback to dense: %s", exc)
        cards = await qdrant_search.dense_fallback(query_text, top_k=settings.SEARCH_TOP_K)

    cards = cards[: settings.SEARCH_TOP_K]
    if not cards:
        base.update(
            _simple(
                "recommend",
                "К сожалению, по вашему запросу ничего не нашлось. "
                "Попробуйте описать иначе: жанр, настроение, автор, тропы.",
            )
        )
        return base

    stores_by_title: dict[str, list[dict]] = {}
    try:
        books_for_shops = [{"title": c["title"], "author": c["author"]} for c in cards]
        with_stores = await book_shop_agent.find_stores(books_for_shops)
        stores_by_title = {
            b["title"].strip().lower(): b["stores"] for b in with_stores
        }
    except Exception as exc:
        logger.warning("Поиск по магазинам не удался: %s", exc)

    answer = await formatter.compose_answer(
        cards, stores_by_title, decision.get("user_summary") or "", meta["tropes"]
    )

    recommendations = []
    for c in cards:
        recommendations.append(
            {
                "source_idx": c.get("source_idx"),
                "title": c["title"],
                "author": c.get("author", ""),
                "genres": c.get("genres", []),
                "tropes": c.get("tropes", []),
                "description": (c.get("description") or "")[:600],
                "score": c.get("score"),
                "stores": stores_by_title.get(str(c["title"]).strip().lower(), []),
            }
        )

    base.update(
        {
            "intent": "recommend",
            "answer": answer,
            "recommendations": recommendations,
            "matched": {
                "genres": meta["genres"],
                "tropes": meta["tropes"],
                "exclude": meta["exclude"],
            },
            "reason": decision.get("reason", ""),
        }
    )
    return base
