"""A hűtő szolgáltatásosztálya: adatbázis-műveletek és a szabály meghívása."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend import rules
from backend.models import Category, ConsumptionLog, Product
from backend.schemas import ConsumptionCreate, ProductCreate

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """A keresett rekord nem létezik (az API 404-et ad rá)."""


class ConflictError(Exception):
    """A művelet ellentmond a meglévő adatoknak (az API 409-et ad rá)."""


class FridgeService:
    """A hűtő üzleti műveletei egy adatbázis-munkameneten (Session) keresztül."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- lekérdezések -------------------------------------------------

    def list_categories(self) -> list[Category]:
        """Az összes kategória név szerint rendezve."""
        return list(self.db.scalars(select(Category).order_by(Category.name)))

    def list_products(self, category_id: int | None = None) -> list[Product]:
        """Termékek listája, opcionálisan egy kategóriára szűrve."""
        query = select(Product).order_by(Product.name)
        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        return list(self.db.scalars(query))

    def get_product(self, product_id: int) -> Product:
        """Egy termék azonosító alapján; ha nincs ilyen, NotFoundError."""
        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"Nincs {product_id} azonosítójú termék.")
        return product

    # --- módosítások --------------------------------------------------

    def create_product(self, data: ProductCreate) -> Product:
        """Új termék felvétele a hűtőbe."""
        if self.db.get(Category, data.category_id) is None:
            raise NotFoundError(f"Nincs {data.category_id} azonosítójú kategória.")
        product = Product(**data.model_dump())
        self.db.add(product)
        self._commit()
        self.db.refresh(product)
        logger.info("Új termék: %s (id=%s)", product.name, product.id)
        return product

    def add_consumption(
        self, product_id: int, data: ConsumptionCreate, today: date
    ) -> ConsumptionLog:
        """Fogyasztás rögzítése: csökkenti a készletet és naplóz."""
        product = self.get_product(product_id)
        if data.amount > product.quantity:
            raise ConflictError(
                f"Csak {product.quantity} {product.unit} van ebből: {product.name}."
            )
        product.quantity -= data.amount
        log = ConsumptionLog(
            product_id=product.id,
            amount=data.amount,
            consumed_on=data.consumed_on or today,
        )
        self.db.add(log)
        self._commit()
        self.db.refresh(log)
        logger.info("Fogyasztás: %s %s %s", product.name, data.amount, product.unit)
        return log

    # --- a szabály meghívása ------------------------------------------

    def shopping_list(
        self, reference_date: date, window_days: int = 14
    ) -> list[rules.ShoppingItem]:
        """Betölti az adatokat, és a rules modul tiszta függvényével kiszámolja a listát."""
        start = reference_date - timedelta(days=window_days)
        products = [
            rules.ProductData(
                p.id, p.name, p.quantity, p.unit, p.min_quantity, p.expiry_date
            )
            for p in self.db.scalars(select(Product))
        ]
        consumptions = [
            rules.ConsumptionData(c.product_id, c.amount, c.consumed_on)
            for c in self.db.scalars(
                select(ConsumptionLog).where(ConsumptionLog.consumed_on > start)
            )
        ]
        return rules.shopping_list(
            products, consumptions, reference_date, window_days=window_days
        )

    # --- belső segédfüggvény ------------------------------------------

    def _commit(self) -> None:
        """Véglegesíti a tranzakciót; hiba esetén visszagörget és továbbdobja a hibát."""
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Adatbázis-hiba, a tranzakció visszagörgetve.")
            raise