"""Zoho OAuth service."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.models.db import OAuthToken, User
from app.models.schemas import TokenSet, ZohoUserInfo
from app.services.crypto import encrypt

logger = logging.getLogger(__name__)

# OAuth scopes required for Zoho Projects + Zoho Accounts user profile
_SCOPES = (
    "AaaServer.profile.READ "
    "ZohoProjects.portals.READ "
    "ZohoProjects.projects.READ "
    "ZohoProjects.tasks.READ "
    "ZohoProjects.tasks.CREATE "
    "ZohoProjects.tasks.UPDATE "
    "ZohoProjects.tasks.DELETE "
    "ZohoProjects.users.READ"
)

_HTTP_TIMEOUT = 30.0  # seconds


class ZohoOAuthService:
    """Handles all Zoho OAuth operations: authorization URL building,
    token exchange, user info retrieval, and persistent storage."""

    def __init__(self, config: Config, db: AsyncSession) -> None:
        self._config = config
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_authorization_url(self, state: str) -> str:
        """Build the Zoho OAuth authorization URL.

        access_type=offline requests a refresh token.
        prompt=consent forces Zoho to re-issue a refresh token on every consent,
        which is required after the first authorization — Zoho only returns a
        refresh token on the initial consent unless prompt=consent is included.
        """
        params = {
            "client_id": self._config.zoho_client_id,
            "redirect_uri": self._config.zoho_redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        base = f"{self._config.zoho_accounts_url}/oauth/v2/auth"
        url = f"{base}?{urlencode(params)}"
        logger.info("Authorization URL params (excluding secrets): %s", {
            k: v for k, v in params.items() if k not in ("client_id",)
        })
        return url

    async def exchange_code_for_tokens(self, code: str) -> TokenSet:
        """Exchange an authorization code for an access/refresh token set."""
        url = f"{self._config.zoho_accounts_url}/oauth/v2/token"
        payload = {
            "code": code,
            "client_id": self._config.zoho_client_id,
            "client_secret": self._config.zoho_client_secret,
            "redirect_uri": self._config.zoho_redirect_uri,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(url, data=payload)
            response.raise_for_status()

        data = response.json()
        logger.info("Token response keys: %s", list(data.keys()))
        logger.info("refresh_token present: %s", "refresh_token" in data)
        logger.info("api_domain from Zoho: %s", data.get("api_domain"))

        return TokenSet(**data)

    async def get_user_info(self, access_token: str) -> ZohoUserInfo:
        """Retrieve Zoho user info.

        Primary: GET /oauth/user/info on the Accounts server.
        Fallback: GET /restapi/portals/ on the Projects API (uses only Projects scopes).

        Uses Zoho-oauthtoken header (Zoho's native format).
        """
        url = f"{self._config.zoho_accounts_url}/oauth/user/info"
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            logger.info("get_user_info url=%s status=%s", url, response.status_code)
            if response.status_code != 200:
                logger.warning("get_user_info failed: %s", response.text)

            if response.status_code == 200:
                data = response.json()
                return ZohoUserInfo(
            zoho_user_id=str(data["ZUID"]),
            email=data["Email"],
            display_name=data.get("Display_Name") or data.get("First_Name", ""),
            )

            # Fallback: pull identity from the Zoho Projects portals endpoint.
            # This works with ZohoProjects scopes alone and always returns
            # login_user_details with the authenticated user's email and ZPUID.
            logger.info("Falling back to portals endpoint for user identity")
            portals_url = f"{self._config.zoho_base_url}/portals/"
            portals_response = await client.get(portals_url, headers=headers)
            logger.info(
                "portals fallback url=%s status=%s",
                portals_url,
                portals_response.status_code,
            )
            if portals_response.status_code != 200:
                logger.warning("portals fallback failed: %s", portals_response.text)
                portals_response.raise_for_status()

            portals_data = portals_response.json()
            user_details = portals_data.get("login_user_details", {})
            return ZohoUserInfo(
                zoho_user_id=user_details.get("ZPUID") or user_details.get("id", ""),
                email=user_details.get("email", ""),
                display_name=user_details.get("display_name") or user_details.get("name", ""),
            )

    async def upsert_user(self, info: ZohoUserInfo) -> User:
        """Insert or update a user row from Zoho identity info.

        Conflicts on ``zoho_user_id``; updates ``email``, ``display_name``,
        and ``updated_at`` on collision.  Returns the live ORM ``User`` object.
        """
        now = datetime.now(UTC)
        stmt = (
            pg_insert(User)
            .values(
                zoho_user_id=info.zoho_user_id,
                email=info.email,
                display_name=info.display_name,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["zoho_user_id"],
                set_={
                    "email": info.email,
                    "display_name": info.display_name,
                    "updated_at": now,
                },
            )
        )
        await self._db.execute(stmt)
        await self._db.flush()

        result = await self._db.execute(
            select(User).where(User.zoho_user_id == info.zoho_user_id)
        )
        user = result.scalar_one()
        logger.info("User upserted successfully (zoho_user_id redacted)")
        return user

    async def store_tokens(self, user_id: UUID, token_set: TokenSet) -> None:
        """Encrypt and persist OAuth tokens for a user.

        access_token is always updated. refresh_token is only updated when Zoho
        returns a new one — if it is absent, the previously stored value is kept.
        This handles Zoho's behaviour of not reissuing a refresh token on
        re-authorisation when one is already active.
        """
        encrypted_access = encrypt(token_set.access_token, self._config.secret_key)
        expires_at = datetime.now(UTC) + timedelta(seconds=token_set.expires_in)
        scopes = token_set.scope.split()
        now = datetime.now(UTC)

        if token_set.refresh_token:
            logger.info("New refresh token received — updating stored value")
            encrypted_refresh: str | None = encrypt(token_set.refresh_token, self._config.secret_key)
        else:
            logger.info("No refresh token in response — preserving existing stored value")
            encrypted_refresh = None

        # Load the existing row so we can fall back to its refresh_token if needed
        existing = await self._db.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        existing_token = existing.scalar_one_or_none()

        if encrypted_refresh is None:
            if existing_token is None:
                raise ValueError(
                    "No refresh token returned by Zoho and no existing token stored. "
                    "Cannot complete token persistence without a refresh token."
                )
            # Keep the refresh token already in the database
            encrypted_refresh = existing_token.refresh_token

        stmt = (
            pg_insert(OAuthToken)
            .values(
                user_id=user_id,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                token_type=token_set.token_type,
                expires_at=expires_at,
                scopes=scopes,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "access_token": encrypted_access,
                    "refresh_token": encrypted_refresh,
                    "token_type": token_set.token_type,
                    "expires_at": expires_at,
                    "scopes": scopes,
                    "updated_at": now,
                },
            )
        )
        await self._db.execute(stmt)
        await self._db.flush()
        logger.info(
            "OAuth tokens stored — api_domain=%s (token values redacted)",
            token_set.api_domain,
        )
