"""Pydantic-modellek: mit fogad és mit ad vissza az API."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from backend.models import Product
from backend.rules import ExpiryStatus, expiry_status


class CategoryOut(BaseModel):
    """Egy kategória az API válaszában."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ProductCreate(BaseModel):
    """Új termék felvételéhez szükséges adatok (kérés törzse)."""

    name: str = Field(min_length=1, max_length=100)
    category_id: int
    quantity: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=20)
    min_quantity: float = Field(default=0, ge=0)
    expiry_date: date | None = None


class ProductOut(BaseModel):
    """Egy termék az API válaszában, kiszámolt lejárati státusszal."""

    id: int
    name: str
    category_id: int
    category_name: str
    quantity: float
    unit: str
    min_quantity: float
    expiry_date: date | None
    status: ExpiryStatus

    @classmethod
    def from_model(cls, product: Product, reference_date: date) -> "ProductOut":
        """ORM-objektumból API-választ készít."""
        return cls(
            id=product.id,
            name=product.name,
            category_id=product.category_id,
            category_name=product.category.name,
            quantity=product.quantity,
            unit=product.unit,
            min_quantity=product.min_quantity,
            expiry_date=product.expiry_date,
            status=expiry_status(product.expiry_date, reference_date),
        )


class ConsumptionCreate(BaseModel):
    """Fogyasztás rögzítése: mennyit, és melyik napon (alapból ma)."""

    amount: float = Field(gt=0)
    consumed_on: date | None = None


class ConsumptionOut(BaseModel):
    """Egy rögzített fogyasztás az API válaszában."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    amount: float
    consumed_on: date


class ShoppingItemOut(BaseModel):
    """A bevásárlólista egy tétele az API válaszában."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    name: str
    unit: str
    usable_quantity: float
    daily_usage: float
    days_left: float | None
    suggested_amount: float
    reasons: list[str]