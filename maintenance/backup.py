"""Mentés, visszaállítás és ellenőrzés (export–import JSON-fájlba, SQLAlchemy-vel).

A műveletek bármely SQLAlchemy-motorral működnek: a felhős PostgreSQL-lel és
egy helyi, elkülönített próba-adatbázissal (SQLite) is.
"""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Engine, func, select, text
from sqlalchemy.orm import Session

from backend import rules
from backend.database import Base, init_db, make_engine
from backend.models import Category, ConsumptionLog, Product
from backend.services import FridgeService

logger = logging.getLogger(__name__)

BACKUP_FORMAT_VERSION = 1


class TargetNotEmptyError(RuntimeError):
    """A céladatbázisban már vannak alkalmazási adatok."""

# A sorrend számít: előbb a hivatkozott tábla, utána a hivatkozó (idegen kulcsok).
TABLES = [Category, Product, ConsumptionLog]


# --- tiszta segédfüggvények ----------------------------------------------

def serialize_value(value: Any) -> Any:
    """Egy mezőértéket JSON-ba írható formára alakít (dátum -> ISO szöveg, UTC)."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def deserialize_row(model: type[Base], row: dict[str, Any]) -> dict[str, Any]:
    """A JSON-ból olvasott sort az oszloptípusok szerint visszaalakítja."""
    result = dict(row)
    for column in model.__table__.columns:
        value = result.get(column.name)
        if value is None:
            continue
        if isinstance(column.type, DateTime):
            result[column.name] = datetime.fromisoformat(value)
        elif isinstance(column.type, Date):
            result[column.name] = date.fromisoformat(value)
    return result


def find_broken_relations(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Megkeresi azokat a sorokat, amelyek nem létező rekordra hivatkoznak."""
    category_ids = {r["id"] for r in tables["categories"]}
    product_ids = {r["id"] for r in tables["products"]}
    problems = [
        f"products.id={r['id']}: nem létező kategória ({r['category_id']})"
        for r in tables["products"] if r["category_id"] not in category_ids
    ]
    problems += [
        f"consumption_logs.id={r['id']}: nem létező termék ({r['product_id']})"
        for r in tables["consumption_logs"] if r["product_id"] not in product_ids
    ]
    return problems


def rule_result_from_backup(backup: dict[str, Any], reference_date: date) -> list[rules.ShoppingItem]:
    """A témaspecifikus szabály eredménye közvetlenül a mentés adataiból."""
    products = [
        rules.ProductData(
            p["id"], p["name"], p["quantity"], p["unit"], p["min_quantity"],
            date.fromisoformat(p["expiry_date"]) if p["expiry_date"] else None,
        )
        for p in backup["tables"]["products"]
    ]
    consumptions = [
        rules.ConsumptionData(c["product_id"], c["amount"], date.fromisoformat(c["consumed_on"]))
        for c in backup["tables"]["consumption_logs"]
    ]
    return rules.shopping_list(products, consumptions, reference_date)


# --- mentés --------------------------------------------------------------

def export_tables(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """Az összes alkalmazási tábla minden sora, azonosító szerint rendezve."""
    tables: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as conn:
        for model in TABLES:
            table = model.__table__
            rows = conn.execute(select(table).order_by(table.c.id)).mappings()
            tables[table.name] = [
                {key: serialize_value(value) for key, value in row.items()} for row in rows
            ]
    return tables


def create_backup(engine: Engine, source_id: str, backup_dir: Path) -> Path:
    """Elmenti a forrás-adatbázis teljes tartalmát egy JSON-fájlba, és visszaadja az útvonalát."""
    created_at = datetime.now(timezone.utc)
    tables = export_tables(engine)
    backup = {
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": created_at.isoformat(),
        "source_id": source_id,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"okoshuto_{source_id}_{created_at:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Mentés elkészült: %s | rekordok: %s", path, backup["counts"])
    return path


def read_backup(path: Path) -> dict[str, Any]:
    """Beolvas egy mentésfájlt, és ellenőrzi a formátumát."""
    backup = json.loads(path.read_text(encoding="utf-8"))
    if backup.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ValueError(f"Ismeretlen mentésformátum: {backup.get('format_version')}")
    return backup


# --- visszaállítás -------------------------------------------------------

def restore_backup(engine: Engine, backup: dict[str, Any]) -> None:
    """Visszaállítja a mentést egy alkalmazási adatoktól üres adatbázisba.

    Létrehozza a sémát, beírja a sorokat az eredeti azonosítókkal (egy
    tranzakcióban), majd PostgreSQL-en beállítja az azonosító-sorozatokat,
    hogy az új rekordok ne ütközzenek a visszaállítottakkal.
    """
    init_db(engine)
    with Session(engine) as session, session.begin():
        for model in TABLES:
            if session.scalar(select(func.count()).select_from(model)):
                raise TargetNotEmptyError(
                    f"A céladatbázis nem üres ({model.__tablename__}); a visszaállítás leállt."
                )
        for model in TABLES:
            rows = backup["tables"][model.__tablename__]
            if rows:
                session.execute(model.__table__.insert(), [deserialize_row(model, r) for r in rows])
        if engine.dialect.name == "postgresql":
            for model in TABLES:
                name = model.__tablename__
                session.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {name}), 1), "
                    f"(SELECT MAX(id) FROM {name}) IS NOT NULL)"
                ))
    logger.info("Visszaállítás kész: %s", backup["counts"])


# --- ellenőrzés ----------------------------------------------------------

def verify_restore(engine: Engine, backup: dict[str, Any]) -> list[str]:
    """Összeveti a visszaállított adatbázist a mentéssel. Üres lista = minden rendben.

    Ellenőrzi a rekordok tartalmát, a kapcsolatokat, a témaspecifikus szabály
    eredményét (a mentés időpontjával mint referencia-nappal), és hogy egy új
    rekord nem okoz-e azonosító-ütközést (próbaírás, majd visszagörgetés).
    """
    problems: list[str] = []
    restored = export_tables(engine)

    for name, rows in backup["tables"].items():
        if restored.get(name) != rows:
            problems.append(f"{name}: a visszaállított sorok eltérnek a mentéstől")
    problems += find_broken_relations(restored)

    reference_date = datetime.fromisoformat(backup["created_at"]).date()
    expected = rule_result_from_backup(backup, reference_date)
    with Session(engine) as session:
        actual = FridgeService(session).shopping_list(reference_date)
    if actual != expected:
        problems.append("A bevásárlólista-szabály eredménye eltér a mentés alapján számítottól")

    problems += _probe_id_generation(engine, backup)
    return problems


def _probe_id_generation(engine: Engine, backup: dict[str, Any]) -> list[str]:
    """Próbaírás mindhárom táblába; az új azonosító legyen nagyobb a meglévőknél. Visszagörgeti."""
    max_ids = {
        name: max((r["id"] for r in rows), default=0) for name, rows in backup["tables"].items()
    }
    problems: list[str] = []
    with Session(engine) as session:
        try:
            category = Category(name="__azonosito_proba__")
            product = Product(name="__proba__", category=category, quantity=1, unit="db")
            log = ConsumptionLog(product=product, amount=1, consumed_on=date.today())
            session.add_all([category, product, log])
            session.flush()
            for obj, name in ((category, "categories"), (product, "products"), (log, "consumption_logs")):
                if obj.id <= max_ids[name]:
                    problems.append(f"{name}: az új azonosító ({obj.id}) ütközhet a meglévőkkel")
        finally:
            session.rollback()
    return problems




# --- összetett műveletek ---------------------------------------------------

def backup_and_verify(db_url: str, source_id: str, backup_dir: Path) -> Path:
    """Mentés a forrásból, majd ellenőrzés egy elkülönített, helyi próba-adatbázisban.

    1. a forrás teljes tartalmának mentése JSON-fájlba
    2. a mentés visszaállítása egy új, üres helyi SQLite-adatbázisba
    3. a visszaállított adatok összevetése a mentéssel
    """
    source = make_engine(db_url)
    try:
        path = create_backup(source, source_id, backup_dir)
    finally:
        source.dispose()

    backup = read_backup(path)
    trial_path = backup_dir / f"{path.stem}_proba.db"
    trial = make_engine(f"sqlite:///{trial_path.as_posix()}")
    try:
        restore_backup(trial, backup)
        problems = verify_restore(trial, backup)
    finally:
        trial.dispose()

    if problems:
        for problem in problems:
            logger.error("Ellenőrzési hiba: %s", problem)
        raise RuntimeError(f"A mentés ellenőrzése sikertelen; a próba-adatbázis megmaradt: {trial_path}")
    trial_path.unlink()
    logger.info("A mentés ellenőrizve: a helyi próbavisszaállítás sikeres.")
    return path


def restore_and_verify(db_url: str, backup: dict[str, Any]) -> None:
    """Visszaállítás a cél-adatbázisba és ellenőrzés.

    Ha a cél már tartalmazza az adatokat (pl. egy megszakított futás után),
    nem ír újra, csak ellenőriz.
    """
    target = make_engine(db_url)
    try:
        try:
            restore_backup(target, backup)
        except TargetNotEmptyError:
            logger.warning("A cél-adatbázis nem üres; csak ellenőrzés következik.")
        problems = verify_restore(target, backup)
    finally:
        target.dispose()
    if problems:
        for problem in problems:
            logger.error("Ellenőrzési hiba: %s", problem)
        raise RuntimeError("Az új adatbázis tartalma nem egyezik a mentéssel.")
    logger.info("Az új adatbázis ellenőrizve: tartalom, kapcsolatok, szabály és azonosítók rendben.")