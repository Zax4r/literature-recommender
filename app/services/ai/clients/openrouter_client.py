"""Совместимость: клиент OpenRouter переехал в app.services.ai.clients.llm."""

from app.services.ai.clients.llm import DEFAULT_CHAT_MODEL, llm_client

__all__ = ["llm_client", "DEFAULT_CHAT_MODEL"]
