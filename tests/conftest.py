from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Book
from app.services.tag_sync import sync_book_tags

BOOK_COUNT = 25


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
def imported(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """A small catalog shaped like the pipeline's output: book i has source_idx i - 1."""
    with session_factory() as session:
        session.add_all(
            Book(
                source_idx=i - 1,
                title=f"Book {i}",
                author=f"Author {i % 3}",
                description="x" * 400,
                genres=["Фэнтези", f"Жанр {i % 3}"],
                tropes=["Найденная семья", "Поиск пути, или судьба"],
            )
            for i in range(1, BOOK_COUNT + 1)
        )
        session.commit()
        sync_book_tags(session)
