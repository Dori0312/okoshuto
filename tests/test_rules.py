"""Egységtesztek a hűtő szabályaihoz (backend/rules.py)."""

from datetime import date, timedelta

import pytest

from backend.rules import (
    ConsumptionData,
    ExpiryStatus,
    ProductData,
    expiry_status,
    shopping_list,
)

MA = date(2026, 11, 14) 


@pytest.mark.parametrize(
    ("lejarat", "elvart"),
    [
        (None, ExpiryStatus.OK),                              
        (MA - timedelta(days=1), ExpiryStatus.EXPIRED),       
        (MA, ExpiryStatus.EXPIRING_SOON),                     
        (MA + timedelta(days=3), ExpiryStatus.EXPIRING_SOON), 
        (MA + timedelta(days=4), ExpiryStatus.OK),            
    ],
)
def test_expiry_status(lejarat, elvart):
    assert expiry_status(lejarat, MA, soon_days=3) == elvart


def test_shopping_list_normal_eset():
    tej = ProductData(1, "Tej", quantity=1, unit="l", min_quantity=1,
                      expiry_date=MA + timedelta(days=5))
    joghurt = ProductData(2, "Joghurt", quantity=4, unit="db", min_quantity=2,
                          expiry_date=MA - timedelta(days=1))  # lejárt
    vaj = ProductData(3, "Vaj", quantity=2, unit="db", min_quantity=1, expiry_date=None)
    # Tejből az utolsó 14 napban napi 0,5 l fogyott (összesen 7 l).
    fogyasztas = [ConsumptionData(1, 0.5, MA - timedelta(days=i)) for i in range(14)]

    lista = shopping_list([tej, joghurt, vaj], fogyasztas, MA)

    assert [(i.name, i.suggested_amount) for i in lista] == [("Joghurt", 2), ("Tej", 2.5)]


def test_negativ_mennyiseg_hibat_ad():
    rossz = ProductData(1, "Sajt", quantity=-1, unit="db", min_quantity=0, expiry_date=None)
    with pytest.raises(ValueError):
        shopping_list([rossz], [], MA)