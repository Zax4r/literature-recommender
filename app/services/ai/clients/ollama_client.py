from openai import AsyncOpenAI

embed_client = AsyncOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

DEFAULT_EMBED_MODEL = "embeddinggemma-2:latest"