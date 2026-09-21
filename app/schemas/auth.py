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
