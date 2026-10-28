import os
import re
from pathlib import Path

_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env_value(value: str, env: dict[str, str]) -> str:
    """Раскрывает ${NAME} в значении: сначала os.environ, затем ключи .env."""

    def repl(m: re.Match) -> str:
        name = m.group(1)
        return os.environ.get(name) or env.get(name, "")

    return _VAR_RE.sub(repl, value)

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent

DATA_DIR = SCRIPTS_DIR / "data"

RAW_LISTS_DIR = DATA_DIR / "1_raw_lists"
GENERATED_JSONS_DIR = DATA_DIR / "2_generated_jsons"

INPUT_CSV_FILE = RAW_LISTS_DIR / "books.csv"
OUTPUT_JSON_FILE = GENERATED_JSONS_DIR / "books.json"

BATCH_SIZE = 10

# Сколько батчей обрабатывать одновременно. Больше — быстрее, но выше шанс
# упереться в rate-limit OpenRouter (тогда ретраи сами разгладят).
CONCURRENCY = 6

# По просьбе: 0 задержки ради скорости (DeepSeek отвечает быстро).
# Если появятся ошибки 429 (rate limit) — вернуть 0,5–1.5.
API_DELAY_SECONDS = 0

COLLECTION_NAME = "books_collection"

VECTOR_SIZE = 768

# Модель для генерации карточек. Дешёвая DeepSeek V4 Flash 0731 (~$0.15 за весь объём).
# Можно переопределить через env METADATA_MODEL.
DEFAULT_METADATA_MODEL = "deepseek/deepseek-v4-flash-0731"


def _load_env() -> dict[str, str]:
    """Минимальный загрузчик .env без сторонних зависимостей.

    Читает переменные из корневого .env, чтобы не требовать pydantic-settings.
    Поддерживает интерполяцию ${VAR} (сначала os.environ, затем ключи .env).
    """
    env: dict[str, str] = {}
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return env
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    for key in list(env):
        env[key] = _expand_env_value(env[key], env)
    return env


_env = _load_env()

OPENROUTER_API_KEY = (
    os.environ.get("OPENROUTER_API_KEY", "") or _env.get("OPENROUTER_API_KEY", "")
)

METADATA_MODEL = (
    os.environ.get("METADATA_MODEL", "").strip()
    or _env.get("METADATA_MODEL", "").strip()
    or DEFAULT_METADATA_MODEL
)

RAW_LISTS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_JSONS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", "") or _env.get("DATABASE_URL", "")
QDRANT_HOST = os.environ.get("QDRANT_HOST", "") or _env.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "") or _env.get("QDRANT_PORT", "6333"))
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
