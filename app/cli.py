"""Maintenance commands: `python -m app.cli sync-tags`."""

import sys

from app.db.session import SessionLocal
from app.services.tag_sync import sync_book_tags


def main() -> int:
    if sys.argv[1:] != ["sync-tags"]:
        print("usage: python -m app.cli sync-tags", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        tags, links = sync_book_tags(db)
    print(f"sync-tags: {tags} new tags, {links} new book-tag links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
