# Интеллектуальная система подбора литературы

Курсовой проект. Пользователь описывает, какую книгу хочет (**текстом, голосом через Whisper или файлом**) — и получает подборку похожих книг с объяснением и ссылками на покупку в магазинах Беларуси. У пользователя есть профиль, личная библиотека (прочитал / читаю / брошено / в планах, оценки, избранное), теги книг можно предлагать и оценивать голосованием.

Репозиторий объединяет две части:

| Часть | Что делает |
|---|---|
| **Бэкенд** (FastAPI + PostgreSQL) | Аккаунты (JWT), каталог (импорт UCSD Book Graph), избранное, библиотека с оценками, теги с голосованием, сохранение рекомендаций, история запросов, минимальный веб-интерфейс |
| **AI-сервис чата** | Агенты рекомендаций (роутер → экстрактор → гибридный поиск в Qdrant → поиск по магазинам → форматтер), локальное распознавание речи (faster-whisper), защита от prompt injection. Эндпоинт `POST /api/v1/chat` |

## Что умеет бэкенд

| Область | Возможности |
|---|---|
| Аккаунты | Регистрация, вход по email или логину (JWT), профиль (имя, о себе), публичный профиль |
| Каталог | Импорт книг из датасета UCSD Book Graph (только админ), лента с `offset`/`limit`, карточка книги |
| Избранное | Добавить и убрать книгу, список избранного с пагинацией |
| Библиотека | Статус (`read`, `reading`, `dropped`, `planned`), оценка 1–5, фильтр по статусу |
| Теги | Теги из полок датасета, свои теги, голосование «за»/«против», рейтинг тега |
| Рекомендации | Сохранение результатов чата, причина для каждой книги, ссылка на магазин |
| Веб-интерфейс | Страница на `/`: вход, лента, избранное, библиотека, теги, рекомендации |

## Архитектура AI-чата

```
вход (текст | whisper | файл)
  -> Router (классификация намерения + риск инъекции)
  -> Extractor (жанры / тропы / исключения)
  -> Hybrid search (dense e5 + sparse BM25, RRF) в Qdrant
  -> Book-shop agent (web-поиск: oz.by, ozon.by, litres, ... + фолбэк-шаблоны)
  -> Formatter (текстовый ответ + карточки)
```

Защита от prompt injection (PI) и косвенной инъекции (IDPI): пользовательский контент
оборачивается как «недоверенные данные» (`app/services/ai/guard.py`), промпты фиксированы
в `prompts/`, эвристический пре-фильтр помечает попытки манипуляции, агенты возвращают
только валидный JSON с проверкой полей, «магазинный» и «форматтер» агенты не видят
сырой ввод пользователя.

## Быстрый старт

### Бэкенд и веб-интерфейс (uv)

Нужны Docker и [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # впишите свой SECRET_KEY
docker compose up --build
```

- Веб-интерфейс: http://localhost:8000/
- Swagger: http://localhost:8000/docs
- Миграции применяются автоматически при старте контейнера.
- Войдите как `admin` / `admin` и нажмите «Импорт 100 книг» (~3 секунды).

> **Админ `admin` / `admin` создаётся миграцией и нужен только для разработки.** Перед
> реальным запуском смените пароль и `SECRET_KEY`.

Локально без Docker:

```bash
uv sync
docker run -d --name lit-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=literature -p 5432:5432 postgres:17
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### AI-чат (пайплайн + эмбеддинги)

```bash
pip install -r requirements.txt
docker compose up -d db qdrant redis            # Postgres, Qdrant, Redis
python -m scripts.run_pipeline --skip-generate --skip-postgres --recreate-qdrant   # гибридный индекс dense+sparse
QDRANT_HOST=127.0.0.1 uvicorn app.main:app --reload --port 8000
```

Whisper скачивает модель `small` при первом использовании.

## Эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/v1/chat` | Чат. multipart/form-data: `message`, `file`, `history`; заголовок `X-User-Id` |
| POST | `/api/v1/chat/transcribe` | Отладка: только whisper (`file` = аудио) |
| POST | `/api/v1/auth/*` | Регистрация/вход (бэкенд) |
| GET/POST | `/api/v1/books`, `/api/v1/tags`, `/api/v1/library`, `/api/v1/recommendations` | Каталог, теги, библиотека, рекомендации |

## Конфигурация

- Бэкенд: `.env` → `app/core/config.py`, см. `.env.example`.
- AI-чат: корневой `config.py` (модели OpenRouter, `QDRANT_COLLECTION`, `WHISPER_MODEL`,
  `BOOK_SHOP_WHITELIST`, `MAX_UPLOAD_MB` и др.; все с дефолтами).
- Пользователь чата передаётся заголовком `X-User-Id` (аутентификацию делает бэкенд).
  `app/services/ai/context.py::get_filtered_book_ids` — место, где бэкенд исключает книги
  пользователя из рекомендаций.

## Проверки (бэкенд)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest                  # SQLite в памяти, сеть не нужна
```

Новая миграция: `uv run alembic revision --autogenerate -m "описание"`.
