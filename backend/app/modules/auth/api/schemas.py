import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.auth.domain.credentials import normalize_username


class BootstrapRequest(BaseModel):
    username: str
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)


class LoginRequest(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    role: str
    must_change_password: bool


class AdminUserResponse(UserResponse):
    role_name: str
    is_active: bool
    created_at: datetime


class CreateUserRequest(BaseModel):
    username: str
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=128)
    role: str = Field(default="operador", pattern="^(principal|operador)$")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)


class BootstrapStatusResponse(BaseModel):
    required: bool
