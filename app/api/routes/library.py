from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.models import UserBook
from app.schemas.book import EntryIn
from app.services.books import get_book_or_404

router = APIRouter(prefix="/books/{book_id}/entry", tags=["library"])


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
def set_entry(book_id: int, data: EntryIn, user: CurrentUser, db: DbSession) -> Response:
    """Puts the book on the user's shelf (read/reading/dropped/planned) with an optional rating."""
    get_book_or_404(db, book_id)
    entry = db.get(UserBook, (user.id, book_id))
    if entry is None:
        db.add(UserBook(user_id=user.id, book_id=book_id, status=data.status, rating=data.rating))
    else:
        entry.status = data.status
        entry.rating = data.rating
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_entry(book_id: int, user: CurrentUser, db: DbSession) -> Response:
    entry = db.get(UserBook, (user.id, book_id))
    if entry is not None:
        db.delete(entry)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
