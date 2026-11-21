"""Egységtesztek az adatbázis-csere döntéseihez, helyettesített Render API-válaszokkal."""

import asyncio

import httpx
import pytest

from maintenance.render_api import RenderClient
from maintenance.replace import ReplaceError, ensure_new_postgres, start_run, wait_for_deploy
from maintenance.state import ReplaceRun

FUTAS_NEVE = "okoshuto-db-202612010900"


def uj_futas() -> ReplaceRun:
    """Egy csere futásának adatai, ahogy az állapotfájlban szerepelnének."""
    return ReplaceRun(
        run_id="202612010900", started_at="2026-12-01T09:00:00+00:00",
        source_postgres_id="dpg-regi-a", owner_id="tea-1", plan="free", region="frankfurt",
        version="18", database_name="okoshuto", new_postgres_name=FUTAS_NEVE,
    )


def futtat(kezelo, muvelet):
    """Lefuttat egy műveletet egy olyan Render-klienssel, amely a kezelő válaszait kapja."""
    async def belso():
        async with RenderClient("teszt-kulcs", max_retries=0, backoff_seconds=0,
                                transport=httpx.MockTransport(kezelo)) as render:
            return await muvelet(render)
    return asyncio.run(belso())


@pytest.mark.parametrize(
    ("meglevo_peldanyok", "elvart_id", "letrehozas_vart"),
    [
        # nincs még új példány -> létrehozza
        ([], "dpg-uj-a", True),
        # félbeszakadt létrehozás után: a futás nevén már létezik -> azt használja, nem hoz létre újat
        ([{"id": "dpg-korabbi-a", "name": FUTAS_NEVE}], "dpg-korabbi-a", False),
        # más nevű példány nem számít
        ([{"id": "dpg-mas-a", "name": "masik-db"}], "dpg-uj-a", True),
    ],
)
def test_uj_peldany_letrehozasa_vagy_atvetele(meglevo_peldanyok, elvart_id, letrehozas_vart):
    letrehozasok: list[str] = []

    def kezelo(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"cursor": "c", "postgres": p} for p in meglevo_peldanyok])
        letrehozasok.append(request.url.path)  # POST /postgres
        return httpx.Response(201, json={"id": "dpg-uj-a", "status": "creating"})

    assert futtat(kezelo, lambda render: ensure_new_postgres(render, uj_futas())) == elvart_id
    assert bool(letrehozasok) == letrehozas_vart


def test_ket_azonos_nevu_peldany_eseten_leall():
    def kezelo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"postgres": {"id": "a", "name": FUTAS_NEVE}},
                                         {"postgres": {"id": "b", "name": FUTAS_NEVE}}])

    with pytest.raises(ReplaceError):
        futtat(kezelo, lambda render: ensure_new_postgres(render, uj_futas()))


def test_sikertelen_telepites_leallitja_a_cseret():
    def kezelo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "dep-1", "status": "build_failed"})

    with pytest.raises(ReplaceError):
        futtat(kezelo, lambda render: wait_for_deploy(render, "srv-1", "dep-1", interval=0, timeout=5))


def test_torlesi_engedely_nelkul_nem_indul_csere():
    hivasok: list[str] = []

    def kezelo(request: httpx.Request) -> httpx.Response:
        hivasok.append(request.url.path)
        return httpx.Response(200, json={})

    with pytest.raises(ReplaceError):
        futtat(kezelo, lambda render: start_run(
            render, settings=None, source_id="dpg-regi-a", confirm_delete="dpg-MAS-a"
        ))
    assert hivasok == []  # egyetlen API-hívás sem történt