from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.models import BookTag, Tag, TagVote
from app.schemas.book import TagIn, TagOut, VoteIn
from app.services.books import book_tags, get_book_or_404, normalize_tag_name

router = APIRouter(prefix="/books/{book_id}/tags", tags=["tags"])


def get_book_tag_or_404(db: Session, book_id: int, tag_id: int) -> BookTag:
    book_tag = db.get(BookTag, (book_id, tag_id))
    if book_tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found on this book")
    return book_tag


def set_vote(db: Session, user_id: int, book_tag: BookTag, value: int) -> None:
    vote = db.get(TagVote, (user_id, book_tag.book_id, book_tag.tag_id))
    if vote is None:
        db.add(
            TagVote(user_id=user_id, book_id=book_tag.book_id, tag_id=book_tag.tag_id, value=value)
        )
    else:
        vote.value = value


@router.post("", response_model=list[TagOut], status_code=status.HTTP_201_CREATED)
def suggest_tag(book_id: int, data: TagIn, user: CurrentUser, db: DbSession) -> list[TagOut]:
    """Adds a tag to the book (or finds the existing one) and upvotes it."""
    get_book_or_404(db, book_id)
    name = normalize_tag_name(data.name)
    tag = db.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    book_tag = db.get(BookTag, (book_id, tag.id))
    if book_tag is None:
        book_tag = BookTag(book_id=book_id, tag_id=tag.id)
        db.add(book_tag)
        db.flush()
    set_vote(db, user.id, book_tag, 1)
    db.commit()
    return book_tags(db, book_id, user)


@router.put("/{tag_id}/vote", response_model=list[TagOut])
def vote_tag(
    book_id: int, tag_id: int, data: VoteIn, user: CurrentUser, db: DbSession
) -> list[TagOut]:
    book_tag = get_book_tag_or_404(db, book_id, tag_id)
    set_vote(db, user.id, book_tag, data.value)
    db.commit()
    return book_tags(db, book_id, user)


@router.delete("/{tag_id}/vote", response_model=list[TagOut])
def remove_vote(book_id: int, tag_id: int, user: CurrentUser, db: DbSession) -> list[TagOut]:
    book_tag = get_book_tag_or_404(db, book_id, tag_id)
    vote = db.get(TagVote, (user.id, book_id, book_tag.tag_id))
    if vote is not None:
        db.delete(vote)
        db.commit()
    return book_tags(db, book_id, user)
