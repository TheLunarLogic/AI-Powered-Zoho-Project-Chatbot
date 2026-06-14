"""FastAPI dependency injection providers."""

import logging
from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db import Session as SessionModel
from app.models.db import User

logger = logging.getLogger(__name__)


async def get_current_user(
    zpc_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate the session cookie and return the authenticated User.

    Raises HTTP 401 if the cookie is missing, the session does not exist,
    the session is inactive, or the session has expired.  Updates
    ``last_active_at`` on every successful validation.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not zpc_session:
        raise credentials_exception

    result = await db.execute(
        select(SessionModel)
        .join(User, SessionModel.user_id == User.id)
        .where(SessionModel.session_token == zpc_session)
        .where(SessionModel.is_active.is_(True))
    )
    session: SessionModel | None = result.scalar_one_or_none()

    if session is None:
        raise credentials_exception

    now = datetime.now(UTC)
    # Make expires_at timezone-aware for comparison if it isn't already
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        from datetime import timezone
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        logger.info("Expired session rejected")
        raise credentials_exception

    # Update last_active_at without loading the full object
    await db.execute(
        update(SessionModel)
        .where(SessionModel.id == session.id)
        .values(last_active_at=now)
    )
    await db.commit()

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user: User | None = user_result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user
