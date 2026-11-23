"""Резервный словарный поиск по каталогу, когда Qdrant недоступен."""

from app.services.search.db_fallback import build_terms


def test_build_terms_keeps_features_and_skips_service_words() -> None:
    terms = build_terms("Книга похожая на ведьмака", ["фэнтези", "тёмное фэнтези"])
    assert "фэнтези" in terms
    assert "тёмное" in terms
    assert "ведьмака" in terms
    assert "книга" not in terms
    assert "похожая" not in terms


def test_build_terms_keeps_location_and_deduplicates() -> None:
    terms = build_terms("события на Аляске", ["Аляска"])
    assert "аляске" in terms
    assert "аляска" in terms
    assert "события" not in terms
    assert len(terms) == len(set(terms))


def test_build_terms_empty_request() -> None:
    assert build_terms("", []) == []
    assert build_terms(None, None) == []
