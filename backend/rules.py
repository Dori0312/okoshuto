"""A hűtő „agya”: lejárati státusz és bevásárlólista.

Minden függvény tiszta: csak a bemenetéből számol, nem módosítja azt,
és nem használ adatbázist, fájlt vagy hálózatot. A „mai napot” is
paraméterként kapja (reference_date), így a függvény tesztelhető, és
ugyanarra a bemenetre mindig ugyanazt adja.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class ExpiryStatus(StrEnum):
    """Egy termék lejárati állapota."""

    EXPIRED = "LEJÁRT"
    EXPIRING_SOON = "HAMAROSAN_LEJÁR"
    OK = "RENDBEN"


@dataclass(frozen=True)
class ProductData:
    """Egy termék adatai a szabály számára (az ORM-modelltől független)."""

    id: int
    name: str
    quantity: float
    unit: str
    min_quantity: float
    expiry_date: date | None


@dataclass(frozen=True)
class ConsumptionData:
    """Egy fogyasztási esemény adatai."""

    product_id: int
    amount: float
    consumed_on: date


@dataclass(frozen=True)
class ShoppingItem:
    """A bevásárlólista egy tétele, indoklással."""

    product_id: int
    name: str
    unit: str
    usable_quantity: float
    daily_usage: float
    days_left: float | None
    suggested_amount: float
    reasons: tuple[str, ...]


def expiry_status(
    expiry_date: date | None, reference_date: date, soon_days: int = 3
) -> ExpiryStatus:
    """Megadja a termék lejárati státuszát a referencia-naphoz képest.

    - nincs lejárati dátum            -> RENDBEN
    - a lejárat a referencia-nap előtt -> LEJÁRT
    - a lejárat legfeljebb soon_days napon belül (a mai nap is) -> HAMAROSAN_LEJÁR
    - különben                        -> RENDBEN
    """
    if soon_days < 0:
        raise ValueError("A soon_days nem lehet negatív.")
    if expiry_date is None:
        return ExpiryStatus.OK
    if expiry_date <= reference_date:
        return ExpiryStatus.EXPIRED
    if expiry_date <= reference_date + timedelta(days=soon_days):
        return ExpiryStatus.EXPIRING_SOON
    return ExpiryStatus.OK


def daily_usage(
    consumptions: list[ConsumptionData],
    product_id: int,
    reference_date: date,
    window_days: int = 14,
) -> float:
    """Átlagos napi fogyasztás az utolsó window_days napban (a referencia-nappal együtt)."""
    if window_days <= 0:
        raise ValueError("A window_days legyen pozitív.")
    start = reference_date - timedelta(days=window_days)
    total = sum(
        c.amount
        for c in consumptions
        if c.product_id == product_id and start < c.consumed_on <= reference_date
    )
    return total / window_days


def usable_quantity(product: ProductData, reference_date: date) -> float:
    """A ténylegesen felhasználható mennyiség: a lejárt termék nem számít készletnek."""
    if product.quantity < 0 or product.min_quantity < 0:
        raise ValueError(f"Negatív mennyiség: {product.name}")
    if expiry_status(product.expiry_date, reference_date) is ExpiryStatus.EXPIRED:
        return 0.0
    return product.quantity


def evaluate_product(
    product: ProductData,
    consumptions: list[ConsumptionData],
    reference_date: date,
    window_days: int = 14,
    runout_days: int = 3,
    target_days: int = 7,
) -> ShoppingItem | None:
    """Eldönti, kell-e venni a termékből; ha igen, ShoppingItem, ha nem, None."""
    usable = usable_quantity(product, reference_date)
    daily = daily_usage(consumptions, product.id, reference_date, window_days)
    days_left = usable / daily if daily > 0 else None

    reasons: list[str] = []
    if usable < product.min_quantity:
        reasons.append("a minimum mennyiség alatt van")
    if days_left is not None and days_left < runout_days:
        reasons.append(f"{runout_days} napon belül kifogy")
    if not reasons:
        return None

    target = max(daily * target_days, product.min_quantity)
    return ShoppingItem(
        product_id=product.id,
        name=product.name,
        unit=product.unit,
        usable_quantity=usable,
        daily_usage=round(daily, 2),
        days_left=None if days_left is None else round(days_left, 1),
        suggested_amount=round(target - usable, 2),
        reasons=tuple(reasons),
    )


def shopping_list(
    products: list[ProductData],
    consumptions: list[ConsumptionData],
    reference_date: date,
    window_days: int = 14,
    runout_days: int = 3,
    target_days: int = 7,
) -> list[ShoppingItem]:
    """A teljes bevásárlólista, név szerint rendezve."""
    items = (
        evaluate_product(p, consumptions, reference_date, window_days, runout_days, target_days)
        for p in products
    )
    return sorted(filter(None, items), key=lambda item: item.name)