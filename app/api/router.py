from fastapi import APIRouter

from app.api.routes import auth, books, chat_sessions, library, recommendations, tags, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(books.router)
api_router.include_router(chat_sessions.router)
api_router.include_router(tags.router)
api_router.include_router(library.router)
api_router.include_router(recommendations.router)
