from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.books import Limit, Offset
from app.models import Recommendation
from app.schemas.recommendation import RecommendationOut, RecommendationPage
from app.services.history import to_out

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationPage)
def list_history(
    user: CurrentUser, db: DbSession, offset: Offset = 0, limit: Limit = 20
) -> RecommendationPage:
    """History of the user's chat recommendations (new ones are created by POST /api/v1/chat)."""
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
