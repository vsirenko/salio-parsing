"""User and session schemas.

One entity for both audiences; `role` decides which panel the account may sign in to.
`UserInDB` never leaves the service layer — routes return `UserRead`, which has no
password hash on it by construction.

The sign-in bodies live here too: they are this feature's wire format. The token
vocabulary they are built from — `Audience`, `TokenType`, `TokenPayload` — belongs to
`app/core/security.py`, which mints and verifies the tokens.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    # Machine accounts. They sign in like anyone else and reach a different set of routes,
    # because the audience decides that and not the role.
    WORKER = "worker"


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


class UserUpdate(BaseModel):
    """Admin-side edit. Every field is optional; only what is sent is applied.

    `full_name` may be sent as null to clear it. `role` and `is_active` have no
    meaningful null, so a null there is treated as "not sent" rather than rejected
    field-by-field. There is no password here — changing one is its own endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserInDB(UserRead):
    """Internal representation — carries the hash, so it must never be a response_model."""

    password_hash: str
    token_epoch: int


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class PasswordChange(BaseModel):
    """Changing your own password. Proving the current one is what makes it yours."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordReset(BaseModel):
    """An administrator setting another account's password: a colleague who lost theirs, or a
    collector's machine account. No current password — the caller is not the owner, and the
    admin token is what authorises it."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
