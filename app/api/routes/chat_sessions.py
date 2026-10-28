"""Сохранённые сессии чата: список, история, удаление и отправка сообщения потоком (SSE)."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageOut,
    ChatSessionDetail,
    ChatSessionOut,
    ChatSessionRename,
)
from app.services.ai import orchestrator
from app.services.files import uploader

logger = logging.getLogger("chat_sessions")

router = APIRouter(prefix="/chat/sessions", tags=["chat"])

DEFAULT_TITLE = "Новый чат"
TITLE_CHARS = 60
HISTORY_LIMIT = 20


def get_owned_session(db: DbSession, user: CurrentUser, session_id: int) -> ChatSession:
    chat = db.get(ChatSession, session_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    return chat


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("", response_model=list[ChatSessionOut])
def list_sessions(user: CurrentUser, db: DbSession) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
    )


@router.post("", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
def create_session(user: CurrentUser, db: DbSession) -> ChatSession:
    chat = ChatSession(user_id=user.id, title=DEFAULT_TITLE)
    db.add(chat)
    db.commit()
    return chat


@router.get("/{session_id}", response_model=ChatSessionDetail)
def read_session(session_id: int, user: CurrentUser, db: DbSession) -> ChatSession:
    return get_owned_session(db, user, session_id)


@router.patch("/{session_id}", response_model=ChatSessionOut)
def rename_session(
    session_id: int, data: ChatSessionRename, user: CurrentUser, db: DbSession
) -> ChatSession:
    chat = get_owned_session(db, user, session_id)
    chat.title = data.title.strip()
    db.commit()
    return chat


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, user: CurrentUser, db: DbSession) -> Response:
    db.delete(get_owned_session(db, user, session_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/messages")
async def send_message(
    session_id: int,
    user: CurrentUser,
    db: DbSession,
    message: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    """Сохраняет вопрос, запускает AI-конвейер и стримит этапы и итоговый ответ.

    События: `user` (сохранённый вопрос), `stage` (этап конвейера), `message`
    (сохранённый ответ ассистента), `error`.
    """
    chat = get_owned_session(db, user, session_id)
    text, untrusted, source = await uploader.process_chat_input(message=message, file=file)

    history = [{"role": m.role, "content": m.content} for m in chat.messages[-HISTORY_LIMIT:]]
    shown = text or f"[файл: {file.filename if file else ''}]"
    user_msg = ChatMessage(session_id=chat.id, role="user", content=shown)
    db.add(user_msg)
    if chat.title == DEFAULT_TITLE:
        chat.title = shown[:TITLE_CHARS]
    db.commit()

    async def events() -> AsyncIterator[str]:
        yield sse("user", ChatMessageOut.model_validate(user_msg).model_dump(mode="json"))

        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def work() -> None:
            try:
                result = await orchestrator.run_chat(
                    user_text=text,
                    untrusted_text=untrusted,
                    source=source,
                    user_id=str(user.id),
                    history=history,
                    on_stage=lambda name: queue.put_nowait(("stage", name)),
                )
                queue.put_nowait(("result", result))
            except Exception as exc:  # noqa: BLE001
                logger.exception("chat pipeline failed")
                queue.put_nowait(("error", str(exc)))

        task = asyncio.create_task(work())
        try:
            while True:
                kind, data = await queue.get()
                if kind == "stage":
                    yield sse("stage", data)
                    continue
                if kind == "error":
                    yield sse("error", "Не удалось получить ответ. Попробуйте ещё раз.")
                    return
                assert isinstance(data, dict)
                reply = ChatMessage(
                    session_id=chat.id,
                    role="assistant",
                    content=data["answer"],
                    payload={
                        "intent": data.get("intent"),
                        "recommendations": data.get("recommendations", []),
                        "matched": data.get("matched"),
                    },
                )
                db.add(reply)
                db.commit()
                yield sse("message", ChatMessageOut.model_validate(reply).model_dump(mode="json"))
                return
        finally:
            task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
