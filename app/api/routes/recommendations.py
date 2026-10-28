from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.books import Limit, Offset
from app.models import Book, Recommendation, RecommendationItem
from app.schemas.recommendation import (
    RecommendationIn,
    RecommendationItemOut,
    RecommendationOut,
    RecommendationPage,
)
from app.services.books import store_url, to_list_items
from app.services.recommender import KeywordRecommender, RecommendationRequest, Recommender

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

MAX_FILE_BYTES = 100_000
MAX_QUERY_CHARS = 2000


def get_recommender(db: DbSession) -> Recommender:
    return KeywordRecommender(db)


RecommenderDep = Annotated[Recommender, Depends(get_recommender)]


def to_out(db: DbSession, user: CurrentUser, recommendation: Recommendation) -> RecommendationOut:
    books = {
        b.id: b
        for b in db.scalars(
            select(Book).where(Book.id.in_([i.book_id for i in recommendation.items]))
        )
    }
    ordered = [books[i.book_id] for i in recommendation.items]
    list_items = to_list_items(db, user, ordered)
    return RecommendationOut(
        id=recommendation.id,
        query=recommendation.query,
        source=recommendation.source,
        created_at=recommendation.created_at,
        items=[
            RecommendationItemOut(book=list_item, reason=item.reason, store_url=store_url(book))
            for list_item, item, book in zip(list_items, recommendation.items, ordered, strict=True)
        ],
    )


def create(
    db: DbSession, user: CurrentUser, recommender: Recommender, text: str, source: str
) -> RecommendationOut:
    found = recommender.recommend(RecommendationRequest(text=text, user_id=user.id))
    recommendation = Recommendation(user_id=user.id, query=text, source=source)
    recommendation.items = [
        RecommendationItem(book_id=r.book_id, position=i, reason=r.reason)
        for i, r in enumerate(found)
    ]
    db.add(recommendation)
    db.commit()
    return to_out(db, user, recommendation)


@router.post("", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
def recommend_from_text(
    data: RecommendationIn, user: CurrentUser, db: DbSession, recommender: RecommenderDep
) -> RecommendationOut:
    return create(db, user, recommender, data.query, "text")


@router.post("/file", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
def recommend_from_file(
    file: UploadFile, user: CurrentUser, db: DbSession, recommender: RecommenderDep
) -> RecommendationOut:
    """Plain-text file (e.g. a list of favorite books). Audio is handled by the AI service later."""
    raw = file.file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large")
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only UTF-8 text files"
        ) from exc
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is empty")
    return create(db, user, recommender, text[:MAX_QUERY_CHARS], "file")


@router.get("", response_model=RecommendationPage)
def list_history(
    user: CurrentUser, db: DbSession, offset: Offset = 0, limit: Limit = 20
) -> RecommendationPage:
    owned = Recommendation.user_id == user.id
    total = db.scalar(select(func.count()).select_from(Recommendation).where(owned)) or 0
    history = db.scalars(
        select(Recommendation)
        .where(owned)
        .order_by(Recommendation.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return RecommendationPage(
        items=[to_out(db, user, r) for r in history], total=total, offset=offset, limit=limit
    )


@router.get("/{recommendation_id}", response_model=RecommendationOut)
def read_recommendation(
    recommendation_id: int, user: CurrentUser, db: DbSession
) -> RecommendationOut:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None or recommendation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")
    return to_out(db, user, recommendation)
