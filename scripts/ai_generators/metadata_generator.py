import asyncio
import json
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI

from scripts.config import (
    INPUT_CSV_FILE,
    OUTPUT_JSON_FILE,
    BATCH_SIZE,
    CONCURRENCY,
    METADATA_MODEL,
    API_DELAY_SECONDS,
    OPENROUTER_API_KEY,
)

logger = logging.getLogger("metadata_generator")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    timeout=120.0,  # чтобы зависший запрос не вис вечно, а уходил в ретраи
    max_retries=2,  # встроенные ретраи SDK на 429/5xx
)

PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "metadata_generator_prompt.txt"
REQUIRED_FIELDS = {"title", "author", "description", "genres", "tropes"}
MAX_RETRIES = 3

_TITLE_STOPWORDS = {"the", "a", "an"}

# Суффиксы изданий/маркеты CSV, которые модель справедливо убирает из названий
_EDITION_RE = re.compile(
    r"(\([^)]*\)|\[[^\]]*\]|\b(tie[- ]?in|l\.?p\.?|rack|rpk?g|hb|ji|gift|edition"
    r"|anniversary|signature|60th)\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- нормализация

def _norm_title(s: str) -> str:
    """Нормализация названия для сравнения: регистр, пунктуация, артикли."""
    s = (s or "").strip().lower()
    s = re.sub(r"[«»\"'’‘.,:;()\[\]!?—–-]", " ", s)
    words = [w for w in s.split() if w and w not in _TITLE_STOPWORDS]
    return " ".join(words)


def _title_clean_ok(card_title: str, csv_title: str) -> bool:
    """True, если название карточки — 'очищенная' версия CSV-названия (без мусора изданий)."""
    a = _EDITION_RE.sub(" ", _norm_title(csv_title))
    b = _EDITION_RE.sub(" ", _norm_title(card_title))
    return a == b or a in b or b in a


def _norm_author(s: str) -> str:
    """Нормализация автора: разделители, титулы, регистр."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s*;\s*", ";", s)  # "A; B" -> "A;B"
    s = s.replace("&", ";")         # "A & B" -> "A;B"
    s = re.sub(r"lecturer in philosophy\s*", "", s)
    s = re.sub(r"\b(dr|prof|mr|mrs|ms|sir|saint)\.?\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace(" ", "").replace(";", " ")  # игнорируем пробелы как разделители


def _author_clean_ok(card_author: str, csv_author: str) -> bool:
    """True, если автор карточки — 'улучшенная' версия CSV-автора (модель почистила мусор).

    Считаем приемлемым, когда авторы карточки являются подмножеством авторов CSV.
    """
    card_set = {a for a in _norm_author(card_author).split() if a}
    csv_set = {a for a in _norm_author(csv_author).split() if a}
    return card_set <= csv_set


def align_cards(entries: list[dict], cards: list[dict]) -> list[dict | None]:
    """Раскладывает карточки LLM по правильным слотам вместо позиционного zip.

    LLM иногда возвращает книги батча в другом порядке — сопоставляем по ключу
    (название + автор), затем по одному названию.
    entries: [{title, author, display}]; возвращает список длиной len(entries).
    """
    result: list[dict | None] = [None] * len(entries)
    used_cards: set[int] = set()
    avail = set(range(len(entries)))

    # 1) точный ключ (название, автор)
    for card in cards:
        k = (_norm_title(card.get("title", "")), _norm_author(card.get("author", "")))
        for i in list(avail):
            e = entries[i]
            if (_norm_title(e["title"]), _norm_author(e["author"])) == k:
                result[i] = card
                avail.remove(i)
                used_cards.add(id(card))
                break

    # 2) только по названию
    for card in cards:
        if id(card) in used_cards:
            continue
        for i in list(avail):
            if _norm_title(card.get("title", "")) == _norm_title(entries[i]["title"]):
                result[i] = card
                avail.remove(i)
                used_cards.add(id(card))
                break

    # 3) остатки — по порядку (последний шанс)
    for card in cards:
        if id(card) in used_cards or not avail:
            continue
        i = min(avail)
        result[i] = card
        avail.remove(i)
        used_cards.add(id(card))

    return result


# ---------------------------------------------------------------- чтение CSV

def read_books_csv(path: Path = INPUT_CSV_FILE, limit: int | None = None) -> list[dict]:
    """Читает books.csv в структурированные записи [{title, author, display}]."""
    import csv

    books: list[dict] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            authors = (row.get("authors") or "").strip()
            if not title:
                continue
            books.append(
                {
                    "title": title,
                    "author": authors,
                    "display": f"{authors} - {title}" if authors else title,
                }
            )
            if limit is not None and len(books) >= limit:
                break
    return books


def load_existing_results() -> dict[int, dict]:
    """Возвращает {index: карточка} из сохранённого books.json (для resume)."""
    if not OUTPUT_JSON_FILE.exists():
        return {}
    try:
        data = json.loads(OUTPUT_JSON_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("books.json повреждён — начинаю с нуля")
        return {}
    if isinstance(data, list):
        return {i: c for i, c in enumerate(data) if isinstance(c, dict)}
    return {}


# ---------------------------------------------------------------- генерация

def _extract_cards(content: str | None) -> list[dict]:
    """Разбирает ответ LLM в список валидных карточек."""
    if not content or not content.strip():
        raise ValueError("Пустой ответ от LLM")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # LLM иногда оборачивает JSON в ```json ... ``` — вырезаем первую { .. последнюю }
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])

    if isinstance(parsed, dict) and "books" in parsed:
        books = parsed["books"]
    elif isinstance(parsed, list):
        books = parsed
    elif isinstance(parsed, dict):
        books = next((v for v in parsed.values() if isinstance(v, list)), None)
    else:
        books = None

    if not isinstance(books, list):
        raise ValueError("В ответе LLM не найден список книг")

    cards = [b for b in books if isinstance(b, dict) and REQUIRED_FIELDS.issubset(b)]
    if not cards:
        raise ValueError("Ни одна карточка не прошла валидацию по обязательным полям")
    return cards


async def generate_batch_metadata(books_chunk: list[str]) -> list[dict]:
    """Запрашивает у LLM карточки для одного батча книг, с ретраями."""
    data = {
        "num_chunks": len(books_chunk),
        "books_list": json.dumps(books_chunk, ensure_ascii=False),
    }
    prompt = PROMPT_FILE.read_text(encoding="utf-8").format(**data)

    for attempt in range(1, MAX_RETRIES + 1):
        kwargs: dict = {
            "model": METADATA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }
        # response_format намеренно НЕ передаём: на ряде провайдеров он вызывает
        # пустой ответ или зависшее соединение. Промпт и так требует строгий JSON,
        # а _extract_cards умеет вытаскивать JSON даже из ```json-обёртки.
        try:
            response = await client.chat.completions.create(**kwargs)
            return _extract_cards(response.choices[0].message.content)
        except Exception as e:
            logger.warning(
                "Попытка %d/%d для батча не удалась: %s", attempt, MAX_RETRIES, e
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(API_DELAY_SECONDS * (2 ** (attempt - 1)))

    raise RuntimeError(f"Батч не сгенерирован после {MAX_RETRIES} попыток")


# ---------------------------------------------------------------- валидация и ремонт

def validate_books(cards: list[dict | None], entries: list[dict]) -> tuple[dict, list[dict]]:
    """Сверяет карточки против CSV. Возвращает (статистика, список проблем)."""
    problems: list[dict] = []
    for i, (card, e) in enumerate(zip(cards, entries)):
        if card is None:
            problems.append({"idx": i, "kind": "empty", "title": e["title"]})
            continue
        if _norm_author(card["author"]) != _norm_author(e["author"]):
            if _author_clean_ok(card["author"], e["author"]):
                continue  # модель просто почистила авторов — это ок
            problems.append(
                {"idx": i, "kind": "author", "title": e["title"],
                 "csv": e["author"], "card": card["author"]}
            )
        elif _norm_title(card["title"]) != _norm_title(e["title"]):
            if _title_clean_ok(card["title"], e["title"]):
                continue  # модель убрала мусор изданий из названия — это ок
            problems.append(
                {"idx": i, "kind": "title", "csv": e["title"], "card": card["title"]}
            )

    stats = {
        "total": len(cards),
        "ok": len(cards) - len(problems),
        "empty": sum(1 for p in problems if p["kind"] == "empty"),
        "author": sum(1 for p in problems if p["kind"] == "author"),
        "title": sum(1 for p in problems if p["kind"] == "title"),
    }
    return stats, problems


async def repair_books(cards: list[dict | None], entries: list[dict]) -> tuple[int, int]:
    """Чинит books.json: перераскладка по ключам + перегенерация проблемных слотов.

    Возвращает (перераскладок, перегенерировано).
    """
    total = min(len(cards), len(entries))
    rearranged = 0

    # 1) перераскладка по батчам — чинит 'повёрнутые' батчи без обращения к LLM
    for start in range(0, total, BATCH_SIZE):
        stop = min(start + BATCH_SIZE, total)
        batch_cards = cards[start:stop]
        if all(c is None for c in batch_cards):
            continue
        aligned = align_cards(entries[start:stop], batch_cards)
        for off, card in enumerate(aligned):
            if card is not None and cards[start + off] is not card:
                cards[start + off] = card
                rearranged += 1

    # 2) слоты, оставшиеся без корректного автора или пустые — перегенерируем
    to_fix = [
        i for i in range(total)
        if cards[i] is None
        or (
            _norm_author(cards[i]["author"]) != _norm_author(entries[i]["author"])
            and not _author_clean_ok(cards[i]["author"], entries[i]["author"])
        )
    ]
    regenerated = 0
    for start in range(0, len(to_fix), BATCH_SIZE):
        chunk = to_fix[start : start + BATCH_SIZE]
        chunk_entries = [entries[i] for i in chunk]
        aligned: list[dict | None] = []
        for _ in range(3):
            new_cards = await generate_batch_metadata([e["display"] for e in chunk_entries])
            aligned = align_cards(chunk_entries, new_cards)
            if sum(1 for c in aligned if c is not None) >= len(chunk):
                break
            await asyncio.sleep(API_DELAY_SECONDS)
        for off, card in enumerate(aligned):
            if card is not None:
                cards[chunk[off]] = card
                regenerated += 1

    return rearranged, regenerated


# ---------------------------------------------------------------- пайплайн генерации

async def run_metadata(resume: bool = True, limit: int | None = None) -> list[dict]:
    """Весь этап генерации: CSV -> LLM -> books.json, батчи обрабатываются параллельно."""
    books = read_books_csv(limit=limit)
    total = len(books)
    logger.info("Всего книг: %d", total)

    results = load_existing_results() if resume else {}
    if results:
        skipped = sum(1 for i in range(total) if i in results)
        logger.info("Resume: уже обработано %d/%d", skipped, total)

    # индексы батчей, которые ещё не обработаны
    pending: list[list[int]] = []
    for start in range(0, total, BATCH_SIZE):
        indices = list(range(start, min(start + BATCH_SIZE, total)))
        if not all(i in results for i in indices):
            pending.append(indices)

    num_batches = len(pending)
    done_batches = 0
    sem = asyncio.Semaphore(CONCURRENCY)

    def save_checkpoint() -> None:
        ordered = [results.get(i) for i in range(total)]
        OUTPUT_JSON_FILE.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def worker(indices: list[int]) -> None:
        nonlocal done_batches
        async with sem:
            try:
                entries = [books[i] for i in indices]
                display = [e["display"] for e in entries]
                aligned: list[dict | None] = []
                for _ in range(3):  # свободные модели иногда теряют/переставляют книги
                    cards = await generate_batch_metadata(display)
                    aligned = align_cards(entries, cards)
                    matched = sum(1 for c in aligned if c is not None)
                    if matched >= len(indices):
                        break
                    logger.warning(
                        "Батч сопоставлен лишь на %d/%d — повторяю", matched, len(indices)
                    )
                    await asyncio.sleep(API_DELAY_SECONDS)
                for offset, card in enumerate(aligned):
                    if card is not None:
                        results[indices[offset]] = card
            except Exception as e:
                logger.error("Батч %s провалился: %s (пропуски добьёт --resume)", indices, e)
            finally:
                done_batches += 1
                save_checkpoint()  # чекпойнт после каждого завершённого батча
                logger.info(
                    "Обработано батчей %d/%d, заполнено %d/%d",
                    done_batches, num_batches, len(results), total,
                )

    await asyncio.gather(*(worker(indices) for indices in pending))

    return [results.get(i) for i in range(total)]


def load_generated_books() -> list[dict]:
    """Просто читает готовый books.json (для --skip-generate)."""
    if not OUTPUT_JSON_FILE.exists():
        raise FileNotFoundError(f"Нет {OUTPUT_JSON_FILE} — сначала запусти генерацию")
    return json.loads(OUTPUT_JSON_FILE.read_text(encoding="utf-8"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_metadata())


if __name__ == "__main__":
    main()