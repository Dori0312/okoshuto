"""Egységtesztek a karbantartó program döntéseihez és a Render-klienshez.

A szolgáltatói hívásokat helyettesített (mock) API-válaszok pótolják,
valódi hálózati kérés nem történik.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from maintenance.decisions import Action, DbStatus, decide
from maintenance.render_api import RenderApiError, RenderClient

MOST = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("db", "tervezett", "elvart"),
    [
        # kapcsolódási hiba: nem indokol cserét
        (DbStatus(reachable=False), None, Action.WAIT),
        # a példány nem 'available' (pl. éppen létrejön): nem cserélünk vakon
        (DbStatus(True, "creating", MOST + timedelta(days=30)), None, Action.WAIT),
        # bőven van idő a lejáratig
        (DbStatus(True, "available", MOST + timedelta(days=20)), None, Action.NONE),
        # határeset: pontosan 7 nap van hátra -> csere
        (DbStatus(True, "available", MOST + timedelta(days=7)), None, Action.REPLACE),
        # 7 nap + 1 perc -> még nem kell
        (DbStatus(True, "available", MOST + timedelta(days=7, minutes=1)), None, Action.NONE),
        # elérkezett a tervezett karbantartás, pedig a lejárat még messze van
        (DbStatus(True, "available", MOST + timedelta(days=20)), MOST, Action.REPLACE),
        # nincs lejárati adat és nincs tervezett karbantartás
        (DbStatus(True, "available", None), None, Action.NONE),
    ],
)
def test_karbantartasi_dontes(db, tervezett, elvart):
    assert decide(db, MOST, warning_days=7, planned_at=tervezett).action == elvart


def test_idozona_nelkuli_idopont_hibat_ad():
    with pytest.raises(ValueError):
        decide(DbStatus(True, "available", None), datetime(2026, 12, 1), warning_days=7)


def _kliens(valaszok: list[httpx.Response], hivasok: list[str]) -> RenderClient:
    """Render-kliens, amely a valódi API helyett az előre megadott válaszokat adja."""

    def kezelo(request: httpx.Request) -> httpx.Response:
        hivasok.append(request.url.path)
        return valaszok.pop(0)

    return RenderClient("teszt-kulcs", max_retries=2, backoff_seconds=0,
                        transport=httpx.MockTransport(kezelo))


def test_atmeneti_szolgaltatoi_hiba_utan_ujraprobal():
    hivasok: list[str] = []
    valaszok = [httpx.Response(503), httpx.Response(200, json={"id": "dpg-1", "status": "available"})]

    async def futtat():
        async with _kliens(valaszok, hivasok) as render:
            return await render.get_postgres("dpg-1")

    assert asyncio.run(futtat())["status"] == "available"
    assert len(hivasok) == 2  # egy sikertelen és egy sikeres próbálkozás


def test_jogosultsagi_hiba_eseten_nem_probal_ujra():
    hivasok: list[str] = []
    valaszok = [httpx.Response(401), httpx.Response(200, json={})]

    async def futtat():
        async with _kliens(valaszok, hivasok) as render:
            await render.get_postgres("dpg-1")

    with pytest.raises(RenderApiError) as hiba:
        asyncio.run(futtat())
    assert hiba.value.status_code == 401
    assert len(hivasok) == 1  # nincs újrapróbálkozás