from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.books import Limit, Offset, to_list_item, to_page
from app.models import Book, Favorite, User
from app.schemas.book import BookPage
from app.schemas.user import UserMe, UserPublic, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserMe)
def read_me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserMe)
def update_me(data: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.add(user)
    db.commit()
    return user


@router.get("/me/favorites", response_model=BookPage)
def read_my_favorites(
    user: CurrentUser, db: DbSession, offset: Offset = 0, limit: Limit = 20
) -> BookPage:
    owned = Favorite.user_id == user.id
    total = db.scalar(select(func.count()).select_from(Favorite).where(owned)) or 0
    books = db.scalars(
        select(Book)
        .join(Favorite, Favorite.book_id == Book.id)
        .where(owned)
        .order_by(Book.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return to_page([to_list_item(b, {b.id for b in books}) for b in books], total, offset, limit)


@router.get("/{username}", response_model=UserPublic)
def read_user(username: str, db: DbSession) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user
