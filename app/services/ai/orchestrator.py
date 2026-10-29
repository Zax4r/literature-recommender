"""Оркестратор чата: роутинг + конвейер рекомендаций с деградацией.

Пайплайн: input -> router -> extractor -> hybrid search -> (магазины || форматер).
Все AI-шаги изолированы try/except и жёсткими таймаутами: сбой одного агента
не роняет весь запрос и не заставляет пользователя ждать десятки секунд.
"""

import asyncio
import logging
import re
import time
from typing import Any

from app.core.config import settings
from app.services.ai import context
from app.services.ai.agents import book_shop_agent, extractor, formatter, router_agent
from app.services.search import qdrant_search

logger = logging.getLogger("orchestrator")

# Сколько последних сообщений диалога показываем агентам.
HISTORY_CTX = 8

# Шаблонные преамбулы, которыми слабые модели портят суть запроса
# («Пользователь ищет книгу…» вместо «действия происходят на Аляске»).
_SUMMARY_PREAMBLES = (
    "пользователь ищет ",
    "пользователь хочет ",
    "пользователь просит ",
    "the user is looking for ",
    "the user wants ",
    "the user is searching for ",
)


def build_search_query(
    summary: str | None,
    genres: list[str],
    tropes: list[str],
    settings_: list[str] | None = None,
) -> str:
    parts = []
    if summary:
        parts.append(summary.strip())
    if genres:
        parts.append("ЖАНРЫ: " + ", ".join(genres))
    if tropes:
        parts.append("ТРОПЫ: " + ", ".join(tropes))
    if settings_:
        parts.append("МЕСТО И ВРЕМЯ ДЕЙСТВИЯ: " + ", ".join(settings_))
    return " ".join(p for p in parts if p)


def clean_summary(text: str | None) -> str:
    """Суть запроса без шаблонных преамбул вида «Пользователь ищет …»."""
    s = (text or "").strip()
    low = s.lower()
    for preamble in _SUMMARY_PREAMBLES:
        if low.startswith(preamble):
            s = s[len(preamble):].strip()
            break
    return s


def dialog_transcript(history: list | None) -> str:
    """История диалога одним текстом: роли заменены, содержание — данные."""
    if not history:
        return ""
    lines = []
    for m in history[-HISTORY_CTX:]:
        if not isinstance(m, dict) or not str(m.get("content") or "").strip():
            continue
        role = "Пользователь" if m.get("role") == "user" else "Ассистент"
        lines.append(f"{role}: {str(m.get('content') or '').strip()[:600]}")
    return "\n".join(lines)


def last_user_query(history: list | None) -> str:
    """Последний пользовательский запрос из истории (для продолжений диалога)."""
    for m in reversed(history or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content") or "").strip()[:1000]
    return ""


OVERFETCH = 5


def prefer_genres(cards: list[dict], genres: list[str]) -> list[dict]:
    """Оставляет книги, чьи жанры/тропы содержат запрошенный жанр (если такие нашлись).

    Гибридный поиск по короткому запросу вроде «фэнтези» поднимает в топ случайные книги,
    поэтому результат дополнительно сверяется с жанрами из запроса."""
    wanted = [g.strip().lower() for g in genres if g.strip()]
    if not wanted:
        return cards
    matched = [
        c
        for c in cards
        if any(w in " ".join([*c.get("genres", []), *c.get("tropes", [])]).lower() for w in wanted)
    ]
    return matched or cards


def _prefix_stem(word: str) -> str:
    """Грубый «стем» — префикс слова достаточно длинный, чтобы ловить падежные
    окончания («Аляска»/«Аляске»/«Аляскинский» → «аляс») и не давать ложных совпадений."""
    w = word.strip().lower()
    if not w:
        return ""
    return w[: max(4, len(w) - 2)]


def prefer_settings(cards: list[dict], settings_: list[str]) -> list[dict]:
    """Поднимает книги, у которых место/время действия из запроса есть в описании.

    «Место действия» не хранится отдельным полем каталога, но почти всегда
    встречается в описании книги (Аляска, Петербург, космос...). Поиск по
    префиксу-«стему», чтобы не терять падежные формы."""
    wanted = [w for w in (_prefix_stem(s) for s in settings_) if w]
    if not wanted:
        return cards
    matched = [
        c
        for c in cards
        if any(stem in (c.get("description") or "").lower() for stem in wanted)
    ]
    return matched or cards


def card_text(card: dict) -> str:
    """Все текстовые поля карточки в нижнем регистре — для проверки совпадений."""
    fields = [
        card.get("title"),
        card.get("author"),
        card.get("description"),
        *(card.get("genres") or []),
        *(card.get("tropes") or []),
    ]
    return " ".join(str(f) for f in fields if f).lower()


def _wanted_terms(
    genres: list[str],
    tropes: list[str],
    settings_: list[str],
) -> list[str]:
    """Признаки запроса одним списком слов/«стемов»: жанры, тропы, места действия."""
    out: list[str] = []
    for g in genres or []:
        if g.strip():
            out.append(g.strip().lower())
    for t in tropes or []:
        if t.strip():
            out.append(t.strip().lower())
    out.extend(_prefix_stem(s) for s in (settings_ or []))
    return [w for w in out if w]


def relevant_cards(
    cards: list[dict],
    *,
    genres: list[str],
    tropes: list[str],
    settings_: list[str],
) -> list[dict] | None:
    """Оставляет только карточки со следами запрошенных признаков.

    Гипотеза: Qdrant всегда возвращает top_k карточек даже при полном несовпадении,
    а форматтер в этом случае вместо честного «ничего не нашлось» начинает
    повторять запрос. Гейт: если явные признаки были извлечены, но ни одна книга
    их не содержит — вернуть пустой список (оркестратор ответит честно).
    None — явных признаков в запросе не было, фильтр не применять."""
    wanted = _wanted_terms(genres, tropes, settings_)
    if not wanted:
        return None
    return [c for c in cards if any(w in card_text(c) for w in wanted)]


_LOCATION_PATTERNS = (
    re.compile(
        r"(?:действия|действие|события|событие|история|сюжет)\s+"
        r"(?:происходят|происходит|разворачиваются|разворачивается)\s+"
        r"(?:в|на)\s+([а-яёa-z][а-яёa-z-]{2,})",
        flags=re.IGNORECASE,
    ),
    re.compile(r"где[- ]то\s+(?:в|на)\s+([а-яёa-z][а-яёa-z-]{2,})"),
)


def extract_location_hints(text: str | None) -> list[str]:
    """Локации из запроса вида «действия происходят на Аляске» — без LLM.

    Страховка на случай, когда модель-экстрактор не заполнила settings:
    место действия всё равно попадает в поиск и в гейт релевантности."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for pattern in _LOCATION_PATTERNS:
        for m in pattern.finditer(text):
            word = m.group(1)
            key = word.lower()
            if key not in seen:
                seen.add(key)
                out.append(word)
    return out[:3]


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


def _fallback_answer(cards: list[dict]) -> str:
    titles = ", ".join(f"«{c.get('title', '')}»" for c in cards)
    return f"По вашему запросу нашёл такие книги: {titles}."


async def _bounded(coro: Any, seconds: float, default: Any, *, label: str = "stage") -> Any:
    """Запускает этап с жёстким таймаутом; при провале — дефолт (деградация)."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        logger.warning("%s: превышен таймаут %ss", label, seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: ошибка: %s", label, exc)
    return default


async def run_chat(
    *,
    user_text: str = "",
    untrusted_text: str | None = None,
    source: str = "chat",
    user_id: str | None = None,
    history: list | None = None,
) -> dict:
    history = history or []
    base = _base(user_text, untrusted_text, source)
    full_input = "\n".join(p for p in (user_text or "", untrusted_text or "") if p)
    dialog = dialog_transcript(history) or ""

    t_start = time.perf_counter()
    timings: dict[str, int] = {}

    def mark(name: str) -> None:
        timings[name] = int((time.perf_counter() - t_start) * 1000)

    decision = await _bounded(
        router_agent.route_request(
            full_input or "(пусто)", history=dialog, has_history=bool(history)
        ),
        settings.AGENT_TIMEOUT_SECONDS,
        {
            "intent": "recommend",
            "risk": "low",
            "user_summary": (full_input or "")[:300],
            "has_text_fragment": bool(untrusted_text),
            "reason": "router timeout",
        },
        label="router",
    )
    mark("router")
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
        # Никогда не отвечаем словами пользователя: уточняющий вопрос строим сами,
        # иначе слабая модель «пересказывает» запрос и ответ получается эхом без пользы.
        question = (
            "Уточните, пожалуйста, чтобы я подобрал точнее: жанр (например, детектив "
            "или фэнтези), настроение, место или время действия, автор — или книга, "
            "похожую на которую вы ищете?"
        )
        base.update(_simple(intent, question, question=question))
        return base

    # --- продолжение диалога: ищем по теме из истории + текущему уточнению ---
    follow_up = intent == "follow_up"
    if follow_up:
        prior = clean_summary(decision.get("user_summary")) or last_user_query(history)
        scope = " ".join(p for p in (prior, user_text or "") if p).strip()[:2000]
        if not scope:
            base.update(
                _simple(
                    intent,
                    "Могу продолжить подбор. Опишите направление — жанр, автор, "
                    "настроение — и я поищу похожие книги.",
                )
            )
            return base
    else:
        scope = user_text

    # --- recommend ---
    meta = await _bounded(
        extractor.extract_metadata(scope, untrusted_text, history=dialog),
        settings.AGENT_TIMEOUT_SECONDS,
        {"genres": [], "tropes": [], "settings": [], "exclude": []},
        label="extractor",
    )
    mark("extractor")

    # Страховка: место действия вида «действия/события происходят на …» вытаскиваем
    # и без LLM-экстрактора, если он вернул пустой settings (короткое типизированное
    # сообщение, без файла).
    if not meta["settings"] and user_text and not untrusted_text and len(user_text.strip()) <= 300:
        meta["settings"] = extract_location_hints(user_text)

    # Суть запроса для форматтера: свои слова пользователя, если они короткие,
    # иначе пересказ роутера (очищенный от «Пользователь ищет…»).
    if follow_up:
        summary = scope[:300]
    elif user_text and len(user_text.strip()) <= 300:
        summary = user_text.strip()
    else:
        summary = (
            clean_summary(decision.get("user_summary"))
            or user_text
            or untrusted_text
            or scope
        )
    summary = summary[:300]

    # В поиск отдаём формулировку пользователя (или продолжение), а не пересказ роутера:
    # он точнее и не содержит шумовых преамбул.
    query_base = scope if (user_text or follow_up) else summary or untrusted_text or scope
    query_text = build_search_query(
        query_base.strip(), meta["genres"], meta["tropes"], meta["settings"]
    ).strip()

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

    cards = await _bounded(
        qdrant_search.hybrid_search(
            query_text,
            exclude_tropes=meta["exclude"],
            exclude_ids=sorted(exclude_ids),
            top_k=settings.SEARCH_TOP_K * OVERFETCH,
            prefetch_k=settings.SEARCH_PREFETCH_K,
        ),
        settings.SEARCH_TIMEOUT_SECONDS,
        None,
        label="search",
    )
    if cards is None:
        cards = await _bounded(
            qdrant_search.dense_fallback(query_text, top_k=settings.SEARCH_TOP_K),
            settings.SEARCH_TIMEOUT_SECONDS,
            [],
            label="search-fallback",
        )
    cards = prefer_settings(
        prefer_genres(cards or [], meta["genres"]), meta["settings"]
    )
    checked = relevant_cards(
        cards, genres=meta["genres"], tropes=meta["tropes"], settings_=meta["settings"]
    )
    if checked is None:
        # Явных признаков экстрактор не нашёл — фильтровать нечем.
        cards = cards[: settings.SEARCH_TOP_K]
    elif checked:
        cards = checked[: settings.SEARCH_TOP_K]
    else:
        # Признаки запроса были (жанр, место действия...), но ни одна книга каталога
        # их не содержит. Не кормим форматтер нерелевантными карточками — честно говорим.
        logger.info("no relevant cards for features: %s", _wanted_terms(
            meta["genres"], meta["tropes"], meta["settings"]
        ))
        cards = []
    mark("search")

    if not cards:
        # В каталоге пусто по запросу — модель отвечает сама, из своих знаний:
        # честно говорит, что подходящих книг нет, и подсказывает известные
        # книги/авторов по теме или как переформулировать запрос.
        answer = await _bounded(
            formatter.compose_no_match(
                summary,
                matched_genres=meta["genres"],
                matched_tropes=meta["tropes"],
                matched_settings=meta["settings"],
            ),
            settings.AGENT_TIMEOUT_SECONDS,
            formatter._default_no_match(),
            label="formatter-no-match",
        )
        mark("formatter")
        base.update(_simple("recommend", answer, reason=decision.get("reason", "")))
        return base

    # Магазины и форматтер выполняются параллельно: тексту ответа ссылки не нужны.
    formatter_task = asyncio.create_task(
        formatter.compose_answer(
            cards,
            {},
            summary,
            matched_genres=meta["genres"],
            matched_tropes=meta["tropes"],
            matched_settings=meta["settings"],
        )
    )
    stores_by_title: dict[str, list[dict]] = {}
    with_stores = await _bounded(
        book_shop_agent.find_stores(
            [{"title": c["title"], "author": c["author"]} for c in cards]
        ),
        settings.SHOP_TIMEOUT_SECONDS + settings.AGENT_TIMEOUT_SECONDS,
        [],
        label="shops",
    )
    stores_by_title = {b["title"].strip().lower(): b["stores"] for b in with_stores}
    mark("shops")

    answer = await _bounded(
        formatter_task,
        settings.AGENT_TIMEOUT_SECONDS,
        _fallback_answer(cards),
        label="formatter",
    )
    mark("formatter")

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
                "settings": meta["settings"],
                "exclude": meta["exclude"],
            },
            "reason": decision.get("reason", ""),
        }
    )
    total_ms = int((time.perf_counter() - t_start) * 1000)
    logger.info("chat timing: %s | total=%d ms", timings, total_ms)
    print(f"CHAT_TIMING {timings} total={total_ms}ms", flush=True)
    return base