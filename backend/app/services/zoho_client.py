"""Zoho Projects API client."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.models.db import OAuthToken
from app.services.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


class ZohoClient:
    def __init__(self, config: Config, db: AsyncSession, user_id: UUID) -> None:
        self.config = config
        self.db = db
        self.user_id = user_id
        # zoho_base_url is set in .env, e.g. https://projectsapi.zoho.in/restapi
        self._base = config.zoho_base_url

    async def _get_token(self) -> OAuthToken:
        result = await self.db.execute(
            select(OAuthToken).where(OAuthToken.user_id == self.user_id)
        )
        token = result.scalar_one_or_none()
        if token is None:
            raise ValueError(f"No OAuth token found for user {self.user_id}")
        return token

    async def _refresh_token(self, token: OAuthToken) -> OAuthToken:
        refresh_token_plain = decrypt(token.refresh_token, self.config.secret_key)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.config.zoho_accounts_url}/oauth/v2/token",
                data={
                    "refresh_token": refresh_token_plain,
                    "client_id": self.config.zoho_client_id,
                    "client_secret": self.config.zoho_client_secret,
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code >= 400:
                logger.error(
                    "Token refresh failed | Status=%s | Body=%s",
                    response.status_code,
                    response.text,
                )
            response.raise_for_status()

        data = response.json()
        token.access_token = encrypt(data["access_token"], self.config.secret_key)
        token.expires_at = datetime.now(UTC) + timedelta(seconds=data.get("expires_in", 3600))
        await self.db.commit()
        logger.info("Access token refreshed successfully")
        return token

    async def _get_headers(self) -> dict:
        """Return auth headers, refreshing the token first if near expiry."""
        token = await self._get_token()

        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            from datetime import timezone
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(UTC) >= expires_at - timedelta(seconds=60):
            token = await self._refresh_token(token)

        access_token = decrypt(token.access_token, self.config.secret_key)
        logger.info("Using Zoho-oauthtoken authentication (value redacted)")
        return {"Authorization": f"Zoho-oauthtoken {access_token}"}

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """Authenticated API request with 401 retry and full error logging.

        Never raises on 4xx/5xx — returns {"error": {"code": ..., "message": ...}} instead,
        so callers can handle errors without crashing.
        """
        headers = await self._get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code == 401:
                logger.warning("Received 401 — refreshing token and retrying")
                token = await self._get_token()
                token = await self._refresh_token(token)
                access_token = decrypt(token.access_token, self.config.secret_key)
                headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
                response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code >= 400:
                logger.error(
                    "Zoho API Error | Method=%s | URL=%s | Status=%s | Body=%s",
                    method, url, response.status_code, response.text,
                )
                # Return structured error dict — do NOT raise, so callers never get a 500
                try:
                    body = response.json()
                    # Zoho wraps errors as {"error": {"code": N, "message": "..."}}
                    if "error" in body:
                        return body
                    return {"error": {"code": response.status_code, "message": str(body)}}
                except Exception:
                    return {"error": {"code": response.status_code, "message": response.text}}

            return response.json()

    async def get_portal_id(self) -> str:
        """Get the user's first Zoho portal ID."""
        data = await self._request("GET", f"{self._base}/portals/")
        portals = data.get("portals", [])
        if not portals:
            raise ValueError("No Zoho Projects portals found for this account.")
        portal_id = str(portals[0].get("id", portals[0].get("zsoid", "")))
        logger.info("Portal ID: %s", portal_id)
        return portal_id

    async def get_projects(self, portal_id: str) -> list[dict]:
        """List all active projects for the user."""
        data = await self._request("GET", f"{self._base}/portal/{portal_id}/projects/")
        projects = data.get("projects", [])
        logger.info("Projects count: %d", len(projects))
        return projects

    async def get_tasks(self, portal_id: str, project_id: str, **filters) -> list[dict]:
        """List tasks for a project."""
        data = await self._request(
            "GET",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/tasks/",
            params=filters,
        )
        tasks = data.get("tasks", [])
        logger.info("Tasks count: %d", len(tasks))
        return tasks

    async def get_task(self, portal_id: str, project_id: str, task_id: str) -> dict:
        """Get full details for a single task."""
        data = await self._request(
            "GET",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/",
        )
        return data.get("tasks", [{}])[0]

    async def get_project_members(self, portal_id: str, project_id: str) -> list[dict]:
        """Get all members of a project."""
        data = await self._request(
            "GET",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/users/",
        )
        return data.get("users", [])

    async def create_task(self, portal_id: str, project_id: str, name: str, **fields) -> dict:
        """Create a new task in a project.

        Zoho Projects Create Task API requires form-encoded (application/x-www-form-urlencoded)
        request body — NOT JSON.  Passing json= returns error 6831 "Input Parameter Missing".
        person_responsible must be a plain Long (zpuid), not a JSON array.
        """
        payload = {"name": name}
        for key, value in fields.items():
            # person_responsible comes in as [{"zpuid": "..."}] from write_tools;
            # flatten it to a plain comma-separated zpuid string for the API.
            if key == "person_responsible" and isinstance(value, list):
                payload[key] = ",".join(
                    str(item["zpuid"]) if isinstance(item, dict) else str(item)
                    for item in value
                )
            else:
                payload[key] = value
        logger.info("CREATE TASK PAYLOAD => %s", payload)
        data = await self._request(
            "POST",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/tasks/",
            data=payload,
        )
        return data.get("tasks", [{}])[0]

    async def update_task(
        self, portal_id: str, project_id: str, task_id: str, fields: dict
    ) -> dict:
        """Update specific fields on an existing task.

        Uses form-encoded body (same requirement as create_task).
        """
        logger.info("UPDATE TASK PAYLOAD => %s", fields)
        data = await self._request(
            "POST",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/",
            data=fields,
        )
        return data.get("tasks", [{}])[0]

    async def delete_task(self, portal_id: str, project_id: str, task_id: str) -> bool:
        """Delete a task."""
        await self._request(
            "DELETE",
            f"{self._base}/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/",
        )
        return True
