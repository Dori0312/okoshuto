"""Aszinkron kliens a Render REST API-jához (httpx.AsyncClient)."""

import asyncio
import logging
from types import TracebackType
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RENDER_API_URL = "https://api.render.com/v1"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class RenderApiError(Exception):
    """A Render API hívása sikertelen volt (az újrapróbálkozások után is)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RenderClient:
    """Render API-kliens időkorláttal és korlátozott újrapróbálkozással.

    Használat:  async with RenderClient(api_key) as render: ...
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=RENDER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    async def __aenter__(self) -> "RenderClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    # --- lekérdezések -------------------------------------------------

    async def get_postgres(self, postgres_id: str) -> dict[str, Any]:
        """Egy PostgreSQL-példány adatai (állapot, lejárat, verzió, régió...)."""
        return await self._request("GET", f"/postgres/{postgres_id}")

    async def list_postgres(self) -> list[dict[str, Any]]:
        """Az API-kulccsal elérhető PostgreSQL-példányok listája."""
        items = await self._request("GET", "/postgres", params={"limit": 100})
        return [item.get("postgres", item) for item in items]


    async def get_service(self, service_id: str) -> dict[str, Any]:
        """Egy webszolgáltatás adatai."""
        return await self._request("GET", f"/services/{service_id}")

    # --- belső működés ------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """HTTP-kérés korlátozott újrapróbálkozással.

        Átmeneti hiba (időtúllépés, hálózati hiba, 429, 5xx) esetén legfeljebb
        max_retries-szor próbálkozik újra, egyre hosszabb várakozással.
        Jogosultsági vagy egyéb hiba (401, 403, 404, 4xx) esetén azonnal leáll.
        """
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:  # időtúllépés, kapcsolódási hiba
                reason = f"hálózati hiba: {type(exc).__name__}"
                status = None
            else:
                if response.status_code < 400:
                    return None if response.status_code == 204 else response.json()
                status = response.status_code
                reason = f"HTTP {status}"
                if status not in RETRY_STATUSES:
                    raise RenderApiError(f"{method} {path} sikertelen: {reason}", status)

            if attempt == self.max_retries:
                raise RenderApiError(
                    f"{method} {path} sikertelen {attempt + 1} próbálkozás után: {reason}", status
                )
            wait = self.backoff_seconds * 2**attempt
            logger.warning("%s %s: %s, újra %.0f mp múlva", method, path, reason, wait)
            await asyncio.sleep(wait)
        raise AssertionError("ide nem juthat el a program")