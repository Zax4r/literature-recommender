"""The chat endpoint with the LLM pipeline replaced by a stub; everything around it is real."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api import chat
from app.services.ai import context, orchestrator

calls: list[dict[str, object]] = []


async def fake_run_chat(**kwargs: object) -> dict[str, object]:
    calls.append(kwargs)
    return {
        "intent": "recommend",
        "answer": "Вот что я нашёл",
        "recommendations": [
            {
                "source_idx": 3,
                "title": "Book 4",
                "author": "Author 1",
                "tropes": ["Найденная семья"],
                "stores": [
                    {"name": "OZ.by", "url": "https://www.oz.by/search/?q=x", "kind": "paper"}
                ],
            },
            {
                "source_idx": 9999,
                "title": "Not in catalog",
                "author": "?",
                "tropes": [],
                "stores": [],
            },
        ],
    }


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]) -> None:
    calls.clear()
    monkeypatch.setattr(orchestrator, "run_chat", fake_run_chat)
    monkeypatch.setattr(chat, "SessionLocal", session_factory)
    monkeypatch.setattr(context, "SessionLocal", session_factory)


def test_anonymous_chat_gets_catalog_ids_but_no_history(client: TestClient, imported: None) -> None:
    response = client.post("/api/v1/chat", data={"message": "хочу фэнтези"})
    assert response.status_code == 200
    body = response.json()
    assert [c["book_id"] for c in body["recommendations"]] == [4, None]
    assert "recommendation_id" not in body
    assert calls[0]["user_id"] is None


def test_chat_saves_history_for_logged_in_user(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    body = client.post("/api/v1/chat", data={"message": "хочу фэнтези"}, headers=auth).json()
    assert calls[0]["user_id"] == "1"

    saved = client.get(f"/api/v1/recommendations/{body['recommendation_id']}", headers=auth).json()
    assert saved["query"] == "хочу фэнтези" and saved["answer"] == "Вот что я нашёл"
    assert saved["source"] == "chat"
    assert [i["book"]["id"] for i in saved["items"]] == [4]  # the unknown book is skipped
    assert saved["items"][0]["reason"] == "Найденная семья"
    assert saved["items"][0]["stores"][0]["name"] == "OZ.by"

    history = client.get("/api/v1/recommendations", headers=auth).json()
    assert history["total"] == 1 and history["items"][0]["id"] == saved["id"]


def test_chat_history_is_private(client: TestClient, auth: dict[str, str], imported: None) -> None:
    rec_id = client.post("/api/v1/chat", data={"message": "x"}, headers=auth).json()[
        "recommendation_id"
    ]
    client.post(
        "/api/v1/auth/register",
        json={"email": "b@b.com", "username": "bob", "password": "password123"},
    )
    token = client.post(
        "/api/v1/auth/login", data={"username": "bob", "password": "password123"}
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/v1/recommendations/{rec_id}", headers=other).status_code == 404
    assert client.get("/api/v1/recommendations", headers=other).json()["total"] == 0
    assert client.get("/api/v1/recommendations").status_code == 401


@pytest.mark.anyio
async def test_filtered_ids_are_sources_of_read_reading_dropped(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    for book_id, status in ((1, "read"), (2, "reading"), (3, "dropped"), (4, "planned")):
        client.put(f"/api/v1/books/{book_id}/entry", headers=auth, json={"status": status})
    assert await context.get_filtered_book_ids("1") == {0, 1, 2}  # source_idx = id - 1
    assert await context.get_filtered_book_ids(None) == set()
