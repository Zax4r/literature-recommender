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


@dataclass(frozen=True)
class BookRecord:
    goodreads_id: str
    title: str
    description: str
    image_url: str | None
    url: str | None
    author_ids: tuple[str, ...] = ()


def clean_description(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


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
