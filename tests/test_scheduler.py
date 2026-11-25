"""Egységtesztek az időzített ellenőrzés döntéseihez (mikor indulhat csere)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from maintenance import controller
from maintenance.config import MaintenanceSettings
from maintenance.decisions import Action, DbStatus, Decision, decide
from maintenance.state import ControllerState, ReplaceRun, save_state

MOST = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
TERVEZETT = MOST - timedelta(hours=1)
ELERHETO = DbStatus(True, "available", MOST + timedelta(days=20))


@pytest.mark.parametrize(
    ("utolso_csere", "elvart"),
    [
        (None, Action.REPLACE),                        # még nem volt csere
        (TERVEZETT - timedelta(days=1), Action.REPLACE),  # a csere a tervezett időpont előtt volt
        (TERVEZETT + timedelta(minutes=5), Action.NONE),  # a tervezett karbantartás már teljesült
    ],
)
def test_teljesitett_tervezett_karbantartas_nem_indit_uj_cseret(utolso_csere, elvart):
    dontes = decide(ELERHETO, MOST, warning_days=7, planned_at=TERVEZETT, last_replaced_at=utolso_csere)
    assert dontes.action == elvart


def _futas(statusz: str) -> ReplaceRun:
    return ReplaceRun(
        run_id="1", started_at="x", source_postgres_id="dpg-regi-a", owner_id="tea-1",
        plan="free", region="frankfurt", version="18", database_name="okoshuto",
        new_postgres_name="okoshuto-db-1", status=statusz,
    )


@pytest.mark.parametrize(
    ("dontes", "engedely", "elozo_futas", "csere_vart"),
    [
        (Action.NONE, "dpg-regi-a", None, False),              # nincs teendő
        (Action.WAIT, "dpg-regi-a", None, False),              # várakozás (pl. kapcsolódási hiba)
        (Action.REPLACE, None, None, False),                   # csere kellene, de nincs engedély
        (Action.REPLACE, "dpg-MAS-a", None, False),            # az engedély másik erőforrásra szól
        (Action.REPLACE, "dpg-regi-a", _futas("failed"), False),  # befejezetlen korábbi csere
        (Action.REPLACE, "dpg-regi-a", None, True),            # minden feltétel teljesül
    ],
)
def test_idozitett_ellenorzes_csak_engedellyel_indit_cseret(
    monkeypatch, tmp_path, dontes, engedely, elozo_futas, csere_vart
):
    allapotfajl = tmp_path / "state.json"
    save_state(ControllerState(run=elozo_futas), allapotfajl)
    monkeypatch.setattr(controller, "STATE_FILE", allapotfajl)

    async def hamis_ellenorzes(settings):
        return Decision(dontes, "teszt")

    cserek: list[str | None] = []

    async def hamis_csere(settings, confirm_delete, resume):
        cserek.append(confirm_delete)

    monkeypatch.setattr(controller, "check_status", hamis_ellenorzes)
    monkeypatch.setattr(controller, "replace_database", hamis_csere)
    beallitasok = MaintenanceSettings(
        _env_file=None, render_api_key="k", render_service_id="srv-1",
        render_postgres_id="dpg-regi-a", replace_confirm_delete=engedely,
    )

    asyncio.run(controller.scheduled_check(beallitasok))

    assert bool(cserek) == csere_vart