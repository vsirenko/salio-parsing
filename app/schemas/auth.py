"""Authentication schemas."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Audience(StrEnum):
    """JWT `aud`. A token minted for one panel is rejected by the other."""

    CLIENT = "client"
    ADMIN = "admin"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


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


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class TokenPayload(BaseModel):
    """Decoded and already-validated JWT claims."""

    sub: int
    aud: Audience
    type: TokenType
    # Checked against the account's current epoch, so a password change can end the
    # sessions that were opened before it.
    epoch: int
