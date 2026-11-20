"""Az Okoshűtő karbantartó vezérlője.

Indítás a projekt gyökeréből:
    python -m maintenance.controller check
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.database import make_engine
from maintenance.backup import create_backup, read_backup, restore_backup, verify_restore
from maintenance.config import MaintenanceSettings
from maintenance.decisions import DbStatus, Decision, decide, parse_render_datetime
from maintenance.render_api import RenderApiError, RenderClient

LOG_FILE = Path(__file__).with_name("maintenance.log")
BACKUP_DIR = Path("backups")
logger = logging.getLogger("okoshuto.maintenance")


def setup_logging() -> None:
    """Naplózás a konzolra és a maintenance/maintenance.log fájlba."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


async def fetch_db_status(render: RenderClient, postgres_id: str) -> DbStatus:
    """Lekéri az adatbázis-példány állapotát; hiba esetén 'nem elérhető' állapotot ad."""
    try:
        data = await render.get_postgres(postgres_id)
    except RenderApiError as exc:
        logger.error("Az adatbázis állapota nem kérdezhető le: %s", exc)
        return DbStatus(reachable=False)
    logger.info(
        "Adatbázis: %s | állapot: %s | lejárat: %s | verzió: %s | régió: %s",
        data.get("name"), data.get("status"), data.get("expiresAt"),
        data.get("version"), data.get("region"),
    )
    return DbStatus(
        reachable=True,
        status=data.get("status"),
        expires_at=parse_render_datetime(data.get("expiresAt")),
    )


async def check_backend(backend_url: str, timeout: float) -> bool:
    """A telepített backend /health végpontjának ellenőrzése."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{backend_url.rstrip('/')}/health")
    except httpx.TransportError as exc:
        logger.warning("A backend nem érhető el: %s", type(exc).__name__)
        return False
    logger.info("Backend /health: HTTP %s", response.status_code)
    return response.status_code == 200


async def check_status(settings: MaintenanceSettings) -> Decision:
    """Egy állapotellenőrzés: az adatbázis és a backend lekérdezése párhuzamosan, majd döntés."""
    async with RenderClient(
        settings.render_api_key, settings.http_timeout, settings.max_retries
    ) as render:
        db, backend_ok = await asyncio.gather(
            fetch_db_status(render, settings.render_postgres_id),
            check_backend(settings.backend_url, settings.http_timeout),
        )
    decision = decide(
        db,
        now=datetime.now(timezone.utc),
        warning_days=settings.expiry_warning_days,
        planned_at=settings.planned_maintenance_at,
    )
    logger.info("Backend elérhető: %s | Döntés: %s – %s", backend_ok, decision.action, decision.reason)
    return decision


def backup_and_verify(db_url: str, source_id: str) -> Path:
    """Mentés a forrásból, majd ellenőrzés egy elkülönített, helyi próba-adatbázisban.

    1. a forrás teljes tartalmának mentése JSON-fájlba (backups/ mappa)
    2. a mentés visszaállítása egy új, üres helyi SQLite-adatbázisba
    3. a visszaállított adatok összevetése a mentéssel
    """
    source = make_engine(db_url)
    try:
        path = create_backup(source, source_id, BACKUP_DIR)
    finally:
        source.dispose()

    backup = read_backup(path)
    trial_path = BACKUP_DIR / f"{path.stem}_proba.db"
    trial = make_engine(f"sqlite:///{trial_path.as_posix()}")
    try:
        restore_backup(trial, backup)
        problems = verify_restore(trial, backup)
    finally:
        trial.dispose()

    if problems:
        for problem in problems:
            logger.error("Ellenőrzési hiba: %s", problem)
        raise RuntimeError("A mentés ellenőrzése sikertelen; a próba-adatbázis megmaradt: " + str(trial_path))
    trial_path.unlink()
    logger.info("A mentés ellenőrizve: a helyi próbavisszaállítás sikeres.")
    return path


async def run_backup(settings: MaintenanceSettings) -> Path:
    """Lekéri az adatbázis kapcsolódási címét a Render API-tól, majd ment és ellenőriz."""
    async with RenderClient(
        settings.render_api_key, settings.http_timeout, settings.max_retries
    ) as render:
        info = await render.get_postgres_connection_info(settings.render_postgres_id)
    db_url = info["externalConnectionString"]
    # Az adatbázis-műveletek szinkronok: külön szálon futnak, hogy ne blokkolják az eseményhurkot.
    return await asyncio.to_thread(backup_and_verify, db_url, settings.render_postgres_id)


async def show_resources(settings: MaintenanceSettings) -> None:
    """Kiírja, mely Render-erőforrásokat éri el az API-kulcs (beállítás ellenőrzéséhez)."""
    async with RenderClient(
        settings.render_api_key, settings.http_timeout, settings.max_retries
    ) as render:
        try:
            service = await render.get_service(settings.render_service_id)
            logger.info("Backend: %s | id: %s", service.get("name"), service.get("id"))
        except RenderApiError as exc:
            logger.error("A backend nem kérdezhető le: %s", exc)
        try:
            databases = await render.list_postgres()
        except RenderApiError as exc:
            logger.error("Az adatbázisok nem listázhatók: %s", exc)
            return
        if not databases:
            logger.warning("Az API-kulccsal egyetlen adatbázis sem érhető el.")
        for db in databases:
            logger.info(
                "Adatbázis: %s | id: %s | állapot: %s",
                db.get("name"), db.get("id"), db.get("status"),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Az Okoshűtő karbantartó vezérlője")
    parser.add_argument(
        "command",
        choices=["check", "resources", "backup"],
        help="check: állapotellenőrzés; resources: elérhető erőforrások; backup: mentés és ellenőrzés",
    )
    args = parser.parse_args()

    setup_logging()
    try:
        settings = MaintenanceSettings()
    except ValidationError as exc:
        missing = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
        logger.error("Hiányzó vagy hibás beállítás a .env fájlban: %s", missing)
        return 2

    try:
        if args.command == "check":
            asyncio.run(check_status(settings))
        elif args.command == "resources":
            asyncio.run(show_resources(settings))
        elif args.command == "backup":
            asyncio.run(run_backup(settings))
    except (RenderApiError, RuntimeError, OSError, SQLAlchemyError) as exc:
        logger.error("A művelet leállt: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())