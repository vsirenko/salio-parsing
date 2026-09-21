"""User schemas.

One entity for both audiences; `role` decides which panel the account may sign in to.
`UserInDB` never leaves the service layer — routes return `UserRead`, which has no
password hash on it by construction.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserCreate(UserBase):
    """Admin-side creation. There is no public registration endpoint."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.CUSTOMER
    is_active: bool = True


class UserRead(UserBase):
    id: int
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserInDB(UserRead):
    """Internal representation — carries the hash, so it must never be a response_model."""

    password_hash: str
