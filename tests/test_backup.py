"""Egységtesztek a mentéshez és a visszaállításhoz (helyi SQLite-adatbázisokkal)."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from backend.database import init_db, make_engine
from backend.models import ConsumptionLog, Product
from backend.seed import seed_categories
from maintenance.backup import create_backup, read_backup, restore_backup, verify_restore


@pytest.fixture
def forras(tmp_path):
    """Egy forrás-adatbázis kategóriákkal, termékekkel és fogyasztással."""
    engine = make_engine(f"sqlite:///{tmp_path / 'forras.db'}")
    init_db(engine)
    seed_categories(sessionmaker(bind=engine))
    with Session(engine) as session:
        tej = Product(name="Tej", category_id=1, quantity=1, unit="l", min_quantity=1,
                      expiry_date=date.today() + timedelta(days=5))
        session.add(tej)
        session.flush()
        session.add(ConsumptionLog(product_id=tej.id, amount=0.5, consumed_on=date.today()))
        session.commit()
    yield engine
    engine.dispose()


def test_mentes_es_visszaallitas_ures_adatbazisba(forras, tmp_path):
    utvonal = create_backup(forras, "dpg-teszt", tmp_path)
    mentes = read_backup(utvonal)
    assert mentes["counts"] == {"categories": 6, "products": 1, "consumption_logs": 1}

    cel = make_engine(f"sqlite:///{tmp_path / 'cel.db'}")
    restore_backup(cel, mentes)
    assert verify_restore(cel, mentes) == []  # tartalom, kapcsolatok, szabály, azonosítók rendben
    cel.dispose()


@pytest.mark.parametrize(
    ("tartalom", "hiba"),
    [
        ("ez nem JSON", json.JSONDecodeError),          # sérült fájl
        ('{"format_version": 99}', ValueError),          # ismeretlen formátum
    ],
)
def test_hibas_mentes_beolvasasa_hibat_ad(tmp_path, tartalom, hiba):
    utvonal = tmp_path / "rossz.json"
    utvonal.write_text(tartalom, encoding="utf-8")
    with pytest.raises(hiba):
        read_backup(utvonal)


def test_hianyzo_mentes_hibat_ad(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_backup(tmp_path / "nincs_ilyen.json")


def test_nem_ures_adatbazisba_nem_allit_vissza(forras, tmp_path):
    mentes = read_backup(create_backup(forras, "dpg-teszt", tmp_path))
    with pytest.raises(RuntimeError):
        restore_backup(forras, mentes)  # a forrás nem üres: nem írhatjuk felül


def test_ellenorzes_eszreveszi_az_elterest(forras, tmp_path):
    mentes = read_backup(create_backup(forras, "dpg-teszt", tmp_path))
    cel = make_engine(f"sqlite:///{tmp_path / 'cel.db'}")
    restore_backup(cel, mentes)
    mentes["tables"]["products"][0]["quantity"] = 99  # a mentés szerint más az érték
    assert verify_restore(cel, mentes) != []
    cel.dispose()