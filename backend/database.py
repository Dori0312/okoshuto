"""Adatbázis-kapcsolat, munkamenet (Session) és táblák létrehozása."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    """Közös ősosztály minden adatbázismodellhez."""


def normalize_database_url(url: str) -> str:
    """A Render-féle 'postgres://' címet az SQLAlchemy + psycopg 3 formájára alakítja.

    Tiszta függvény: csak a bemenetéből számol, nincs mellékhatása.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def make_engine(url: str) -> Engine:
    """Létrehozza az adatbázismotort a megadott címhez."""
    url = normalize_database_url(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-függőség: kérésenként egy Session, a végén mindig lezárja."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target: Engine | None = None) -> None:
    """Létrehozza a hiányzó táblákat (a meglévő adatokat nem bántja)."""
    from backend import models  # noqa: F401  # a modellek importja regisztrálja a táblákat

    Base.metadata.create_all(bind=target or engine)