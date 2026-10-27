from fastapi.testclient import TestClient

USER = {"email": "Reader@Example.com", "username": "reader", "password": "supersecret"}


def register(client: TestClient) -> None:
    assert client.post("/api/v1/auth/register", json=USER).status_code == 201


def login(client: TestClient, password: str = USER["password"]) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", data={"username": "reader@example.com", "password": password}
    )
    if response.status_code != 200:
        return {}
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_register_returns_user_without_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=USER)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "reader@example.com"
    assert "password" not in body and "hashed_password" not in body


def test_register_duplicate_is_conflict(client: TestClient) -> None:
    register(client)
    assert client.post("/api/v1/auth/register", json=USER).status_code == 409


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json={**USER, "password": "short"})
    assert response.status_code == 422


def test_login_wrong_password(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/auth/login", data={"username": "reader@example.com", "password": "wrongpass1"}
    )
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/users/me").status_code == 401
    assert (
        client.get("/api/v1/users/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    )


def test_profile_read_and_update(client: TestClient) -> None:
    register(client)
    headers = login(client)

    me = client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "reader"

    patched = client.patch(
        "/api/v1/users/me", headers=headers, json={"display_name": "Bookworm", "bio": "Fantasy fan"}
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Bookworm"

    public = client.get("/api/v1/users/reader")
    assert public.status_code == 200
    assert public.json()["bio"] == "Fantasy fan"
    assert "email" not in public.json()


def test_unknown_public_profile(client: TestClient) -> None:
    assert client.get("/api/v1/users/nobody").status_code == 404
