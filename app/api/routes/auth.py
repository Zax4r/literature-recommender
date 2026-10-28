from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.user import Token, UserCreate, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserMe, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: DbSession) -> User:
    taken = db.scalar(
        select(User).where((User.email == data.email.lower()) | (User.username == data.username))
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already taken")
    user = User(
        email=data.email.lower(),
        username=data.username,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """Log in by email or username (sent in the OAuth2 `username` field)."""
    login = form.username
    user = db.scalar(select(User).where((User.email == login.lower()) | (User.username == login)))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect login or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
