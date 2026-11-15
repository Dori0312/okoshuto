"""API-integrációs teszt: kérés -> feldolgozás -> tesztadatbázis -> válasz.

A teszt egy külön, minden futásnál újonnan létrehozott SQLite-adatbázist használ,
így nem nyúl a fejlesztői vagy a felhős adatbázishoz.
"""

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.database import get_db, init_db, make_engine
from backend.main import app
from backend.models import ConsumptionLog, Product
from backend.seed import seed_categories


@pytest.fixture
def test_session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    """Friss, üres tesztadatbázis a kategóriákkal; a teszt végén eldobjuk."""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_categories(factory)
    yield factory
    engine.dispose()


@pytest.fixture
def client(test_session_factory) -> Iterator[TestClient]:
    """TestClient, amelyben a get_db függőség a tesztadatbázist adja."""

    def override_get_db() -> Iterator[Session]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app) 
    app.dependency_overrides.clear()


def test_termek_felvetele_fogyasztasa_es_bevasarlolista(client, test_session_factory):
    lejarat = date.today() + timedelta(days=10)

    # 1. Új termék felvétele
    valasz = client.post("/products", json={
        "name": "Tej", "category_id": 1, "quantity": 2, "unit": "l",
        "min_quantity": 1, "expiry_date": lejarat.isoformat(),
    })
    assert valasz.status_code == 201
    termek = valasz.json()
    assert termek["name"] == "Tej"
    assert termek["status"] == "RENDBEN"

    # 2. Visszaolvasás az API-n keresztül
    valasz = client.get(f"/products/{termek['id']}")
    assert valasz.status_code == 200
    assert valasz.json()["quantity"] == 2

    # 3. Fogyasztás: 1,5 l
    valasz = client.post(f"/products/{termek['id']}/consumptions", json={"amount": 1.5})
    assert valasz.status_code == 201

    # 4. Az adatbázis állapota: csökkent a készlet, és létrejött a napló
    with test_session_factory() as db:
        assert db.get(Product, termek["id"]).quantity == 0.5
        assert db.query(ConsumptionLog).count() == 1

    # 5. Bevásárlólista: 0,5 l < 1 l minimum, tehát felkerül
    valasz = client.get("/shopping-list")
    assert valasz.status_code == 200
    assert [t["name"] for t in valasz.json()] == ["Tej"]


def test_hibas_kerest_ertheto_hibaval_utasit_el(client):
    assert client.get("/products/999").status_code == 404
    assert client.post("/products", json={
        "name": "Sajt", "category_id": 1, "quantity": -1, "unit": "db",
    }).status_code == 422