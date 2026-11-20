"""Karbantartási döntések tiszta függvényekkel.

Nincs bennük hálózati, fájl- vagy adatbázis-művelet: a bemenetből számolnak,
ezért egyszerűen tesztelhetők. Minden időpont időzónával (UTC) érkezik.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Action(StrEnum):
    """Mit tegyen a vezérlő az ellenőrzés után."""

    NONE = "NINCS_TEENDŐ"
    REPLACE = "CSERE_SZÜKSÉGES"
    WAIT = "VÁRAKOZÁS"


@dataclass(frozen=True)
class DbStatus:
    """Az adatbázis-példány szolgáltatói állapota egy adott pillanatban."""

    reachable: bool
    status: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    """Az ellenőrzés eredménye: a teendő és az indoklása."""

    action: Action
    reason: str


def parse_render_datetime(value: str | None) -> datetime | None:
    """A Render API ISO-időpontját (pl. '2026-12-15T10:00:00Z') datetime-má alakítja."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(
    db: DbStatus,
    now: datetime,
    warning_days: int,
    planned_at: datetime | None = None,
) -> Decision:
    """Eldönti, kell-e adatbázis-cserét indítani.

    - Ha az állapot nem kérdezhető le: VÁRAKOZÁS (kapcsolódási hiba nem indokol cserét).
    - Ha a példány nem 'available': VÁRAKOZÁS (nem cserélünk vakon).
    - Ha elérkezett a tervezett karbantartás ideje: CSERE.
    - Ha a lejáratig legfeljebb warning_days nap van hátra: CSERE.
    - Egyébként: NINCS TEENDŐ.
    """
    for moment in (now, db.expires_at, planned_at):
        if moment is not None and moment.tzinfo is None:
            raise ValueError("Az időpontoknak időzónával (UTC) kell érkezniük.")
    if warning_days < 0:
        raise ValueError("A warning_days nem lehet negatív.")

    if not db.reachable:
        return Decision(Action.WAIT, "Az állapot nem kérdezhető le; ez önmagában nem indokol cserét.")
    if db.status != "available":
        return Decision(Action.WAIT, f"A példány állapota: {db.status}; csere nem indítható.")
    if planned_at is not None and now >= planned_at:
        return Decision(Action.REPLACE, f"Elérkezett a tervezett karbantartás ({planned_at.isoformat()}).")
    if db.expires_at is not None:
        days_left = (db.expires_at - now).total_seconds() / 86400
        if days_left <= warning_days:
            return Decision(Action.REPLACE, f"Közelgő lejárat: {days_left:.1f} nap van hátra.")
        return Decision(Action.NONE, f"A lejáratig {days_left:.1f} nap van hátra.")
    return Decision(Action.NONE, "Nincs lejárati adat, és nincs tervezett karbantartás.")