import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_session
from app.models.user import RefreshToken, User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)


async def create_refresh_token(user_id: str, session: AsyncSession) -> str:
    raw_token = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    refresh = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh)
    await session.flush()
    return raw_token


async def refresh_access_token(
    refresh_token: str, session: AsyncSession
) -> tuple[str, str]:
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    stored = result.scalar_one_or_none()

    if stored is None:
        raise ValueError("Invalid or expired refresh token")

    # Revoke old token (rotation)
    stored.revoked = True

    # Create new tokens
    new_access = create_access_token({"sub": str(stored.user_id)})
    new_refresh = await create_refresh_token(stored.user_id, session)

    await session.commit()
    return new_access, new_refresh


async def revoke_user_tokens(user_id: str, session: AsyncSession) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
        .values(revoked=True)
    )
    await session.commit()


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

    user_id: str | None = None

    # Try service JWT first (issued by BFF proxy)
    service_user_id = _validate_service_jwt(token)
    if service_user_id is not None:
        user_id = service_user_id
    else:
        # Fall back to legacy access token
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
            if payload.get("type") != "access":
                # Try previous secret for rotation
                if settings.jwt_secret_previous:
                    try:
                        payload = jwt.decode(
                            token, settings.jwt_secret_previous, algorithms=[ALGORITHM]
                        )
                        if payload.get("type") != "access":
                            return None
                    except JWTError:
                        return None
                else:
                    return None
            user_id = payload.get("sub")
        except JWTError:
            # Try previous secret for rotation
            if settings.jwt_secret_previous:
                try:
                    payload = jwt.decode(
                        token, settings.jwt_secret_previous, algorithms=[ALGORITHM]
                    )
                    if payload.get("type") != "access":
                        return None
                    user_id = payload.get("sub")
                except JWTError:
                    return None
            else:
                return None

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
