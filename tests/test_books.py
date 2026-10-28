from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Book, BookTag, Tag
from app.services.tag_sync import sync_book_tags


def test_feed_pagination(client: TestClient, imported: None) -> None:
    page = client.get("/api/v1/books?offset=20&limit=10").json()
    assert (page["total"], page["offset"], page["limit"]) == (25, 20, 10)
    assert [b["title"] for b in page["items"]] == [f"Book {i}" for i in range(21, 26)]
    assert page["items"][0]["author"] == "Author 0"
    assert client.get("/api/v1/books?limit=0").status_code == 422
    assert client.get("/api/v1/books?limit=101").status_code == 422
    assert client.get("/api/v1/books?offset=-1").status_code == 422


def test_book_detail(client: TestClient, imported: None) -> None:
    book = client.get("/api/v1/books/1").json()
    assert book["title"] == "Book 1"
    assert len(book["description"]) == 250
    assert book["genres"] == ["Фэнтези", "Жанр 1"]
    assert book["tropes"] == ["Найденная семья", "Поиск пути, или судьба"]
    assert book["is_favorite"] is False and book["status"] is None
    assert book["store_url"].startswith("https://oz.by/search/?q=Book+1+Author+1")
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


def test_sync_tags_creates_votable_tags_and_is_idempotent(
    imported: None, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        # genres: "Фэнтези" + 3 "Жанр N"; tropes: 2 shared ones
        assert session.scalar(select(func.count()).select_from(Tag)) == 6
        assert session.scalar(select(func.count()).select_from(BookTag)) == 25 * 4
        assert sync_book_tags(session) == (0, 0)
        first = session.scalar(select(Book).order_by(Book.id))
        assert first is not None
        weights = dict(
            session.execute(
                select(Tag.name, BookTag.weight)
                .join(BookTag, BookTag.tag_id == Tag.id)
                .where(BookTag.book_id == first.id)
            ).all()
        )
        assert weights["фэнтези"] > weights["жанр 1"] > weights["найденная семья"]
