from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_PATTERN = r"^[a-zA-Z0-9_]+$"
AVATAR_PREFIXES = ("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")
AVATAR_MAX_LENGTH = 300_000


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=1000)
    avatar: str | None = Field(default=None, max_length=AVATAR_MAX_LENGTH)

    @field_validator("avatar")
    @classmethod
    def avatar_is_image(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(AVATAR_PREFIXES):
            raise ValueError("Аватар должен быть изображением JPEG, PNG или WebP")
        return value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    display_name: str | None
    bio: str | None
    avatar: str | None
    created_at: datetime


class UserMe(UserPublic):
    id: int
    email: EmailStr
    is_admin: bool


class UserStats(BaseModel):
    read: int
    reading: int
    dropped: int
    planned: int
    favorites: int
    rated: int
    average_rating: float | None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
