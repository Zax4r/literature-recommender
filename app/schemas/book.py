from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["read", "reading", "dropped", "planned"]


class TagOut(BaseModel):
    name: str
    score: int
    my_vote: int


class BookListItem(BaseModel):
    id: int
    title: str
    authors: list[str]
    image_url: str | None
    is_favorite: bool
    status: Status | None
    rating: int | None


class BookDetail(BookListItem):
    description: str
    url: str | None
    store_url: str
    tags: list[TagOut]


class BookPage(BaseModel):
    items: list[BookListItem]
    total: int
    offset: int
    limit: int


class ImportResult(BaseModel):
    imported: int
    skipped: int


class EntryIn(BaseModel):
    status: Status
    rating: int | None = Field(default=None, ge=1, le=5)


class VoteIn(BaseModel):
    value: Literal[-1, 1]


class TagIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
