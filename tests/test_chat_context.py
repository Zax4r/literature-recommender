"""Чистые функции конвейера чата: работа с контекстом и защита от «эха» запроса.

Эти правила чинят два бага:
- продолжения диалога («ещё», «а похожее на…») не видят историю;
- слабая модель-роутер формулирует суть как «Пользователь ищет книгу…»,
  а форматтер повторяет её дословно вместо объяснения.
"""

from app.services.ai.agents.formatter import _is_echo
from app.services.ai.orchestrator import (
    build_search_query,
    clean_summary,
    dialog_transcript,
    extract_location_hints,
    last_user_query,
    prefer_settings,
    relevant_cards,
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
        {"title": "К", "author": "", "description": "Про космос",
         "genres": ["Фантастика"], "tropes": []},
    ]
    # Признаки были, но ни одна книга не совпала.
    assert relevant_cards(cards, genres=["детектив"], tropes=[], settings_=[]) == []
    assert relevant_cards(cards, genres=[], tropes=[], settings_=["Аляска"]) == []
    # Совпадение по жанру/описанию остаётся.
    assert relevant_cards(cards, genres=["фантастика"], tropes=[], settings_=[]) == cards
    assert relevant_cards(cards, genres=[], tropes=[], settings_=["аляс", "космос"]) == cards


def test_relevant_cards_no_features_returns_none() -> None:
    """Без явных признаков фильтр не применяется (None), чтобы не резать нечёткие запросы."""
    cards = [{"title": "А", "author": "", "description": "X", "genres": [], "tropes": []}]
    assert relevant_cards(cards, genres=[], tropes=[], settings_=[]) is None


def test_extract_location_hints() -> None:
    """Локация из «действия/события происходят на …» достаётся и без LLM-экстрактора."""
    assert extract_location_hints("Хочу книгу, где действия происходят на Аляске") == ["Аляске"]
    assert extract_location_hints("хочу книгу где действия происходят на аляске") == ["аляске"]
    assert extract_location_hints("события происходят в Петербурге") == ["Петербурге"]
    assert extract_location_hints("просто тёмное фэнтези") == []
    assert extract_location_hints("") == []