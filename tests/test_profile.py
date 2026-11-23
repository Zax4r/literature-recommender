from fastapi.testclient import TestClient

PIXEL = "data:image/png;base64,iVBORw0KGgo="


def test_stats_count_books_by_status(
    client: TestClient, auth: dict[str, str], imported: None
) -> None:
    empty = client.get("/api/v1/users/me/stats", headers=auth).json()
    assert empty["read"] == 0 and empty["average_rating"] is None

    client.put("/api/v1/books/1/entry", headers=auth, json={"status": "read", "rating": 5})
    client.put("/api/v1/books/2/entry", headers=auth, json={"status": "read", "rating": 4})
    client.put("/api/v1/books/3/entry", headers=auth, json={"status": "planned"})
    client.put("/api/v1/books/3/favorite", headers=auth)

    stats = client.get("/api/v1/users/me/stats", headers=auth).json()
    assert stats == {
        "read": 2,
        "reading": 0,
        "dropped": 0,
        "planned": 1,
        "favorites": 1,
        "rated": 2,
        "average_rating": 4.5,
    }
    assert client.get("/api/v1/users/me/stats").status_code == 401


def test_avatar_can_be_set_and_cleared(client: TestClient, auth: dict[str, str]) -> None:
    me = client.patch("/api/v1/users/me", headers=auth, json={"avatar": PIXEL}).json()
    assert me["avatar"] == PIXEL
    assert client.get("/api/v1/users/alice").json()["avatar"] == PIXEL

    # Changing another field leaves the avatar alone; null removes it.
    me = client.patch("/api/v1/users/me", headers=auth, json={"bio": "hi"}).json()
    assert me["avatar"] == PIXEL
    me = client.patch("/api/v1/users/me", headers=auth, json={"avatar": None}).json()
    assert me["avatar"] is None


def test_avatar_must_be_a_small_image(client: TestClient, auth: dict[str, str]) -> None:
    not_image = client.patch("/api/v1/users/me", headers=auth, json={"avatar": "http://x/y.png"})
    assert not_image.status_code == 422
    too_big = "data:image/png;base64," + "A" * 300_000
    assert (
        client.patch("/api/v1/users/me", headers=auth, json={"avatar": too_big}).status_code == 422
    )
