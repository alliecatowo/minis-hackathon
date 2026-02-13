import logging

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_session
from app.models.user import User

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def _validate_service_jwt(token: str) -> str | None:
    """Validate a service JWT issued by the BFF proxy.

    Returns the user ID (sub claim) if valid, None otherwise.
    """
    secrets = [settings.service_jwt_secret]
    if settings.jwt_secret_previous:
        secrets.append(settings.jwt_secret_previous)

    for secret in secrets:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[ALGORITHM],
                options={"require_sub": True, "require_iat": True, "require_exp": True},
            )
            if payload.get("iss") != "minis-bff":
                continue
            return payload.get("sub")
        except JWTError:
            continue
    return None


async def _get_user_from_token(token: str | None, session: AsyncSession) -> User | None:
    if token is None:
        return None

    user_id = _validate_service_jwt(token)
    if user_id is None:
        return None

    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    from fastapi import HTTPException, status

    user = await _get_user_from_token(token, session)
    if user is None:
        logging.getLogger(__name__).warning(
            "Auth failed: token=%s",
            "present" if token else "missing",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    return await _get_user_from_token(token, session)
