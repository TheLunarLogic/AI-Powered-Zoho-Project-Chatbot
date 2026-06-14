"""OAuth authentication endpoints."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config, get_config
from app.database import get_db
from app.models.db import Session as SessionModel
from app.services.oauth_service import ZohoOAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    service = ZohoOAuthService(config=config, db=db)
    auth_url = await service.build_authorization_url(state=state)

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        max_age=300,
        secure=False,
    )
    logger.info("Redirecting user to Zoho OAuth consent page")
    return response


@router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    config: Config = Depends(get_config),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not code:
        logger.warning("OAuth callback missing code parameter")
        return RedirectResponse(url=f"{config.frontend_url}/login?error=missing_code", status_code=302)

    if not state or not oauth_state or not secrets.compare_digest(state, oauth_state):
        logger.warning("OAuth callback state mismatch — possible CSRF attempt")
        response = RedirectResponse(url=f"{config.frontend_url}/login?error=csrf", status_code=302)
        response.delete_cookie("oauth_state")
        return response

    try:
        service = ZohoOAuthService(config=config, db=db)

        token_set = await service.exchange_code_for_tokens(code=code)
        user_info = await service.get_user_info(access_token=token_set.access_token)
        user = await service.upsert_user(info=user_info)
        await service.store_tokens(user_id=user.id, token_set=token_set)

        session_token = secrets.token_urlsafe(64)
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=config.session_ttl_hours)

        session = SessionModel(
            id=uuid4(),
            user_id=user.id,
            session_token=session_token,
            last_active_at=now,
            expires_at=expires_at,
            is_active=True,
        )
        db.add(session)
        await db.commit()

        logger.info("OAuth callback completed — session created")

        # Redirect to the frontend chat page.
        # The request arrives via the Next.js proxy (localhost:3000/auth/callback
        # → localhost:8000/auth/callback), so the cookie is set on localhost:3000
        # and will be sent by the browser on all subsequent /api/* requests.
        response = RedirectResponse(url=f"{config.frontend_url}/chat", status_code=302)
        response.set_cookie(
            key=config.session_cookie_name,
            value=session_token,
            httponly=True,
            samesite="lax",
            path="/",
            secure=False,
        )
        response.delete_cookie("oauth_state")
        return response

    except Exception:
        logger.exception("OAuth callback failed unexpectedly")
        await db.rollback()
        response = RedirectResponse(url=f"{config.frontend_url}/login?error=auth_failed", status_code=302)
        response.delete_cookie("oauth_state")
        return response
