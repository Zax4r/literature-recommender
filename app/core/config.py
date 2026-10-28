from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Инфраструктура ---
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/literature"
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # --- Аккаунты ---
    SECRET_KEY: str = "dev-only-secret-change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    STORE_SEARCH_URL: str = "https://oz.by/search/?q={query}"

    # --- LLM (OpenRouter; модели настраиваются через env) ---
    OPENROUTER_API_KEY: str = ""
    # ling-3.1-flash был очень медленным на реальных промптах (10-18с+ на вызов);
    # gpt-4o-mini ~2-3с и стабильно отдаёт JSON. Переопределяется через env.
    ROUTER_MODEL: str = "openai/gpt-4o-mini"
    EXTRACTOR_MODEL: str = "openai/gpt-4o-mini"
    FORMATTER_MODEL: str = "openai/gpt-4o-mini"
    # Модель для web-поиска через OpenRouter Responses API (plugins: web)
    SHOP_SEARCH_WEB_MODEL: str = "openai/gpt-4o-mini"
    # Фолбэк для web-поиска: модель с суффиксом :online (chat completions)
    SHOP_SEARCH_ONLINE_MODEL: str = "openai/gpt-4o-mini:online"
    # false: без платного web-поиска, ссылки-шаблоны на поиск в магазинах
    SHOP_SEARCH_ENABLED: bool = True
    LLM_TIMEOUT_SECONDS: float = 60.0
    # <- retry только по явным ошибкам провайдера (429/5xx), не по зависаниям
    LLM_MAX_RETRIES: int = 2

    # --- Скорость / таймауты этапов чата ---
    AGENT_TIMEOUT_SECONDS: float = 15.0  # роутер/экстрактор/форматер
    SEARCH_TIMEOUT_SECONDS: float = 20.0  # эмбеддинг + гибридный поиск
    SHOP_MAX_BOOKS: int = 3  # столько книг ищутся в магазинах (web-поиск дорогой)
    SHOP_SEARCH_MAX_RESULTS: int = 3
    SHOP_TIMEOUT_SECONDS: float = 15.0

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


settings = Settings()

# Стабильные ссылки-шаблоны на страницы поиска магазинов (фолбэк, если
# web-поиск недоступен). {q} заменяется на URL-encoded «название автор».
BOOK_SHOP_SEARCH_TEMPLATES: dict[str, str] = {
    "OZ.by": "https://www.oz.by/search/?q={q}",
    "Ozon.by": "https://www.ozon.by/search/?text={q}",
    "Литрес": "https://www.litres.ru/pages/biblio_search/?q={q}",
    "Лабиринт": "https://www.labirint.ru/search/{q}/",
}
