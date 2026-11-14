"""A backend REST API-jának kliense: a felület minden HTTP-kérése itt történik."""

import logging
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """A felhasználónak megjeleníthető hiba az API hívásakor."""


class ApiClient:
    """Egyszerű kliens az Okoshűtő API-hoz, időkorláttal és hibakezeléssel."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # --- végpontok ----------------------------------------------------

    def get_categories(self) -> list[dict[str, Any]]:
        return self._request("GET", "/categories")

    def get_products(
        self, category_id: int | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"category_id": category_id, "status": status}
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/products", params=params)

    def create_product(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/products", json=data)

    def add_consumption(
        self, product_id: int, amount: float, consumed_on: date
    ) -> dict[str, Any]:
        body = {"amount": amount, "consumed_on": consumed_on.isoformat()}
        return self._request("POST", f"/products/{product_id}/consumptions", json=body)

    def get_shopping_list(self, reference_date: date) -> list[dict[str, Any]]:
        params = {"reference_date": reference_date.isoformat()}
        return self._request("GET", "/shopping-list", params=params)

    # --- belső működés ------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Elküldi a kérést; hiba esetén érthető üzenetű ApiError-t dob."""
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            logger.warning("Időtúllépés: %s %s", method, url)
            raise ApiError("A szerver nem válaszolt időben. Próbáld újra később!") from exc
        except requests.ConnectionError as exc:
            logger.error("Nem érhető el a backend: %s", url)
            raise ApiError("Nem sikerült kapcsolódni a szerverhez. Fut a backend?") from exc

        if response.status_code >= 400:
            logger.warning("Hibás válasz: %s %s -> %s", method, url, response.status_code)
            raise ApiError(self._error_message(response))
        return response.json()

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        """A FastAPI hibaválaszából olvasható üzenetet készít."""
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, list):  # a FastAPI validációs hibái listában jönnek
            detail = "; ".join(f"{e['loc'][-1]}: {e['msg']}" for e in detail)
        return f"Hiba ({response.status_code}): {detail or response.reason}"