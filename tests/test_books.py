import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from app.services import ucsd
from app.services.ucsd import BookRecord, parse_record


def fake_books(limit: int) -> Iterator[BookRecord]:
    for i in range(1, min(limit, 30) + 1):
        yield BookRecord(
            str(i), f"Book {i}", "x" * 400, None, f"https://example.com/{i}", (str(i % 3),)
        )


def fake_author_names(author_ids: set[str]) -> dict[str, str]:
    return {a: f"Author {a}" for a in author_ids}


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "username": "alice", "password": "password123"},
    )
    token = client.post(
        "/api/v1/auth/login", data={"username": "a@b.com", "password": "password123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(auth: dict[str, str], session_factory: sessionmaker[Session]) -> dict[str, str]:
    with session_factory() as session:
        session.execute(update(User).values(is_admin=True))
        session.commit()
    return auth


@pytest.fixture
def imported(client: TestClient, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ucsd, "fetch_books", fake_books)
    monkeypatch.setattr(ucsd, "fetch_author_names", fake_author_names)
    assert client.post("/api/v1/books/import?count=25", headers=admin).status_code == 200


def test_parse_record_cleans_html_and_skips_unusable() -> None:
    line = json.dumps(
        {"book_id": "7", "title": " T ", "description": "a<br />b &amp; c\n\n d", "url": "u"}
    ).encode()
    record = parse_record(line)
    assert record is not None
    assert (record.title, record.description) == ("T", "a b & c d")
    assert (
        parse_record(json.dumps({"book_id": "8", "title": "T", "description": ""}).encode()) is None
    )


def test_import_requires_auth(client: TestClient) -> None:
    assert client.post("/api/v1/books/import").status_code == 401


def test_import_forbidden_for_regular_user(client: TestClient, auth: dict[str, str]) -> None:
    assert client.post("/api/v1/books/import", headers=auth).status_code == 403


def test_import_is_idempotent(client: TestClient, admin: dict[str, str], imported: None) -> None:
    again = client.post("/api/v1/books/import?count=25", headers=admin)
    assert again.json() == {"imported": 0, "skipped": 25}
    assert client.get("/api/v1/books").json()["total"] == 25


def test_feed_pagination(client: TestClient, imported: None) -> None:
    page = client.get("/api/v1/books?offset=20&limit=10").json()
    assert (page["total"], page["offset"], page["limit"]) == (25, 20, 10)
    assert [b["title"] for b in page["items"]] == [f"Book {i}" for i in range(21, 26)]
    assert client.get("/api/v1/books?limit=0").status_code == 422
    assert client.get("/api/v1/books?offset=-1").status_code == 422


def test_book_detail_truncates_description(client: TestClient, imported: None) -> None:
    book = client.get("/api/v1/books/1").json()
    assert book["title"] == "Book 1"
    assert book["authors"] == ["Author 1"]
    assert book["is_favorite"] is False
    assert len(book["description"]) == 250
    assert client.get("/api/v1/books/999").status_code == 404


def test_favorites_flow(client: TestClient, auth: dict[str, str], imported: None) -> None:
    assert client.put("/api/v1/books/2/favorite", headers=auth).status_code == 204
    assert client.put("/api/v1/books/2/favorite", headers=auth).status_code == 204
    assert client.put("/api/v1/books/3/favorite", headers=auth).status_code == 204
    favorites = client.get("/api/v1/users/me/favorites", headers=auth).json()
    assert favorites["total"] == 2
    assert [b["id"] for b in favorites["items"]] == [2, 3]
    assert client.delete("/api/v1/books/2/favorite", headers=auth).status_code == 204
    assert client.get("/api/v1/users/me/favorites", headers=auth).json()["total"] == 1
    assert client.get("/api/v1/books/3", headers=auth).json()["is_favorite"] is True
    assert client.get("/api/v1/books/2", headers=auth).json()["is_favorite"] is False
    flags = {
        b["id"]: b["is_favorite"] for b in client.get("/api/v1/books", headers=auth).json()["items"]
    }
    assert flags[3] is True and flags[2] is False
    assert client.put("/api/v1/books/999/favorite", headers=auth).status_code == 404
    assert client.put("/api/v1/books/1/favorite").status_code == 401


def test_login_by_username(client: TestClient, auth: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/auth/login", data={"username": "alice", "password": "password123"}
    )
    assert response.status_code == 200
