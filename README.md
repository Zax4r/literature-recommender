# literature-recommender

Интеллектуальная система подбора литературы: пользователь описывает, какую книгу
хочет (текстом, голосом через whisper или файлом), а агенты находят похожие книги
(гибридный поиск в Qdrant) и ссылки на покупку в магазинах Беларуси.

## Архитектура

```
вход (текст | whisper | файл)
  -> Router (классификация намерения + риск инъекции)
  -> Extractor (жанры / тропы / исключения)
  -> Hybrid search (dense e5 + sparse BM25, RRF) в Qdrant
  -> Book-shop agent (web-поиск: oz.by, ozon.by, litres, ... фолбэк-шаблоны)
  -> Formatter (текстовый ответ + карточки)
```

Защита от prompt injection (PI) и косвенной инъекции (IDPI): пользовательский
контент всегда оборачивается как «недоверенные данные» (`app/services/ai/guard.py`),
системные промпты фиксированы в `prompts/`, эвристический пре-фильтр помечает
попытки манипуляции, агенты возвращают только валидный JSON с проверкой полей,
а «магазинный» и «форматтер» агенты не видят сырой ввод пользователя.

## Быстрый старт

Зависимости добавляют `faster-whisper`, `pypdf`, `python-docx`, `fastapi` и т.д.:
```bash
pip install -r requirements.txt
```

Инфраструктура (Postgres, Qdrant, Redis):
```bash
docker compose up -d db qdrant redis
```

Перед первым запуском чата коллекцию Qdrant нужно пересоздать под гибридный
индекс (dense + sparse BM25). Данные и кэш эмбеддингов уже есть, поэтому шаг быстрый;
сам загрузчик `init_qdrant` также делает это автоматически при следующем прогоне
пайплайна:
```bash
python -m scripts.run_pipeline --skip-generate --skip-postgres --recreate-qdrant
```

Запуск API (без UI):
```bash
uvicorn app.main:app --reload --port 8000
# Swagger: http://localhost:8000/docs
```

Всё сразу в docker:
```bash
docker compose up --build api
```

## Эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/v1/chat` | Основной чат. multipart/form-data: `message`, `file`, `history`, заголовок `X-User-Id` |
| POST | `/api/v1/chat/transcribe` | Отладка: только whisper (`file` = аудио) |
| GET | `/api/v1/chat/health` | Проверка |
| GET | `/health` | Проверка приложения |

Пример:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "message=Что-то похожее на Дюну, тёмная политика и выживание"
```

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -F "file=@книга.txt" -F "message=хочу что-то похожее"
```

Ответ:
```json
{
  "intent": "recommend",
  "answer": "…",
  "recommendations": [
    {
      "source_idx": 42, "title": "…", "author": "…",
      "genres": ["…"], "tropes": ["…"], "description": "…",
      "score": 0.83,
      "stores": [{"name": "OZ.by", "url": "https://www.oz.by/…", "kind": "paper"}]
    }
  ],
  "matched": {"genres": ["…"], "tropes": ["…"], "exclude": []},
  "input": {"text": "…", "source": "chat", "has_file": false}
}
```

## Конфигурация (env, все с дефолтами)

`ROUTER_MODEL`, `EXTRACTOR_MODEL`, `FORMATTER_MODEL`, `SHOP_SEARCH_WEB_MODEL`,
`SHOP_SEARCH_ONLINE_MODEL`, `WHISPER_MODEL` (`small`), `WHISPER_DEVICE`,
`WHISPER_COMPUTE_TYPE`, `QDRANT_COLLECTION`, `EMBEDDING_MODEL`,
`BOOK_SHOP_WHITELIST` (JSON-список доменов), `MAX_UPLOAD_MB`, `MAX_TEXT_CHARS`.
Регион и магазины-фолбэки — константы в `config.py`.

## Контракт с владельцем бэкенда

- Пользователь передаётся заголовком `X-User-Id` (чат не аутентифицирует).
- `app/services/ai/context.py::get_filtered_book_ids` — место, где бэкенд вернёт
  книги из списков пользователя (сейчас заглушка, рекомендации не фильтруются).
- Книги в рекомендациях идентифицируются через `source_idx` (индекс в books.json).
