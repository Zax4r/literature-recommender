"""Чистые функции конвейера чата: работа с контекстом и защита от «эха» запроса.

Эти правила чинят два бага:
- продолжения диалога («ещё», «а похожее на…») не видят историю;
- слабая модель-роутер формулирует суть как «Пользователь ищет книгу…»,
  а форматтер повторяет её дословно вместо объяснения.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.agents import formatter as formatter_mod
from app.services.ai.agents.formatter import _is_echo
from app.services.ai.orchestrator import (
    build_search_query,
    clean_summary,
    context_hits,
    dialog_transcript,
    extract_location_hints,
    is_continuation_only,
    is_similarity_request,
    keep_history_context,
    last_user_query,
    prefer_settings,
    rank_with_context,
    relevant_cards,
    resolve_scope,
    trim_weak,
)


def test_clean_summary_strips_router_preamble() -> None:
    """«Пользователь ищет …» не должно попадать в поисковый запрос."""
    assert clean_summary("Пользователь ищет книгу в которой действия происходят на аляске") == (
        "книгу в которой действия происходят на аляске"
    )
    assert clean_summary("The user is looking for something dark") == "something dark"
    assert clean_summary("тёмное фэнтези") == "тёмное фэнтези"
    assert clean_summary(None) == ""


def test_build_search_query_includes_settings() -> None:
    q = build_search_query("действия происходят на аляске", [], [], ["Аляска"])
    assert q == "действия происходят на аляске МЕСТО И ВРЕМЯ ДЕЙСТВИЯ: Аляска"

    q2 = build_search_query("хочу фэнтези", ["фэнтези"], ["магия"], [])
    assert q2 == "хочу фэнтези ЖАНРЫ: фэнтези ТРОПЫ: магия"


def test_dialog_transcript_marks_roles() -> None:
    history = [
        {"role": "user", "content": "хочу фэнтези"},
        {"role": "assistant", "content": "Дюна"},
        {"role": "user", "content": "ещё"},
    ]
    assert dialog_transcript(history) == (
        "Пользователь: хочу фэнтези\nАссистент: Дюна\nПользователь: ещё"
    )
    assert dialog_transcript(None) == ""


def test_last_user_query_finds_newest_question() -> None:
    history = [
        {"role": "user", "content": "что-то мрачное"},
        {"role": "assistant", "content": "Дюна"},
        {"role": "user", "content": "а без магии"},
    ]
    assert last_user_query(history) == "а без магии"
    assert last_user_query([]) == ""


def test_is_continuation_only() -> None:
    assert is_continuation_only("ещё")
    assert is_continuation_only("Продолжи!")
    assert is_continuation_only("а ещё похожее")
    assert not is_continuation_only("события на Аляске")
    assert not is_continuation_only("в космосе")
    assert not is_continuation_only("а чтобы действие было на Аляске")
    assert not is_continuation_only("ещё что-нибудь мрачное про магов")


def test_resolve_scope_does_not_mix_stale_topic_into_new_request() -> None:
    """Новое место/жанр в сообщении важнее темы из истории.

    Именно эта ошибка давала после «научной фантастики про космос» на запрос
    «события на Аляске» подборку про космос, а не про Аляску.
    """
    history = [{"role": "user", "content": "Научная фантастика про космос"}]
    scope = resolve_scope(
        user_text="события на Аляске",
        intent="follow_up",
        router_summary="похожие книги на Ведьмака, уточнение о событиях на Аляске",
        history=history,
    )
    assert scope == "события на Аляске"

    # Чистое продолжение по-прежнему использует тему из истории.
    continuation = resolve_scope(
        user_text="ещё",
        intent="follow_up",
        router_summary="тёмное фэнтези про магов",
        history=history,
    )
    assert "тёмное фэнтези" in continuation

    # Новый самостоятельный запрос не зависит от истории.
    assert (
        resolve_scope(
            user_text="в космосе",
            intent="recommend",
            router_summary="похожее на Ведьмака",
            history=history,
        )
        == "в космосе"
    )


def test_prefer_settings_ranks_by_description() -> None:
    # «Аляске» (предложный) должно матчиться по запросу «Аляска» — префикс-стем.
    cards = [
        {"title": "А", "description": "Действие на Аляске, суровая зима"},
        {"title": "Б", "description": "Про город и любовь"},
    ]
    assert [c["title"] for c in prefer_settings(cards, ["Аляска"])] == ["А"]
    # Без места действия список не меняется.
    assert prefer_settings(cards, []) == cards
    # Точное совпадение тоже работает.
    exact = [
        {"title": "В", "description": "Космос и звёзды"},
        {"title": "Г", "description": "детектив"},
    ]
    assert [c["title"] for c in prefer_settings(exact, ["космос"])] == ["В"]


def test_formatter_echo_is_detected() -> None:
    """Ответ-эхо «Пользователь ищет книгу…» не должен прийти пользователю."""
    summary = "Пользователь ищет книгу в которой действия происходят на аляске"
    assert _is_echo(summary, summary) is True
    assert _is_echo("Книги, где события разворачиваются среди снегов Аляски", summary) is False
    assert _is_echo("", summary) is False
    assert (
        _is_echo(
            "По запросу «действия происходят на аляске» вот что нашлось",
            "действия происходят на аляске",
        )
        is False
    )


def test_relevant_cards_gates_empty_results() -> None:
    """Гейт релевантности: явные признаки без совпадений дают [] (честный «не нашлось»)."""
    cards = [
        {
            "title": "К",
            "author": "",
            "description": "Про космос",
            "genres": ["Фантастика"],
            "tropes": [],
        },
    ]
    # Признаки были, но ни одна книга не совпала.
    assert relevant_cards(cards, genres=["детектив"], tropes=[], settings_=[]) == []
    assert relevant_cards(cards, genres=[], tropes=[], settings_=["Аляска"]) == []
    # Совпадение по жанру/описанию остаётся.
    assert relevant_cards(cards, genres=["фантастика"], tropes=[], settings_=[]) == cards
    assert relevant_cards(cards, genres=[], tropes=[], settings_=["космос"]) == cards
    # Все места действия обязательны: «космос» не отменяет «Аляску».
    assert relevant_cards(cards, genres=[], tropes=[], settings_=["аляс", "космос"]) == []


def test_relevant_cards_requires_requested_genre() -> None:
    """Запрошенный жанр обязателен, даже если совпал троп.

    Иначе на «тёмное фэнтези с юмором» проходили любые юмористические книги.
    """
    cards = [
        {
            "title": "Смешная книга",
            "author": "",
            "description": "Бытовые шутки",
            "genres": ["современная проза"],
            "tropes": ["юмор"],
        },
        {
            "title": "Фэнтези",
            "author": "",
            "description": "Магия и драконы",
            "genres": ["фэнтези"],
            "tropes": ["юмор"],
        },
    ]
    out = relevant_cards(cards, genres=["фэнтези"], tropes=["юмор"], settings_=[])
    assert [c["title"] for c in out or []] == ["Фэнтези"]


def test_relevant_cards_no_features_returns_none() -> None:
    """Без явных признаков фильтр не применяется (None), чтобы не резать нечёткие запросы."""
    cards = [{"title": "А", "author": "", "description": "X", "genres": [], "tropes": []}]
    assert relevant_cards(cards, genres=[], tropes=[], settings_=[]) is None


def test_trim_weak_drops_tail() -> None:
    cards = [
        {"title": "A", "score": 0.5},
        {"title": "B", "score": 0.3},
        {"title": "C", "score": 0.05},
    ]
    assert [c["title"] for c in trim_weak(cards)] == ["A", "B"]
    assert [c["title"] for c in trim_weak(cards, min_relative=0.9)] == ["A"]


def test_keep_history_context_only_for_refinements() -> None:
    # Короткое уточнение места: прошлую тему используем.
    assert keep_history_context(
        intent="recommend",
        current_genres=[],
        current_tropes=[],
        user_text="в космосе",
    )
    assert keep_history_context(
        intent="recommend", current_genres=[], current_tropes=[], user_text="события на Аляске"
    )
    # Новый запрос со своим жанром или книгой: прошлую тему не тянем.
    assert not keep_history_context(
        intent="recommend",
        current_genres=["научная фантастика"],
        current_tropes=[],
        user_text="научная фантастика про ИИ",
    )
    assert not keep_history_context(
        intent="recommend",
        current_genres=[],
        current_tropes=[],
        user_text="похожее на «С жизнью наедине»",
    )


def test_context_ranking_boosts_previous_theme_without_filtering() -> None:
    """«в космосе» после «похоже на Ведьмака»: космос остаётся фильтром,
    а фэнтези из прошлой темы поднимает книгу выше, но не отсекает остальные."""
    cards = [
        {
            "title": "Научная фантастика в космосе",
            "genres": ["научная фантастика"],
            "tropes": ["космос"],
            "score": 0.5,
        },
        {
            "title": "Тёмное фэнтези в космосе",
            "genres": ["фэнтези"],
            "tropes": ["космос", "магия"],
            "score": 0.45,
        },
    ]
    assert context_hits(cards[1], ["фэнтези"], ["магия"]) == 2
    ranked = rank_with_context(cards, genres=["фэнтези"], tropes=["магия"])
    assert [c["title"] for c in ranked] == [
        "Тёмное фэнтези в космосе",
        "Научная фантастика в космосе",
    ]
    # Без контекста порядок поиска не меняется.
    assert rank_with_context(cards, genres=[], tropes=[]) == cards


def test_extract_location_hints() -> None:
    """Локация из «действия/события происходят на …» достаётся и без LLM-экстрактора."""
    assert extract_location_hints("Хочу книгу, где действия происходят на Аляске") == ["Аляске"]
    assert extract_location_hints("хочу книгу где действия происходят на аляске") == ["аляске"]
    assert extract_location_hints("события происходят в Петербурге") == ["Петербурге"]
    assert extract_location_hints("просто тёмное фэнтези") == []
    assert extract_location_hints("") == []


@pytest.mark.anyio
async def test_compose_no_match_uses_model_knowledge() -> None:
    """Когда в каталоге пусто, модель отвечает сама — из своих знаний, а не эхом."""

    async def fake_completion(*_: object, **__: object) -> str:
        return (
            '{"answer": "В каталоге пока нет таких книг. '
            'По этой теме известны Джек Лондон и Джон Кракауэр."}'
        )

    with patch.object(formatter_mod, "chat_completion", new=AsyncMock(side_effect=fake_completion)):
        out = await formatter_mod.compose_no_match("события происходят на аляске")
    assert "Кракауэр" in out or "кракауэр" in out


@pytest.mark.anyio
async def test_compose_no_match_blocks_echo() -> None:
    """Эхо запроса от модели отбрасывается — пользователь видит запасной ответ."""

    async def fake_echo(*_: object, **__: object) -> str:
        return '{"answer": "события происходят на аляске"}'

    with patch.object(formatter_mod, "chat_completion", new=AsyncMock(side_effect=fake_echo)):
        out = await formatter_mod.compose_no_match("события происходят на аляске")
    assert "не нашлось" in out.lower()
    assert "аляске" not in out.lower()


def test_is_similarity_request() -> None:
    """«Похожее на книгу X» — совпадение смысловое, гейт не применяем."""
    assert is_similarity_request(
        "Найти похожее по месту или сюжету Кристин Ханна «С жизнью наедине»"
    )
    assert is_similarity_request("похожее на Дюну")
    assert is_similarity_request("что-то вроде «Мастера и Маргариты»")
    assert is_similarity_request("аналог Литтл-Файр")
    # Явные запросы признаков similarity не считаются.
    assert not is_similarity_request("события происходят на аляске")
    assert not is_similarity_request("тёмное фэнтези про драконов")
    assert not is_similarity_request("посоветуй что-нибудь лёгкое")
    assert not is_similarity_request("")
