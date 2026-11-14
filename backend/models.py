"""SQLAlchemy ORM-modellek: Kategória, Termék, Fogyasztási napló."""

from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    """Az aktuális időpont UTC-ben (egységes időzóna)."""
    return datetime.now(timezone.utc)


class Category(Base):
    """Termékkategória, pl. tejtermék, hús, zöldség."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    """Egy termék a hűtőben, aktuális mennyiséggel és lejárati dátummal."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_products_quantity_nonneg"),
        CheckConstraint("min_quantity >= 0", name="ck_products_min_quantity_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    min_quantity: Mapped[float] = mapped_column(Float, default=0)
    expiry_date: Mapped[date | None] = mapped_column(Date)  # None = nem romlandó
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    category: Mapped[Category] = relationship(back_populates="products")
    consumptions: Mapped[list["ConsumptionLog"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

class ConsumptionLog(Base):
    """Egy fogyasztási esemény: melyik termékből, mennyit, melyik napon."""

    __tablename__ = "consumption_logs"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_consumption_amount_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    amount: Mapped[float] = mapped_column(Float)
    consumed_on: Mapped[date] = mapped_column(Date)

    product: Mapped[Product] = relationship(back_populates="consumptions")