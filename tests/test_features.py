from typing import Any

from fastapi.testclient import TestClient


def tags_of(
    client: TestClient, headers: dict[str, str] | None = None, book_id: int = 1
) -> dict[str, Any]:
    tags = client.get(f"/api/v1/books/{book_id}", headers=headers or {}).json()["tags"]
    return {t["name"]: t for t in tags}


def test_book_tags_come_from_genres_and_tropes(client: TestClient, imported: None) -> None:
    assert set(tags_of(client)) == {
        "фэнтези",
        "жанр 1",
        "найденная семья",
        "поиск пути, или судьба",
    }


def test_tag_voting(client: TestClient, auth: dict[str, str], imported: None) -> None:
    tag_id = tags_of(client)["фэнтези"]["id"]
    vote = f"/api/v1/books/1/tags/{tag_id}/vote"
    assert client.put(vote, headers=auth, json={"value": 1}).status_code == 200
    assert tags_of(client, auth)["фэнтези"]["score"] == 1
    tags = client.put(vote, headers=auth, json={"value": -1}).json()
    assert {t["name"]: (t["score"], t["my_vote"]) for t in tags}["фэнтези"] == (-1, -1)
    assert client.delete(vote, headers=auth).status_code == 200
    assert tags_of(client, auth)["фэнтези"]["score"] == 0
    assert client.put(vote, headers=auth, json={"value": 2}).status_code == 422
    assert client.put(vote, json={"value": 1}).status_code == 401
    missing = "/api/v1/books/1/tags/99999/vote"
    assert client.put(missing, headers=auth, json={"value": 1}).status_code == 404


def test_one_vote_per_user(client: TestClient, auth: dict[str, str], imported: None) -> None:
    tag_id = tags_of(client)["фэнтези"]["id"]
    for _ in range(3):
        client.put(f"/api/v1/books/1/tags/{tag_id}/vote", headers=auth, json={"value": 1})
    assert tags_of(client, auth)["фэнтези"]["score"] == 1


def test_suggest_tag(client: TestClient, auth: dict[str, str], imported: None) -> None:
    response = client.post(
        "/api/v1/books/1/tags", headers=auth, json={"name": "  Медленное  Горение "}
    )
    assert response.status_code == 201
    assert {t["name"]: t["score"] for t in response.json()}["медленное горение"] == 1
    assert client.post("/api/v1/books/1/tags", headers=auth, json={"name": "a"}).status_code == 422
    client.post("/api/v1/books/1/tags", headers=auth, json={"name": "медленное горение"})
    names = [t["name"] for t in client.get("/api/v1/books/1").json()["tags"]]
    assert names.count("медленное горение") == 1


def test_library_flow(client: TestClient, auth: dict[str, str], imported: None) -> None:
    entry = "/api/v1/books/4/entry"
    assert client.put(entry, headers=auth, json={"status": "read", "rating": 5}).status_code == 204
    planned = client.put("/api/v1/books/5/entry", headers=auth, json={"status": "planned"})
    assert planned.status_code == 204
    assert client.put(entry, headers=auth, json={"status": "bad"}).status_code == 422
    assert client.put(entry, headers=auth, json={"status": "read", "rating": 6}).status_code == 422
    missing = client.put("/api/v1/books/999/entry", headers=auth, json={"status": "read"})
    assert missing.status_code == 404
    assert client.put(entry, json={"status": "read"}).status_code == 401

    book = client.get("/api/v1/books/4", headers=auth).json()
    assert (book["status"], book["rating"]) == ("read", 5)

    assert client.get("/api/v1/users/me/library", headers=auth).json()["total"] == 2
    only_read = client.get("/api/v1/users/me/library?status=read", headers=auth).json()
    assert [b["id"] for b in only_read["items"]] == [4]

    client.put(entry, headers=auth, json={"status": "dropped"})
    assert client.get("/api/v1/books/4", headers=auth).json()["rating"] is None
    assert client.delete(entry, headers=auth).status_code == 204
    assert client.get("/api/v1/users/me/library", headers=auth).json()["total"] == 1
