"""Password hashing and JWT minting/verification.

Two independent guarantees live here:
- `aud` scopes a token to one panel, so a client token cannot be replayed against
  the admin API even if a role check is forgotten somewhere;
- `type` separates access from refresh, so a long-lived refresh token cannot be
  used as an access token.
"""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.exceptions import AppError
from app.schemas.auth import Audience, TokenPayload, TokenType

_password_hash = PasswordHash.recommended()  # argon2


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Invalid credentials"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Not enough permissions"


def hash_password(raw_password: str) -> str:
    return _password_hash.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return _password_hash.verify(raw_password, password_hash)


def _create_token(
    *, user_id: int, audience: Audience, token_type: TokenType, lifetime: timedelta
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "aud": audience.value,
        "type": token_type.value,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, audience: Audience) -> str:
    return _create_token(
        user_id=user_id,
        audience=audience,
        token_type=TokenType.ACCESS,
        lifetime=timedelta(minutes=settings.access_token_ttl_minutes),
    )


def create_refresh_token(user_id: int, audience: Audience) -> str:
    return _create_token(
        user_id=user_id,
        audience=audience,
        token_type=TokenType.REFRESH,
        lifetime=timedelta(days=settings.refresh_token_ttl_days),
    )


def decode_token(
    token: str, *, expected_audience: Audience, expected_type: TokenType
) -> TokenPayload:
    """Decode and validate a token, or raise AuthError."""
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=expected_audience.value,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired", code="token_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("Token was issued for a different audience") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid token") from exc

    if claims.get("type") != expected_type.value:
        raise AuthError(f"Expected a {expected_type.value} token")

    return TokenPayload(sub=int(claims["sub"]), aud=claims["aud"], type=claims["type"])
