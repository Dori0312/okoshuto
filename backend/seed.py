"""Kezdő adatok betöltése: a kategóriák listája."""

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.database import SessionLocal, init_db
from backend.models import Category

KATEGORIAK = ["Tejtermék", "Zöldség", "Hús", "Felvágott", "Tojás", "Üdítő"]


def seed_categories(session_factory: sessionmaker[Session] = SessionLocal) -> None:
    """Felveszi a hiányzó kategóriákat; a már meglévőket nem duplikálja."""
    with session_factory() as db:
        meglevok = set(db.scalars(select(Category.name)))
        for nev in KATEGORIAK:
            if nev not in meglevok:
                db.add(Category(name=nev))
        db.commit()


if __name__ == "__main__":
    init_db()
    seed_categories()
    print("Kategóriák betöltve.")