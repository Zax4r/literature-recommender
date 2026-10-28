import argparse
import asyncio
import logging

logger = logging.getLogger("pipeline")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Пайплайн предобработки книг")
    parser.add_argument("--limit", type=int, default=None,
                        help="Обработать только первые N книг (для проверки)")
    parser.add_argument("--only-generate", action="store_true",
                        help="Только LLM-генерация карточек, без загрузки в БД")
    parser.add_argument("--skip-generate", action="store_true",
                        help="Не генерировать, использовать существующий books.json")
    parser.add_argument("--skip-postgres", action="store_true",
                        help="Не загружать в Postgres")
    parser.add_argument("--skip-qdrant", action="store_true",
                        help="Не загружать в Qdrant")
    parser.add_argument("--recreate-qdrant", action="store_true",
                        help="Пересоздать коллекцию Qdrant перед загрузкой "
                             "(гибридный индекс dense+sparse BM25)")
    parser.add_argument("--resume", action="store_true",
                        help="Продолжить генерацию с последней обработанной книги")
    parser.add_argument("--validate", action="store_true",
                        help="Проверить books.json против CSV и показать проблемы")
    parser.add_argument("--repair", action="store_true",
                        help="Починить books.json: перераскладка + перегенерация битых карточек")
    return parser.parse_args()


async def validate_repair(do_repair: bool) -> None:
    """Проверяет books.json против CSV и, при do_repair=True, чинит проблемы."""
    from scripts.ai_generators.metadata_generator import (
        load_generated_books,
        read_books_csv,
        validate_books,
        repair_books,
    )

    cards = load_generated_books()
    entries = read_books_csv()

    if do_repair:
        from scripts.config import OUTPUT_JSON_FILE
        import json

        rearranged, regenerated = await repair_books(cards, entries)
        logger.info("Ремонт завершён: перераскладок=%d, перегенерировано=%d", rearranged, regenerated)
        OUTPUT_JSON_FILE.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("books.json обновлён (%d записей)", len(cards))

    stats, problems = validate_books(cards, entries)
    logger.info("Валидация: всего=%d, ок=%d (%.1f%%)", stats["total"], stats["ok"],
                stats["ok"] / stats["total"] * 100 if stats["total"] else 0)
    logger.info("  пустых: %d | author: %d | title: %d",
                stats["empty"], stats["author"], stats["title"])
    for p in problems[:20]:
        if p["kind"] == "empty":
            logger.warning("  пусто idx=%d (%s)", p["idx"], p["title"])
        elif p["kind"] == "author":
            logger.warning("  author idx=%d (%s): csv='%s' | card='%s'",
                           p["idx"], p["title"], p["csv"], p["card"])
        else:
            logger.warning("  title idx=%d: csv='%s' | card='%s'",
                           p["idx"], p["csv"], p["card"])
    if len(problems) > 20:
        logger.info("  ... и ещё %d проблем (см. сводку выше)", len(problems) - 20)


async def load_books_to_postgres(books: list[dict]) -> None:
    from scripts.loaders.init_postgres import load_books_to_postgres as f
    n = await f(books)
    logger.info("Postgres: upsert %d карточек", n)


async def load_books_to_qdrant(books: list[dict], recreate: bool = False) -> None:
    from scripts.loaders.init_qdrant import load_books_to_qdrant as f
    n = await f(books, recreate=recreate)
    logger.info("Qdrant: upsert %d точек", n)


async def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    if args.validate or args.repair:
        await validate_repair(args.repair)
        return

    if args.skip_generate:
        from scripts.ai_generators.metadata_generator import load_generated_books

        books = load_generated_books()
    else:
        from scripts.ai_generators.metadata_generator import run_metadata

        books = await run_metadata(resume=args.resume, limit=args.limit)

    filled = [b for b in books if b is not None]
    logger.info("Готово: %d карточек из %d книг", len(filled), len(books))

    if args.only_generate:
        return

    if not args.skip_postgres:
        await load_books_to_postgres(books)
    if not args.skip_qdrant:
        await load_books_to_qdrant(books, recreate=args.recreate_qdrant)


if __name__ == "__main__":
    asyncio.run(main())
