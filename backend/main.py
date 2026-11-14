"""Az Okoshűtő FastAPI-alkalmazása: a REST-végpontok."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db, init_db
from backend.rules import ExpiryStatus
from backend.schemas import (
    ConsumptionCreate,
    ConsumptionOut,
    ProductCreate,
    ProductOut,
    ShoppingItemOut,
    CategoryOut,
)
from backend.seed import seed_categories
from backend.services import ConflictError, FridgeService, NotFoundError

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("okoshuto.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Induláskor létrehozza a táblákat és betölti a kategóriákat."""
    init_db()
    seed_categories()
    logger.info("Az Okoshűtő API elindult.")
    yield


app = FastAPI(title="Okoshűtő API", lifespan=lifespan)


def get_service(db: Session = Depends(get_db)) -> FridgeService:
    """Kérésenként egy szolgáltatásobjektum a kérés saját Session-jével."""
    return FridgeService(db)


# --- hibák átalakítása HTTP-válasszá ----------------------------------

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


# --- végpontok --------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Állapotellenőrzés (nem számít az alkalmazási végpontok közé)."""
    return {"status": "ok"}


@app.get("/products", response_model=list[ProductOut])
def list_products(
    category_id: int | None = None,
    status_filter: ExpiryStatus | None = Query(default=None, alias="status"),
    service: FridgeService = Depends(get_service),
) -> list[ProductOut]:
    """Termékek listája; szűrhető kategóriára és lejárati státuszra."""
    today = date.today()
    products = [ProductOut.from_model(p, today) for p in service.list_products(category_id)]
    if status_filter is not None:
        products = [p for p in products if p.status == status_filter]
    return products


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, service: FridgeService = Depends(get_service)) -> ProductOut:
    """Egy termék részletei."""
    return ProductOut.from_model(service.get_product(product_id), date.today())


@app.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, service: FridgeService = Depends(get_service)) -> ProductOut:
    """Új termék felvétele."""
    return ProductOut.from_model(service.create_product(data), date.today())


@app.post(
    "/products/{product_id}/consumptions",
    response_model=ConsumptionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_consumption(
    product_id: int, data: ConsumptionCreate, service: FridgeService = Depends(get_service)
) -> ConsumptionOut:
    """Fogyasztás rögzítése egy termékből."""
    return ConsumptionOut.model_validate(service.add_consumption(product_id, data, date.today()))


@app.get("/shopping-list", response_model=list[ShoppingItemOut])
def shopping_list(
    reference_date: date | None = None, service: FridgeService = Depends(get_service)
) -> list[ShoppingItemOut]:
    """Bevásárlólista a témaspecifikus szabály alapján."""
    items = service.shopping_list(reference_date or date.today())
    return [ShoppingItemOut.model_validate(item) for item in items]

@app.get("/categories", response_model=list[CategoryOut])
def list_categories(service: FridgeService = Depends(get_service)) -> list[CategoryOut]:
    """Az összes kategória listája (pl. a felület legördülő menüjéhez)."""
    return [CategoryOut.model_validate(c) for c in service.list_categories()]