"""A karbantartó vezérlő tartós futási állapota (maintenance/state.json).

Az állapot független a cserélendő adatbázistól és a backendtől: helyi fájlban van,
így egy megszakított csere a rögzített lépésektől folytatható.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STATE_FILE = Path(__file__).with_name("state.json")
LOCK_FILE = Path(__file__).with_name("replace.lock")


@dataclass
class ReplaceRun:
    """Egy adatbázis-csere futásának adatai és már elvégzett lépései."""

    run_id: str
    started_at: str
    source_postgres_id: str
    owner_id: str
    plan: str
    region: str
    version: str
    database_name: str
    new_postgres_name: str
    status: str = "running"  # running / failed / completed
    completed_steps: list[str] = field(default_factory=list)
    backup_path: str | None = None
    new_postgres_id: str | None = None
    error: str | None = None
    finished_at: str | None = None


@dataclass
class ControllerState:
    """A vezérlő teljes állapota: az aktív példány és az utolsó csere."""

    active_postgres_id: str | None = None
    run: ReplaceRun | None = None


def load_state(path: Path = STATE_FILE) -> ControllerState:
    """Beolvassa az állapotot; ha még nincs fájl, üres állapotot ad."""
    if not path.exists():
        return ControllerState()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    run = ReplaceRun(**data["run"]) if data.get("run") else None
    return ControllerState(active_postgres_id=data.get("active_postgres_id"), run=run)


def save_state(state: ControllerState, path: Path = STATE_FILE) -> None:
    """Elmenti az állapotot. Előbb ideiglenes fájlba ír, így egy félbeszakadt írás sem rontja el."""
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class ReplaceLock:
    """Biztosítja, hogy egyszerre csak egy csere fusson (zárolófájllal)."""

    def __init__(self, path: Path = LOCK_FILE) -> None:
        self.path = path

    def __enter__(self) -> "ReplaceLock":
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError(
                f"Már fut egy csere (zárolófájl: {self.path}). Ha biztosan nem fut, töröld a fájlt."
            ) from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)