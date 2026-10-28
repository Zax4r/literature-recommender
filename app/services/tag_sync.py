from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import Book, BookTag, Tag
from app.services.books import normalize_tag_name


def sync_book_tags(db: Session) -> tuple[int, int]:
    """Turns every book's genres and tropes into votable tags. Idempotent.

    A tag's weight is its reversed position in the pipeline's list, so the original order is kept.
    Returns the number of new tags and new book-tag links.
    """
    tag_ids: dict[str, int] = {name: id_ for id_, name in db.execute(select(Tag.id, Tag.name))}
    wanted: list[tuple[int, str, int]] = []
    for book in db.scalars(select(Book)):
        names = [n for n in (*book.genres, *book.tropes) if n]
        for position, raw in enumerate(names):
            try:
                name = normalize_tag_name(raw)
            except Exception:  # noqa: BLE001 - skip names that cannot be tags
                continue
            wanted.append((book.id, name, len(names) - position))

    new_names = sorted({name for _, name, _ in wanted} - tag_ids.keys())
    for start in range(0, len(new_names), 5000):
        db.execute(insert(Tag), [{"name": n} for n in new_names[start : start + 5000]])
    db.flush()
    tag_ids = {name: id_ for id_, name in db.execute(select(Tag.id, Tag.name))}

    existing = {(b, t) for b, t in db.execute(select(BookTag.book_id, BookTag.tag_id))}
    rows: dict[tuple[int, int], int] = {}
    for book_id, name, weight in wanted:
        key = (book_id, tag_ids[name])
        if key not in existing:
            rows[key] = max(weight, rows.get(key, 0))
    links = [{"book_id": b, "tag_id": t, "weight": w} for (b, t), w in rows.items()]
    for start in range(0, len(links), 5000):
        db.execute(insert(BookTag), links[start : start + 5000])
    db.commit()
    return len(new_names), len(links)
