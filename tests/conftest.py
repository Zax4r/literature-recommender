from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User
from app.services import ucsd
from app.services.ucsd import BookRecord


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def fake_books(limit: int) -> Iterator[BookRecord]:
    for i in range(1, min(limit, 30) + 1):
        yield BookRecord(
            str(i),
            f"Book {i}",
            "x" * 400,
            None,
            f"https://example.com/{i}",
            (str(i % 3),),
            (("fantasy", 5), (f"genre-{i % 3}", 3)),
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
