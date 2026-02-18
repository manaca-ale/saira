from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class ConectaService:
    def ensure_enabled_and_configured(self) -> None:
        if not settings.ENABLE_CONECTA_LOGIN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Conecta login is disabled",
            )

        missing = []
        if not settings.CONECTA_CLIENT_ID:
            missing.append("CONECTA_CLIENT_ID")
        if not settings.CONECTA_REDIRECT_URI:
            missing.append("CONECTA_REDIRECT_URI")

        if missing:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Conecta not configured: missing {', '.join(missing)}",
            )

    def _base_url(self) -> str:
        conecta_env = settings.CONECTA_ENV.strip().lower()
        if conecta_env in {"prod", "production"}:
            return settings.CONECTA_BASE_URL_PROD.rstrip("/")
        return settings.CONECTA_BASE_URL_TEST.rstrip("/")

    def _protocol_base(self) -> str:
        return f"{self._base_url()}/realms/{settings.CONECTA_REALM}/protocol/openid-connect"

    def authorization_endpoint(self) -> str:
        return f"{self._protocol_base()}/auth"

    def token_endpoint(self) -> str:
        return f"{self._protocol_base()}/token"

    def userinfo_endpoint(self) -> str:
        return f"{self._protocol_base()}/userinfo"

    def logout_endpoint(self) -> str:
        return f"{self._protocol_base()}/logout"

    def introspect_endpoint(self) -> str:
        return f"{self.token_endpoint()}/introspect"

    def build_authorization_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.CONECTA_CLIENT_ID,
            "redirect_uri": settings.CONECTA_REDIRECT_URI,
            "scope": settings.CONECTA_SCOPE,
            "state": state,
        }
        return f"{self.authorization_endpoint()}?{urlencode(params)}"

    def build_logout_url(self, redirect_uri: str) -> str:
        return f"{self.logout_endpoint()}?{urlencode({'redirect_uri': redirect_uri})}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.CONECTA_REDIRECT_URI,
            "client_id": settings.CONECTA_CLIENT_ID,
        }
        if settings.CONECTA_CLIENT_SECRET:
            data["client_secret"] = settings.CONECTA_CLIENT_SECRET

        return await self._post_form(self.token_endpoint(), data)

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        return await self._get_json(self.userinfo_endpoint(), headers=headers)

    async def introspect_token(self, access_token: str) -> dict[str, Any]:
        data = {
            "client_id": settings.CONECTA_CLIENT_ID,
            "token": access_token,
        }
        if settings.CONECTA_CLIENT_SECRET:
            data["client_secret"] = settings.CONECTA_CLIENT_SECRET
        return await self._post_form(self.introspect_endpoint(), data)

    async def _post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.CONECTA_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(url, data=data)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to call Conecta endpoint: {exc.__class__.__name__}",
            ) from exc

        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Conecta endpoint returned {response.status_code}",
            )

        return response.json()

    async def _get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.CONECTA_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to call Conecta endpoint: {exc.__class__.__name__}",
            ) from exc

        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Conecta endpoint returned {response.status_code}",
            )

        return response.json()


conecta_service = ConectaService()
