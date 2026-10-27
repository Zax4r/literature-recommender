"""Reads books from the UCSD Book Graph (Goodreads), licensed for academic use only.

The dumps are gzipped JSON-lines files (books ~2 GB, authors ~18 MB); we stream them and
stop as soon as we have enough records.
"""

import gzip
import html
import json
import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from urllib.request import Request, urlopen

BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads"
BOOKS_URL = f"{BASE_URL}/goodreads_books.json.gz"
AUTHORS_URL = f"{BASE_URL}/goodreads_book_authors.json.gz"
TIMEOUT_SECONDS = 30


# Shelves that describe the reader's state or edition rather than the book itself.
NON_TOPIC_SHELVES = frozenset(
    {
        "to-read", "currently-reading", "read", "owned", "favorites", "favourites", "favorite",
        "books-i-own", "default", "library", "audiobook", "audiobooks", "audio", "audio-books",
        "e-book", "ebook", "ebooks", "kindle", "wish-list", "wishlist", "to-buy", "own",
        "owned-books", "my-books", "my-library", "dnf", "did-not-finish", "abandoned", "re-read",
        "reread", "book-club", "bookclub", "paperback", "hardcover", "have", "owned-but-unread",
    }
)  # fmt: skip
SHELF_NAME_PATTERN = re.compile(r"^[a-z]+(-[a-z]+)*$")
READER_STATE_PATTERN = re.compile(r"favou?rite|owned|shelf|library")
MAX_SHELVES = 10
MIN_SHELF_COUNT = 2


@dataclass(frozen=True)
class BookRecord:
    goodreads_id: str
    title: str
    description: str
    image_url: str | None
    url: str | None
    author_ids: tuple[str, ...] = ()
    shelves: tuple[tuple[str, int], ...] = ()


def clean_description(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def topic_shelves(popular_shelves: list[dict[str, str]]) -> tuple[tuple[str, int], ...]:
    """Keeps the most popular shelves that look like topics (genres, tropes, themes)."""
    shelves = [
        (s["name"], int(s["count"]))
        for s in popular_shelves
        if s["name"] not in NON_TOPIC_SHELVES
        and len(s["name"]) <= 40
        and SHELF_NAME_PATTERN.match(s["name"])
        and not READER_STATE_PATTERN.search(s["name"])
        and int(s["count"]) >= MIN_SHELF_COUNT
    ]
    shelves.sort(key=lambda s: s[1], reverse=True)
    return tuple(shelves[:MAX_SHELVES])


def parse_record(line: bytes) -> BookRecord | None:
    """Returns None for records that are unusable (no title or description)."""
    data = json.loads(line)
    title = (data.get("title") or "").strip()
    description = clean_description(data.get("description") or "")
    if not (data.get("book_id") and title and description):
        return None
    return BookRecord(
        goodreads_id=str(data["book_id"]),
        title=title,
        description=description,
        image_url=data.get("image_url") or None,
        url=data.get("url") or None,
        author_ids=tuple(str(a["author_id"]) for a in data.get("authors") or []),
        shelves=topic_shelves(data.get("popular_shelves") or []),
    )


def _stream_lines(url: str) -> Iterator[bytes]:
    request = Request(url, headers={"User-Agent": "literature-recommender-coursework"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response, gzip.open(response) as lines:
        yield from lines


def fetch_books(limit: int, url: str = BOOKS_URL) -> Iterator[BookRecord]:
    found = 0
    for line in _stream_lines(url):
        if found >= limit:
            return
        record = parse_record(line)
        if record is not None:
            found += 1
            yield record


def fetch_author_names(author_ids: Collection[str], url: str = AUTHORS_URL) -> dict[str, str]:
    """Maps author id to name, reading the authors dump until all ids are found."""
    wanted = set(author_ids)
    names: dict[str, str] = {}
    if not wanted:
        return names
    for line in _stream_lines(url):
        data = json.loads(line)
        author_id = str(data["author_id"])
        if author_id in wanted:
            names[author_id] = data["name"]
            if len(names) == len(wanted):
                break
    return names
