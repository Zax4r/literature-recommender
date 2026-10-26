from pydantic import BaseModel


class BookListItem(BaseModel):
    id: int
    title: str
    authors: list[str]
    image_url: str | None
    is_favorite: bool


class BookDetail(BookListItem):
    description: str
    url: str | None


class BookPage(BaseModel):
    items: list[BookListItem]
    total: int
    offset: int
    limit: int


class ImportResult(BaseModel):
    imported: int
    skipped: int
