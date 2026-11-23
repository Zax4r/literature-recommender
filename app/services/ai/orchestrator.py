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
from app.services.search import db_fallback, qdrant_search

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


# Сообщения, которые сами по себе не содержат темы поиска. Только для них
# имеет смысл подмешивать тему из истории; «события на Аляске» или «в космосе»
# — это новый поисковый признак, а не продолжение старой темы.
_CONTINUATION_ONLY = {
    "ещё",
    "еще",
    "дальше",
    "продолжи",
    "продолжай",
    "а ещё",
    "а еще",
    "и ещё",
    "и еще",
    "ещё книги",
    "еще книги",
    "ещё варианты",
    "еще варианты",
    "ещё похожее",
    "еще похожее",
    "а ещё похожее",
    "а еще похожее",
    "а похожее",
    "похожее",
    "аналоги",
    "аналог",
    "что ещё",
    "что еще",
    "что ещё есть",
    "что еще есть",
    "ещё что-нибудь",
    "еще что-нибудь",
    "а что ещё есть",
    "а что еще есть",
}


def _normalize_phrase(text: str | None) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip().strip(".,!?;:…").lower())
    return s


def is_continuation_only(text: str | None) -> bool:
    """True, если сообщение — чистое продолжение («ещё», «продолжи») без своей темы."""
    s = _normalize_phrase(text)
    return not s or s in _CONTINUATION_ONLY


def keep_history_context(
    *,
    intent: str,
    current_genres: list[str],
    current_tropes: list[str],
    user_text: str,
) -> bool:
    """Нужно ли учитывать тему прошлой темы как мягкий контекст.

    Контекст полезен для коротких уточнений («в космосе» после «похоже на
    Ведьмака»), но вреден для нового самостоятельного запроса со своим жанром
    или книгой: иначе «научная фантастика про ИИ» после фэнтези тянула бы магию.
    """
    if intent == "follow_up":
        return True
    return not (
        current_genres
        or current_tropes
        or is_similarity_request(user_text)
        or _has_quoted_title(user_text)
    )


def resolve_scope(
    *,
    user_text: str,
    intent: str,
    router_summary: str | None,
    history: list | None,
) -> str:
    """Текст, по которому ищем книги.

    Для нового запроса — только текущее сообщение. Для продолжения без своей
    темы — тема из истории + продолжение. Раньше сюда всегда подмешивалась
    тема из истории, поэтому «события на Аляске» после научной фантастики
    искались как «космос + Аляска», а слово «похожие» из прошлого запроса
    отключало все фильтры.
    """
    current = (user_text or "").strip()
    if intent != "follow_up":
        return current[:2000]

    prior = clean_summary(router_summary) or last_user_query(history)
    if is_continuation_only(current):
        return " ".join(p for p in (prior.strip(), current) if p).strip()[:2000]
    # В сообщении есть свой признак (место, жанр, автор) — он важнее старой темы.
    return (current or prior).strip()[:2000]


OVERFETCH = 5
# Для «похожего на X», где экстрактор не дал ни жанров, ни тропов, оставляем
# только книги, близкие к лучшей по скору: иначе в карточки попадает случайный хвост.
SIMILAR_NO_FEATURES_SCORE_RATIO = 0.6


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
    """Поднимает книги, у которых все места/время действия из запроса есть в тексте.

    «Место действия» не хранится отдельным полем каталога, но почти всегда
    встречается в описании книги (Аляска, Петербург, космос...). Поиск по
    префиксу-«стему», чтобы не терять падежные формы. Если совпадений нет,
    список не меняется — окончательное решение принимает гейт релевантности.
    """
    wanted = [w for w in (_prefix_stem(s) for s in settings_) if w]
    if not wanted:
        return cards
    matched = [c for c in cards if all(stem in card_text(c) for stem in wanted)]
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


def card_meta_text(card: dict) -> str:
    """Метаданные карточки без описания — для проверки жанров и тропов.

    Описание может упомянуть «фэнтези» или «космос» в переносном смысле,
    поэтому жанр/троп сверяем только с полями каталога.
    """
    fields = [
        card.get("title"),
        card.get("author"),
        *(card.get("genres") or []),
        *(card.get("tropes") or []),
    ]
    return " ".join(str(f) for f in fields if f).lower()


def _clean_terms(values: list[str] | None) -> list[str]:
    return [v.strip().lower() for v in (values or []) if v.strip()]


def _setting_stems(values: list[str] | None) -> list[str]:
    return [stem for stem in (_prefix_stem(v) for v in (values or [])) if stem]


def relevant_cards(
    cards: list[dict],
    *,
    genres: list[str],
    tropes: list[str],
    settings_: list[str],
) -> list[dict] | None:
    """Оставляет только карточки, где есть запрошенные признаки.

    Правила (а не «совпало хоть что-нибудь», как раньше):
    - каждое место/время действия из запроса должно встречаться в тексте книги;
    - если запрошен жанр, у книги должен быть этот жанр (тропы помогают
      ранжировать, но не заменяют жанр);
    - если жанров нет, достаточно любого запрошенного тропа.

    None — явных признаков в запросе не было, фильтр не применять.
    Пустой список — признаки были, но ни одна книга им не соответствует;
    оркестратор честно ответит «ничего не нашлось».
    """
    genre_terms = _clean_terms(genres)
    trope_terms = _clean_terms(tropes)
    setting_terms = _setting_stems(settings_)
    if not (genre_terms or trope_terms or setting_terms):
        return None

    def matches(card: dict) -> bool:
        if setting_terms:
            text = card_text(card)
            if not all(term in text for term in setting_terms):
                return False
        if genre_terms:
            meta = card_meta_text(card)
            if not any(term in meta for term in genre_terms):
                return False
        if not genre_terms and trope_terms:
            meta = card_meta_text(card)
            if not any(term in meta for term in trope_terms):
                return False
        return True

    return [c for c in cards if matches(c)]


def trim_weak(cards: list[dict], *, min_relative: float | None = None) -> list[dict]:
    """Убирает карточки со скором заметно ниже лучшей в подборке.

    Qdrant/RRF всегда отдаёт top_k, поэтому без отсечения в конце подборки
    оказываются книги, совпавшие только по одному слову. Для «похожего на X»
    без извлечённых признаков порог можно поднять: иначе в подборку попадают
    случайные книги из хвоста.
    """
    if len(cards) <= 1:
        return cards
    ratio = settings.SEARCH_MIN_RELATIVE_SCORE if min_relative is None else min_relative
    scores = [float(c.get("score") or 0.0) for c in cards]
    best = max(scores)
    if best <= 0:
        return cards
    cutoff = best * ratio
    kept = [c for c, score in zip(cards, scores) if score >= cutoff]
    return kept or cards[:1]


def context_hits(card: dict, genres: list[str], tropes: list[str]) -> int:
    """Сколько мягких признаков прошлой темы есть у книги."""
    meta = card_meta_text(card)
    return sum(1 for g in _clean_terms(genres) if g in meta) + sum(
        1 for t in _clean_terms(tropes) if t in meta
    )


def rank_with_context(
    cards: list[dict],
    *,
    genres: list[str],
    tropes: list[str],
) -> list[dict]:
    """Поднимает книги, совпавшие с прошлой темой, не отсекая остальные.

    Новый запрос («в космосе») остаётся жёстким фильтром, а тема из истории
    («похоже на Ведьмака») работает как бонус к рангу. Поэтому подборка
    учитывает контекст, но не превращается в пустой список.
    """
    if not genres and not tropes:
        return cards

    def rank_key(card: dict) -> float:
        return float(card.get("score") or 0.0) + 0.05 * context_hits(card, genres, tropes)

    return sorted(cards, key=rank_key, reverse=True)


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


# Слова/обороты «похожего» запроса: тут совпадают по смыслу, а не по признакам.
_SIMILARITY_RE = re.compile(
    r"похож\w*|аналог|в духе|подобн|наподобие|такое как|что-то (?:такое|вроде)|в стиле",
    re.IGNORECASE,
)


def _has_quoted_title(text: str) -> bool:
    """«…» или \"…\" с многословным содержимым — похоже на название книги."""
    for m in re.finditer(r"[«\"]([^»\"]{2,60})[»\"]", text):
        title = m.group(1).strip()
        if len(re.split(r"\s+", title)) >= 2 or len(title) >= 6:
            return True
    return False


def is_similarity_request(text: str | None) -> bool:
    """True, если запрос — «похожее на книгу/как X»: сравниваем смысл, а не жанры.

    Для таких запросов гейт релевантности и фильтры по жанрам/местам отключаются,
    иначе из похожих книг остаются только буквально совпавшие по словам."""
    if not text:
        return False
    return bool(_SIMILARITY_RE.search(text)) or _has_quoted_title(text)


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

    # --- продолжение диалога: старую тему берём только для чистых продолжений ---
    follow_up = intent == "follow_up"
    scope = resolve_scope(
        user_text=user_text,
        intent=intent,
        router_summary=decision.get("user_summary"),
        history=history,
    )
    if follow_up and not scope:
        base.update(
            _simple(
                intent,
                "Могу продолжить подбор. Опишите направление — жанр, автор, "
                "настроение — и я поищу похожие книги.",
            )
        )
        return base

    # --- recommend ---
    meta = await _bounded(
        extractor.extract_metadata(scope, untrusted_text, history=dialog),
        settings.AGENT_TIMEOUT_SECONDS,
        {
            "genres": [],
            "tropes": [],
            "settings": [],
            "exclude": [],
            "context_genres": [],
            "context_tropes": [],
        },
        label="extractor",
    )
    mark("extractor")

    current_genres = meta["genres"]
    current_tropes = meta["tropes"]
    context_genres = meta["context_genres"]
    context_tropes = meta["context_tropes"]

    # Полностью новый запрос со своим жанром/книгой не должен тянуть контекст
    # из прошлой темы. Контекст оставляем для коротких уточнений места/времени
    # («в космосе», «события на Аляске») и чистых продолжений.
    if not keep_history_context(
        intent=intent,
        current_genres=current_genres,
        current_tropes=current_tropes,
        user_text=user_text,
    ):
        context_genres, context_tropes = [], []

    # Чистое продолжение: текущих признаков нет, но тема в истории есть.
    # В этом случае контекст становится основным, иначе поиск будет случайным.
    if not (current_genres or current_tropes or meta["settings"]) and (
        context_genres or context_tropes
    ):
        current_genres, current_tropes = context_genres, context_tropes
        context_genres, context_tropes = [], []

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

    # Форматтеру говорим и о текущем запросе, и о мягком контексте прошлой темы.
    context_label = ", ".join([*context_genres, *context_tropes])
    formatter_summary = summary
    if context_label:
        formatter_summary = f"{summary}. Учитывай предыдущую тему: {context_label}"[:300]

    # В поиск отдаём формулировку пользователя (или продолжение), а не пересказ роутера:
    # он точнее и не содержит шумовых преамбул.
    query_base = scope if (user_text or follow_up) else summary or untrusted_text or scope

    # «Похожее на книгу X»: смысловое совпадение, но извлечённые жанры/тропы
    # всё равно помогают отсечь случайные книги. Раньше здесь отключались все
    # фильтры, и на «книгу похожую на Ведьмака» приходили справочники по стилю.
    similar = is_similarity_request(query_base) or is_similarity_request(user_text)
    query_text = build_search_query(
        (query_base or "").strip()[:700 if similar else 2000],
        [*current_genres, *context_genres],
        [*current_tropes, *context_tropes],
        meta["settings"],
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
    search_unavailable = cards is None
    if search_unavailable:
        cards = await _bounded(
            qdrant_search.dense_fallback(query_text, top_k=settings.SEARCH_TOP_K),
            settings.SEARCH_TIMEOUT_SECONDS,
            None,
            label="search-fallback",
        )
        search_unavailable = cards is None

    used_db_fallback = False
    if search_unavailable:
        # Qdrant — основной поиск, но если он упал, не выдаём «книг нет».
        logger.warning("Qdrant недоступен; резервный поиск по каталогу в Postgres")
        cards = await _bounded(
            db_fallback.search_books(
                query_text,
                features=[
                    *current_genres,
                    *current_tropes,
                    *context_genres,
                    *context_tropes,
                    *meta["settings"],
                ],
                exclude_ids=sorted(exclude_ids),
                exclude_tropes=meta["exclude"],
                top_k=settings.SEARCH_TOP_K * OVERFETCH,
            ),
            10.0,
            None,
            label="search-db-fallback",
        )
        search_unavailable = cards is None
        used_db_fallback = not search_unavailable

    raw_cards = cards or []
    if similar:
        # Место действия из книги-образца — мягкий приоритет, а не жёсткий фильтр:
        # у «похожих» книг оно может быть другим. Жанры/тропы при этом проверяем.
        candidates = prefer_genres(prefer_settings(raw_cards, meta["settings"]), current_genres)
        checked = relevant_cards(
            candidates,
            genres=current_genres,
            tropes=[] if current_genres else current_tropes,
            settings_=[],
        )
    else:
        candidates = prefer_settings(
            prefer_genres(raw_cards, current_genres), meta["settings"]
        )
        checked = relevant_cards(
            candidates,
            genres=current_genres,
            tropes=current_tropes,
            settings_=meta["settings"],
        )

    limited_ratio: float | None = None
    if checked is None:
        # Явных признаков экстрактор не нашёл — фильтровать нечем.
        selected = candidates
        if similar:
            limited_ratio = SIMILAR_NO_FEATURES_SCORE_RATIO
    elif checked:
        selected = checked
    else:
        # Признаки запроса были (жанр, место действия...), но ни одна книга каталога
        # им не соответствует. Не кормим форматтер нерелевантными карточками.
        logger.info(
            "no relevant cards for features: genres=%s tropes=%s settings=%s (similar=%s)",
            current_genres,
            current_tropes,
            meta["settings"],
            similar,
        )
        selected = []

    if selected:
        # Контекст прошлой темы — мягкий буст: книги, совпавшие с ним, идут выше,
        # но жёсткий фильтр по новому запросу уже применён выше.
        selected = rank_with_context(
            selected,
            genres=context_genres,
            tropes=[*current_tropes, *context_tropes],
        )
        cards = trim_weak(selected, min_relative=limited_ratio)[: settings.SEARCH_TOP_K]
    else:
        cards = []
    logger.info(
        "chat search: intent=%s follow_up=%s similar=%s db_fallback=%s unavailable=%s "
        "query=%r meta=%s -> %d cards",
        intent,
        follow_up,
        similar,
        used_db_fallback,
        search_unavailable,
        query_text[:300],
        meta,
        len(cards),
    )
    mark("search")

    if not cards:
        if search_unavailable:
            answer = (
                "Сейчас поиск по каталогу временно недоступен — это не значит, что "
                "подходящих книг нет. Попробуйте, пожалуйста, ещё раз через минуту."
            )
            base.update(_simple("recommend", answer, reason=decision.get("reason", "")))
            return base
        # В каталоге пусто по запросу — модель отвечает сама, из своих знаний:
        # честно говорит, что подходящих книг нет, и подсказывает известные
        # книги/авторов по теме или как переформулировать запрос.
        answer = await _bounded(
            formatter.compose_no_match(
                formatter_summary,
                matched_genres=[*current_genres, *context_genres],
                matched_tropes=[*current_tropes, *context_tropes],
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
            formatter_summary,
            matched_genres=current_genres,
            matched_tropes=current_tropes,
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
                "genres": current_genres,
                "tropes": current_tropes,
                "settings": meta["settings"],
                "context_genres": context_genres,
                "context_tropes": context_tropes,
                "exclude": meta["exclude"],
            },
            "reason": decision.get("reason", ""),
        }
    )
    total_ms = int((time.perf_counter() - t_start) * 1000)
    logger.info("chat timing: %s | total=%d ms", timings, total_ms)
    print(f"CHAT_TIMING {timings} total={total_ms}ms", flush=True)
    return base