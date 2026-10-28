from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["read", "reading", "dropped", "planned"]


class TagOut(BaseModel):
    id: int
    name: str
    score: int
    my_vote: int


class BookListItem(BaseModel):
    id: int
    title: str
    author: str
    is_favorite: bool
    status: Status | None
    rating: int | None


class BookDetail(BookListItem):
    description: str
    genres: list[str]
    tropes: list[str]
    store_url: str
    tags: list[TagOut]


class BookPage(BaseModel):
    items: list[BookListItem]
    total: int
    offset: int
    limit: int


class EntryIn(BaseModel):
    status: Status
    rating: int | None = Field(default=None, ge=1, le=5)


class VoteIn(BaseModel):
    value: Literal[-1, 1]


class TagIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
