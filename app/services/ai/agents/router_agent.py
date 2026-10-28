"""Агент-роутер: классифицирует намерение и уровень риска запроса."""

import logging

from app.core.config import settings
from app.services.ai import PROJECT_ROOT
from app.services.ai.clients.llm import chat_completion
from app.services.ai.guard import parse_json_llm, run_prefilter, wrap_untrusted

logger = logging.getLogger("router")

ROUTER_PROMPT = (PROJECT_ROOT / "prompts" / "router_prompt.txt").read_text(encoding="utf-8")

VALID_INTENTS = {"recommend", "follow_up", "clarify", "refuse", "unsafe"}


async def route_request(
    user_text: str,
    *,
    has_history: bool = False,
) -> dict:
    """Возвращает решение: intent, risk, user_summary (и служебные поля)."""
    risky, hits = run_prefilter(user_text)

    content = (
        "Результаты автоматической проверки на манипуляции: "
        f"{', '.join(hits) if hits else 'подозрение не обнаружено'}.\n\n"
        + wrap_untrusted(user_text, "сообщение пользователя")
    )
    if has_history:
        content += "\n\n[Примечание: в диалоге уже есть история; запрос короткий.]"

    try:
        raw = await chat_completion(
            settings.ROUTER_MODEL, ROUTER_PROMPT, content, json_mode=True, temperature=0.1
        )
        parsed = parse_json_llm(raw) or {}
    except Exception as exc:
        logger.warning("Router call failed (%s); использую дефолтную ветку", exc)
        parsed = {}

    intent = str(parsed.get("intent", "")).strip().lower()
    if intent not in VALID_INTENTS:
        # Если роутер недоступен, не блокируем книжный запрос: уходим в recommend
        # (префильтр всё равно пометит явные инъекции).
        intent = "unsafe" if risky else "recommend"
    if risky and intent in {"recommend", "follow_up"}:
        intent = "unsafe"

    return {
        "intent": intent,
        "risk": parsed.get("risk", "high" if risky else "low"),
        "has_text_fragment": bool(parsed.get("has_text_fragment", False)),
        "user_summary": str(parsed.get("user_summary", "") or "").strip()[:500],
        "reason": str(parsed.get("reason", "") or "").strip()[:300],
        "matched_prefilter": hits,
    }
