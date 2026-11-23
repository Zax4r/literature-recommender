from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.books import Limit, Offset
from app.models import Book, Favorite, User, UserBook
from app.schemas.book import BookPage, Status
from app.schemas.user import UserMe, UserPublic, UserStats, UserUpdate
from app.services.books import to_list_items

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


@router.get("/me/stats", response_model=UserStats)
def read_my_stats(user: CurrentUser, db: DbSession) -> UserStats:
    """How many books the user has in each status, plus favorites and the average rating."""
    by_status = {
        status: count
        for status, count in db.execute(
            select(UserBook.status, func.count())
            .where(UserBook.user_id == user.id)
            .group_by(UserBook.status)
        )
    }
    rated, average = db.execute(
        select(func.count(UserBook.rating), func.avg(UserBook.rating)).where(
            UserBook.user_id == user.id
        )
    ).one()
    favorites = db.scalar(
        select(func.count()).select_from(Favorite).where(Favorite.user_id == user.id)
    )
    return UserStats(
        read=by_status.get("read", 0),
        reading=by_status.get("reading", 0),
        dropped=by_status.get("dropped", 0),
        planned=by_status.get("planned", 0),
        favorites=favorites or 0,
        rated=rated,
        average_rating=round(float(average), 1) if average is not None else None,
    )


@router.get("/me/favorites", response_model=BookPage)
def read_my_favorites(
    user: CurrentUser, db: DbSession, offset: Offset = 0, limit: Limit = 20
) -> BookPage:
    owned = Favorite.user_id == user.id
    total = db.scalar(select(func.count()).select_from(Favorite).where(owned)) or 0
    books = list(
        db.scalars(
            select(Book)
            .join(Favorite, Favorite.book_id == Book.id)
            .where(owned)
            .order_by(Book.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return BookPage(items=to_list_items(db, user, books), total=total, offset=offset, limit=limit)


@router.get("/me/library", response_model=BookPage)
def read_my_library(
    user: CurrentUser,
    db: DbSession,
    status: Status | None = None,
    offset: Offset = 0,
    limit: Limit = 20,
) -> BookPage:
    conditions = [UserBook.user_id == user.id]
    if status is not None:
        conditions.append(UserBook.status == status)
    total = db.scalar(select(func.count()).select_from(UserBook).where(*conditions)) or 0
    books = list(
        db.scalars(
            select(Book)
            .join(UserBook, UserBook.book_id == Book.id)
            .where(*conditions)
            .order_by(UserBook.updated_at.desc(), Book.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return BookPage(items=to_list_items(db, user, books), total=total, offset=offset, limit=limit)


@router.get("/{username}", response_model=UserPublic)
def read_user(username: str, db: DbSession) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user
