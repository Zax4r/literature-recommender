from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.book import BookListItem


class RecommendationIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class RecommendationItemOut(BaseModel):
    book: BookListItem
    reason: str
    store_url: str


class RecommendationOut(BaseModel):
    id: int
    query: str
    source: str
    created_at: datetime
    items: list[RecommendationItemOut]


class RecommendationPage(BaseModel):
    items: list[RecommendationOut]
    total: int
    offset: int
    limit: int
