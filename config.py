from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Инфраструктура (задаётся docker-compose / .env) ---
    DATABASE_URL: str
    QDRANT_HOST: str
    QDRANT_PORT: int
    REDIS_URL: str
    OPENROUTER_API_KEY: str
    SECRET_KEY: str

    # --- LLM (модели OpenRouter; все настраиваются через env) ---
    ROUTER_MODEL: str = "inclusionai/ling-3.1-flash"
    EXTRACTOR_MODEL: str = "inclusionai/ling-3.1-flash"
    FORMATTER_MODEL: str = "inclusionai/ling-3.1-flash"
    # Модель для web-поиска через OpenRouter Responses API (plugins: web)
    SHOP_SEARCH_WEB_MODEL: str = "openai/gpt-4o-mini"
    # Фолбэк для web-поиска — модель с суффиксом :online (chat completions)
    SHOP_SEARCH_ONLINE_MODEL: str = "openai/gpt-4o-mini:online"
    LLM_TIMEOUT_SECONDS: float = 60.0

    # --- Qdrant (гибридный поиск: dense + sparse BM25) ---
    QDRANT_COLLECTION: str = "books_collection"
    QDRANT_DENSE_NAME: str = "dense"
    QDRANT_SPARSE_NAME: str = "bm25"
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-base"
    SEARCH_PREFETCH_K: int = 40
    SEARCH_TOP_K: int = 6

    # --- Whisper (локальный faster-whisper) ---
    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # --- Ввод данных ---
    MAX_UPLOAD_MB: int = 25
    MAX_TEXT_CHARS: int = 20000

    # --- Гео и магазины (Беларусь) ---
    REGION: str = "by"
    # Разрешённые домены для ссылок на книги; задаётся JSON-списком в env при желании.
    BOOK_SHOP_WHITELIST: list[str] = [
        "oz.by",
        "ozon.by",
        "ozon.ru",
        "wildberries.by",
        "books.by",
        "labirint.ru",
        "book24.ru",
        "litres.by",
        "litres.ru",
        "mybook.ru",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Ссылки на страницы поиска магазинов (проверены вручную: открываются без логина).
# {q} заменяется на URL-encoded название книги.
BOOK_SHOP_SEARCH_TEMPLATES: dict[str, str] = {
    "OZ.by": "https://oz.by/search/?q={q}",
    "Литрес": "https://www.litres.ru/search/?q={q}",
    "Лабиринт": "https://www.labirint.ru/search/{q}/",
    "Goodreads": "https://www.goodreads.com/search?q={q}",
}
