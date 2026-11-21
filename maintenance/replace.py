"""Az adatbázis-példány cseréje (a Render ingyenes csomagjához: egyszerre egy példány).

A csere lépései (a feladatleírás 6.3 szerint):
  1. előfeltételek ellenőrzése, a futás rögzítése
  2. karbantartási mód: a backend elutasítja az írásokat (újratelepítéssel)
  3. végső mentés és ellenőrzés helyi próba-adatbázisban
  4. a régi példány törlése (csak kifejezett engedéllyel), a törlés megvárása
  5. új példány létrehozása, megvárása
  6. visszaállítás az új példányba és ellenőrzés (tartalom, kapcsolatok, szabály, azonosítók)
  7. a backend átállítása az új DATABASE_URL-re, újratelepítés
  8. utóellenőrzés a backend olvasó végpontján
  9. az új aktív példány rögzítése, a karbantartási mód feloldása

Minden elvégzett lépés a state.json-ba kerül, így megszakadás után --resume-mal folytatható.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from maintenance.backup import backup_and_verify, read_backup, restore_and_verify
from maintenance.config import MaintenanceSettings
from maintenance.render_api import RenderApiError, RenderClient
from maintenance.state import ControllerState, ReplaceRun, save_state

logger = logging.getLogger("okoshuto.maintenance.replace")

DEPLOY_FAILED = {"build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated"}


class ReplaceError(Exception):
    """A csere nem folytatható; a karbantartási mód érvényben marad."""


# --- várakozó segédfüggvények (időkorláttal) -----------------------------

async def wait_for_deploy(
    render: RenderClient, service_id: str, deploy_id: str, interval: float, timeout: float
) -> None:
    """Megvárja, amíg a telepítés 'live' lesz; hibánál vagy időtúllépésnél ReplaceError."""
    deadline = time.monotonic() + timeout
    while True:
        status = (await render.get_deploy(service_id, deploy_id)).get("status")
        logger.info("Telepítés %s: %s", deploy_id, status)
        if status == "live":
            return
        if status in DEPLOY_FAILED:
            raise ReplaceError(f"A telepítés sikertelen: {status}")
        if time.monotonic() > deadline:
            raise ReplaceError(f"A telepítés nem fejeződött be {timeout:.0f} mp alatt.")
        await asyncio.sleep(interval)


async def wait_for_postgres(
    render: RenderClient, postgres_id: str, interval: float, timeout: float
) -> None:
    """Megvárja, amíg az új példány 'available' állapotú lesz."""
    deadline = time.monotonic() + timeout
    while True:
        status = (await render.get_postgres(postgres_id)).get("status")
        logger.info("Új adatbázis %s: %s", postgres_id, status)
        if status == "available":
            return
        if time.monotonic() > deadline:
            raise ReplaceError(f"Az új adatbázis nem lett elérhető {timeout:.0f} mp alatt.")
        await asyncio.sleep(interval)


async def wait_until_deleted(
    render: RenderClient, postgres_id: str, interval: float, timeout: float
) -> None:
    """Megvárja, amíg a törölt példány már nem kérdezhető le (HTTP 404)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = (await render.get_postgres(postgres_id)).get("status")
        except RenderApiError as exc:
            if exc.status_code == 404:
                logger.info("A régi adatbázis (%s) törlése befejeződött.", postgres_id)
                return
            raise
        logger.info("A régi adatbázis törlése folyamatban: %s", status)
        if time.monotonic() > deadline:
            raise ReplaceError(f"A régi adatbázis törlése nem fejeződött be {timeout:.0f} mp alatt.")
        await asyncio.sleep(interval)


async def redeploy(render: RenderClient, settings: MaintenanceSettings) -> None:
    """Újratelepíti a backendet, és megvárja, amíg él."""
    deploy = await render.trigger_deploy(settings.render_service_id)
    await wait_for_deploy(
        render, settings.render_service_id, deploy["id"],
        settings.poll_interval_seconds, settings.deploy_timeout_seconds,
    )


async def set_maintenance_mode(render: RenderClient, settings: MaintenanceSettings, enabled: bool) -> None:
    """Be- vagy kikapcsolja a backend karbantartási módját (MAINTENANCE_MODE + újratelepítés)."""
    await render.set_env_var(settings.render_service_id, "MAINTENANCE_MODE", str(enabled).lower())
    await redeploy(render, settings)
    logger.info("Karbantartási mód: %s", "BE" if enabled else "KI")


# --- bizonytalan létrehozás kezelése --------------------------------------

async def ensure_new_postgres(render: RenderClient, run: ReplaceRun) -> str:
    """Létrehozza az új példányt, vagy ha egy korábbi futás már létrehozta, azt használja.

    Egy időtúllépés után nem tudni biztosan, létrejött-e a példány. Ezért a futás
    egyedi nevén először megkeressük; csak ha nincs, hozunk létre újat.
    """
    if run.new_postgres_id:
        return run.new_postgres_id
    matches = [db for db in await render.list_postgres() if db.get("name") == run.new_postgres_name]
    if len(matches) > 1:
        raise ReplaceError(f"Több '{run.new_postgres_name}' nevű példány van; kézi ellenőrzés szükséges.")
    if matches:
        logger.warning("Egy korábbi futás már létrehozta az új példányt: %s", matches[0]["id"])
        return matches[0]["id"]
    created = await render.create_postgres({
        "name": run.new_postgres_name,
        "ownerId": run.owner_id,
        "plan": run.plan,
        "version": run.version,
        "region": run.region,
        "databaseName": run.database_name,
    })
    logger.info("Új adatbázis létrehozva: %s (%s)", created["id"], run.new_postgres_name)
    return created["id"]


# --- utóellenőrzés ---------------------------------------------------------

async def check_backend_content(backend_url: str, backup: dict[str, Any], timeout: float) -> None:
    """A telepített backend /products végpontja a visszaállított termékeket adja-e vissza."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{backend_url.rstrip('/')}/products")
    if response.status_code != 200:
        raise ReplaceError(f"A backend /products végpontja HTTP {response.status_code} választ adott.")
    actual = sorted((p["id"], p["name"], p["quantity"]) for p in response.json())
    expected = sorted((p["id"], p["name"], p["quantity"]) for p in backup["tables"]["products"])
    if actual != expected:
        raise ReplaceError("A backend által visszaadott termékek eltérnek a mentéstől.")
    logger.info("Utóellenőrzés: a backend a visszaállított %d terméket adja vissza.", len(actual))


# --- a csere munkafolyamata -----------------------------------------------

async def start_run(
    render: RenderClient, settings: MaintenanceSettings, source_id: str, confirm_delete: str | None
) -> ReplaceRun:
    """1. lépés: előfeltételek ellenőrzése és az új futás adatainak rögzítése."""
    if confirm_delete != source_id:
        raise ReplaceError(
            "A régi példány törléséhez kifejezett engedély kell: "
            f"--confirm-delete {source_id}"
        )
    await render.get_service(settings.render_service_id)  # létezik és elérhető-e
    source = await render.get_postgres(source_id)
    if source.get("status") != "available":
        raise ReplaceError(f"A forrás-adatbázis nem elérhető (állapot: {source.get('status')}).")
    owner_id = (source.get("owner") or {}).get("id") or settings.render_owner_id
    if not owner_id:
        raise ReplaceError("A tulajdonos (workspace) azonosítója ismeretlen; add meg: RENDER_OWNER_ID.")
    now = datetime.now(timezone.utc)
    run = ReplaceRun(
        run_id=f"{now:%Y%m%d%H%M}",
        started_at=now.isoformat(),
        source_postgres_id=source_id,
        owner_id=owner_id,
        plan=str(source.get("plan", "free")),
        region=str(source.get("region", "frankfurt")),
        version=str(source.get("version", "18")),
        database_name=str(source.get("databaseName", "okoshuto")),
        new_postgres_name=f"okoshuto-db-{now:%Y%m%d%H%M}",
    )
    logger.info(
        "Csere indul: %s -> %s | csomag: %s, régió: %s, verzió: %s",
        source_id, run.new_postgres_name, run.plan, run.region, run.version,
    )
    return run


async def run_replace(
    settings: MaintenanceSettings,
    state: ControllerState,
    state_path: Path,
    backup_dir: Path,
    confirm_delete: str | None,
    resume: bool,
) -> None:
    """A teljes csere, lépésenként; minden elvégzett lépést rögzít az állapotfájlban."""
    source_id = state.active_postgres_id or settings.render_postgres_id
    async with RenderClient(settings.render_api_key, settings.http_timeout, settings.max_retries) as render:
        if resume:
            if state.run is None or state.run.status == "completed":
                raise ReplaceError("Nincs folytatható, befejezetlen csere.")
            run = state.run
            if "delete_old" not in run.completed_steps and confirm_delete != run.source_postgres_id:
                raise ReplaceError(
                    "A régi példány még nincs törölve; a folytatáshoz is kell az engedély: "
                    f"--confirm-delete {run.source_postgres_id}"
                )
            run.status, run.error = "running", None
            logger.info("Csere folytatása: %s (kész lépések: %s)", run.run_id, run.completed_steps)
        else:
            if state.run is not None and state.run.status != "completed":
                raise ReplaceError("Egy korábbi csere nem fejeződött be; folytatás: replace --resume")
            run = await start_run(render, settings, source_id, confirm_delete)
            state.run = run
        save_state(state, state_path)

        async def step(name: str, action: Callable[[], Awaitable[None]]) -> None:
            """Egy lépés végrehajtása, ha még nincs kész; utána rögzítés."""
            if name in run.completed_steps:
                logger.info("[%s] már kész, kihagyva", name)
                return
            logger.info("[%s] indul", name)
            await action()
            run.completed_steps.append(name)
            save_state(state, state_path)
            logger.info("[%s] kész", name)

        async def maintenance_on() -> None:
            await set_maintenance_mode(render, settings, True)
            await asyncio.sleep(settings.drain_seconds)  # a folyamatban lévő írások befejeződnek

        async def final_backup() -> None:
            info = await render.get_postgres_connection_info(run.source_postgres_id)
            path = await asyncio.to_thread(
                backup_and_verify, info["externalConnectionString"], run.source_postgres_id, backup_dir
            )
            run.backup_path = str(path)

        async def delete_old() -> None:
            if confirm_delete != run.source_postgres_id:
                raise ReplaceError("Nincs törlési engedély a régi példányra.")
            await render.delete_postgres(run.source_postgres_id)
            await wait_until_deleted(
                render, run.source_postgres_id,
                settings.poll_interval_seconds, settings.postgres_timeout_seconds,
            )

        async def create_new() -> None:
            run.new_postgres_id = await ensure_new_postgres(render, run)
            save_state(state, state_path)  # az azonosító azonnal tartósan rögzül
            await wait_for_postgres(
                render, run.new_postgres_id,
                settings.poll_interval_seconds, settings.postgres_timeout_seconds,
            )

        async def restore_new() -> None:
            backup = read_backup(Path(run.backup_path))
            info = await render.get_postgres_connection_info(run.new_postgres_id)
            await asyncio.to_thread(restore_and_verify, info["externalConnectionString"], backup)

        async def switch_backend() -> None:
            info = await render.get_postgres_connection_info(run.new_postgres_id)
            await render.set_env_var(
                settings.render_service_id, "DATABASE_URL", info["internalConnectionString"]
            )
            await redeploy(render, settings)

        async def post_check() -> None:
            backup = read_backup(Path(run.backup_path))
            await check_backend_content(settings.backend_url, backup, settings.http_timeout)

        async def record_active() -> None:
            state.active_postgres_id = run.new_postgres_id
            logger.info("Új aktív adatbázis rögzítve: %s", run.new_postgres_id)

        async def maintenance_off() -> None:
            await set_maintenance_mode(render, settings, False)

        try:
            await step("maintenance_on", maintenance_on)
            await step("final_backup", final_backup)
            await step("delete_old", delete_old)
            await step("create_new", create_new)
            await step("restore_new", restore_new)
            await step("switch_backend", switch_backend)
            await step("post_check", post_check)
            await step("record_active", record_active)
            await step("maintenance_off", maintenance_off)
        except Exception as exc:
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
            save_state(state, state_path)
            logger.error(
                "A csere leállt: %s. A karbantartási mód érvényben marad; "
                "a mentés (%s) és az állapot megmaradt. Javítás után: replace --resume",
                run.error, run.backup_path,
            )
            raise

        run.status, run.finished_at = "completed", datetime.now(timezone.utc).isoformat()
        save_state(state, state_path)
        logger.info("A csere sikeresen befejeződött. Új aktív adatbázis: %s", run.new_postgres_id)