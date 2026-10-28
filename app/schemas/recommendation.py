from datetime import datetime

from pydantic import BaseModel

from app.schemas.book import BookListItem


class StoreLink(BaseModel):
    name: str
    url: str
    kind: str


class RecommendationItemOut(BaseModel):
    book: BookListItem
    reason: str
    stores: list[StoreLink]


class RecommendationOut(BaseModel):
    id: int
    query: str
    source: str
    answer: str
    created_at: datetime
    items: list[RecommendationItemOut]


class RecommendationPage(BaseModel):
    items: list[RecommendationOut]
    total: int
    offset: int
    limit: int
