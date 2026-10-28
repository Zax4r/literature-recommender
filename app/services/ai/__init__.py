"""Пакет AI-агентов и оркестратора чата."""

from pathlib import Path

# Корень репозитория; промпты лежат в PROJECT_ROOT / "prompts".
PROJECT_ROOT = Path(__file__).resolve().parents[3]

__all__ = ["PROJECT_ROOT"]
