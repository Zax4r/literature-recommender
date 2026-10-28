import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.ai import orchestrator


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def run_chat(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        kwargs["on_stage"]("routing")
        return {"intent": "recommend", "answer": "Читайте Дюну", "recommendations": []}

    monkeypatch.setattr(orchestrator, "run_chat", run_chat)
    return calls


def events(body: str) -> list[tuple[str, Any]]:
    out = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n")
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_chat_is_saved_and_streamed(
    client: TestClient, auth: dict[str, str], fake_pipeline: list[dict[str, Any]]
) -> None:
    chat = client.post("/api/v1/chat/sessions", headers=auth).json()
    assert chat["title"] == "Новый чат"

    res = client.post(
        f"/api/v1/chat/sessions/{chat['id']}/messages",
        headers=auth,
        data={"message": "хочу фэнтези"},
    )
    assert res.status_code == 200
    assert [name for name, _ in events(res.text)] == ["user", "stage", "message"]

    saved = client.get(f"/api/v1/chat/sessions/{chat['id']}", headers=auth).json()
    assert saved["title"] == "хочу фэнтези"
    assert [(m["role"], m["content"]) for m in saved["messages"]] == [
        ("user", "хочу фэнтези"),
        ("assistant", "Читайте Дюну"),
    ]

    client.post(
        f"/api/v1/chat/sessions/{chat['id']}/messages", headers=auth, data={"message": "ещё"}
    )
    assert len(fake_pipeline[1]["history"]) == 2


def test_chats_are_private(
    client: TestClient, auth: dict[str, str], fake_pipeline: list[dict[str, Any]]
) -> None:
    chat = client.post("/api/v1/chat/sessions", headers=auth).json()
    client.post(
        "/api/v1/auth/register",
        json={"email": "b@b.com", "username": "bob", "password": "password123"},
    )
    token = client.post(
        "/api/v1/auth/login", data={"username": "bob", "password": "password123"}
    ).json()["access_token"]
    bob = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/chat/sessions", headers=bob).json() == []
    assert client.get(f"/api/v1/chat/sessions/{chat['id']}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/chat/sessions/{chat['id']}", headers=bob).status_code == 404


def test_rename_and_delete(client: TestClient, auth: dict[str, str]) -> None:
    chat = client.post("/api/v1/chat/sessions", headers=auth).json()
    url = f"/api/v1/chat/sessions/{chat['id']}"
    assert client.patch(url, headers=auth, json={"title": "Фэнтези"}).json()["title"] == "Фэнтези"
    assert client.delete(url, headers=auth).status_code == 204
    assert client.get(url, headers=auth).status_code == 404


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/chat/sessions").status_code == 401
