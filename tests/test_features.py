from fastapi.testclient import TestClient


def tag_scores(client: TestClient, headers: dict[str, str], book_id: int = 1) -> dict[str, int]:
    tags = client.get(f"/api/v1/books/{book_id}", headers=headers).json()["tags"]
    return {t["name"]: t["score"] for t in tags}


def test_book_has_imported_tags_and_store_link(client: TestClient, imported: None) -> None:
    book = client.get("/api/v1/books/1").json()
    assert {t["name"] for t in book["tags"]} == {"fantasy", "genre-1"}
    assert book["store_url"] == "https://oz.by/search/?q=Book+1+Author+1"


def test_tag_voting(client: TestClient, auth: dict[str, str], imported: None) -> None:
    base = "/api/v1/books/1/tags/fantasy/vote"
    assert client.put(base, headers=auth, json={"value": 1}).status_code == 200
    assert tag_scores(client, auth)["fantasy"] == 1
    tags = client.put(base, headers=auth, json={"value": -1}).json()
    assert {t["name"]: (t["score"], t["my_vote"]) for t in tags}["fantasy"] == (-1, -1)
    assert client.delete(base, headers=auth).status_code == 200
    assert tag_scores(client, auth)["fantasy"] == 0
    assert client.put(base, headers=auth, json={"value": 2}).status_code == 422
    assert client.put(base, json={"value": 1}).status_code == 401
    missing = "/api/v1/books/1/tags/nonexistent/vote"
    assert client.put(missing, headers=auth, json={"value": 1}).status_code == 404


def test_one_vote_per_user(client: TestClient, auth: dict[str, str], imported: None) -> None:
    for _ in range(3):
        client.put("/api/v1/books/1/tags/fantasy/vote", headers=auth, json={"value": 1})
    assert tag_scores(client, auth)["fantasy"] == 1


def test_suggest_tag(client: TestClient, auth: dict[str, str], imported: None) -> None:
    response = client.post("/api/v1/books/1/tags", headers=auth, json={"name": " Slow Burn "})
    assert response.status_code == 201
    assert {t["name"]: t["score"] for t in response.json()}["slow-burn"] == 1
    assert client.post("/api/v1/books/1/tags", headers=auth, json={"name": "a!"}).status_code == 422
    # suggesting an existing tag does not create a duplicate
    client.post("/api/v1/books/1/tags", headers=auth, json={"name": "slow-burn"})
    names = [t["name"] for t in client.get("/api/v1/books/1").json()["tags"]]
    assert names.count("slow-burn") == 1


def test_library_flow(client: TestClient, auth: dict[str, str], imported: None) -> None:
    entry = "/api/v1/books/4/entry"
    assert client.put(entry, headers=auth, json={"status": "read", "rating": 5}).status_code == 204
    assert (
        client.put("/api/v1/books/5/entry", headers=auth, json={"status": "planned"}).status_code
        == 204
    )
    assert client.put(entry, headers=auth, json={"status": "bad"}).status_code == 422
    assert client.put(entry, headers=auth, json={"status": "read", "rating": 6}).status_code == 422
    assert (
        client.put("/api/v1/books/999/entry", headers=auth, json={"status": "read"}).status_code
        == 404
    )
    assert client.put(entry, json={"status": "read"}).status_code == 401

    book = client.get("/api/v1/books/4", headers=auth).json()
    assert (book["status"], book["rating"]) == ("read", 5)

    library = client.get("/api/v1/users/me/library", headers=auth).json()
    assert library["total"] == 2
    only_read = client.get("/api/v1/users/me/library?status=read", headers=auth).json()
    assert [b["id"] for b in only_read["items"]] == [4]

    client.put(entry, headers=auth, json={"status": "dropped"})
    assert client.get("/api/v1/books/4", headers=auth).json()["rating"] is None
    assert client.delete(entry, headers=auth).status_code == 204
    assert client.get("/api/v1/users/me/library", headers=auth).json()["total"] == 1


def test_recommendations_match_tags_and_skip_read_books(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    client.put("/api/v1/books/1/entry", headers=auth, json={"status": "read", "rating": 4})
    response = client.post(
        "/api/v1/recommendations", headers=auth, json={"query": "want more fantasy"}
    )
    assert response.status_code == 201
    body = response.json()
    ids = [i["book"]["id"] for i in body["items"]]
    assert len(ids) == 5 and 1 not in ids
    assert "fantasy" in body["items"][0]["reason"]
    assert body["items"][0]["store_url"].startswith("https://oz.by/")

    history = client.get("/api/v1/recommendations", headers=auth).json()
    assert history["total"] == 1 and history["items"][0]["id"] == body["id"]
    assert client.get(f"/api/v1/recommendations/{body['id']}", headers=auth).status_code == 200


def test_recommendations_from_file(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    response = client.post(
        "/api/v1/recommendations/file",
        headers=auth,
        files={"file": ("books.txt", b"fantasy genre-2")},
    )
    assert response.status_code == 201 and response.json()["source"] == "file"
    binary = client.post(
        "/api/v1/recommendations/file", headers=auth, files={"file": ("x.bin", b"\xff\xfe\x00")}
    )
    assert binary.status_code == 415
    empty = client.post(
        "/api/v1/recommendations/file", headers=auth, files={"file": ("e.txt", b"  ")}
    )
    assert empty.status_code == 422


def test_recommendations_are_private(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    rec_id = client.post("/api/v1/recommendations", headers=auth, json={"query": "fantasy"}).json()[
        "id"
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
    assert client.post("/api/v1/recommendations", json={"query": "x"}).status_code == 401
