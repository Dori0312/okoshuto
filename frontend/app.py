"""Az Okoshűtő Streamlit-felülete. Csak a saját FastAPI-backendet hívja."""

import os
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from api_client import ApiClient, ApiError

STATUSES = ["RENDBEN", "HAMAROSAN_LEJÁR", "LEJÁRT"]
STATUS_COLORS = {"RENDBEN": "#2ca02c", "HAMAROSAN_LEJÁR": "#ff7f0e", "LEJÁRT": "#d62728"}
UNITS = ["db", "l", "ml", "kg", "g", "csomag"]


def get_api_base_url() -> str:
    """A backend címe: felhőben a Streamlit secrets-ből, helyben a .env-ből."""
    try:
        return st.secrets["API_BASE_URL"]
    except Exception:  # nincs secrets.toml, vagy nincs benne ez a kulcs
        load_dotenv()
        return os.getenv("API_BASE_URL", "http://localhost:8000")


def call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any | None:
    """Meghív egy API-függvényt; hiba esetén kiírja az üzenetet és None-t ad."""
    try:
        return func(*args, **kwargs)
    except ApiError as exc:
        st.error(str(exc))
        return None


def flash_and_rerun(message: str) -> None:
    """Megjegyzi a sikerüzenetet, és frissíti az oldalt, hogy az új adatok látsszanak."""
    st.session_state["flash"] = message
    st.rerun()


# --- oldalak ------------------------------------------------------------

def highlight_empty(row: pd.Series) -> list[str]:
    """Az elfogyott termék sorát pirosas háttérrel jelöli a táblázatban."""
    style = "background-color: rgba(255, 75, 75, 0.25)" if row["Mennyiség"] == 0 else ""
    return [style] * len(row)


def page_fridge(api: ApiClient) -> None:
    st.header("🧊 A hűtő tartalma")

    categories = call(api.get_categories)
    if categories is None:
        return
    category_ids = {c["name"]: c["id"] for c in categories}

    col1, col2 = st.columns(2)
    category = col1.selectbox("Kategória", ["Összes", *category_ids])
    status = col2.selectbox("Státusz", ["Összes", *STATUSES])
    show_empty = st.checkbox("Elfogyottak mutatása")

    products = call(
        api.get_products,
        category_id=category_ids.get(category),
        status=None if status == "Összes" else status,
    )
    if products is None:
        return
    empty_count = sum(1 for p in products if p["quantity"] == 0)
    if not show_empty:
        products = [p for p in products if p["quantity"] > 0]
    if not products:
        if category == "Összes" and status == "Összes" and empty_count == 0:
            st.info("A hűtő üres. Vegyél fel termékeket az „Új termék” menüpontban!")
        else:
            st.info("Nincs a szűrésnek megfelelő termék.")
        return

    df = pd.DataFrame(products)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Termékek", len(df))
    m2.metric("Hamarosan lejár", int((df["status"] == "HAMAROSAN_LEJÁR").sum()))
    m3.metric("Lejárt", int((df["status"] == "LEJÁRT").sum()))
    m4.metric("Elfogyott", empty_count)

    table = df[["name", "category_name", "quantity", "unit", "expiry_date", "status"]].rename(
        columns={
            "name": "Név", "category_name": "Kategória", "quantity": "Mennyiség",
            "unit": "Egység", "expiry_date": "Lejárat", "status": "Státusz",
        }
    )
    styled = table.style.apply(highlight_empty, axis=1).format({"Mennyiség": "{:g}"})
    st.dataframe(styled, hide_index=True)

    st.subheader("Termékek kategóriánként")
    counts = df.groupby(["category_name", "status"]).size().reset_index(name="darab")
    fig = px.bar(
        counts, x="category_name", y="darab", color="status",
        color_discrete_map=STATUS_COLORS,
        labels={"category_name": "Kategória", "darab": "Termékek száma", "status": "Státusz"},
    )
    st.plotly_chart(fig)


def page_new_product(api: ApiClient) -> None:
    st.header("➕ Új termék")

    categories = call(api.get_categories)
    if not categories:
        return
    category_ids = {c["name"]: c["id"] for c in categories}

    with st.form("new_product", clear_on_submit=True):
        name = st.text_input("Név")
        category = st.selectbox("Kategória", list(category_ids))
        col1, col2, col3 = st.columns(3)
        quantity = col1.number_input("Mennyiség", min_value=0.0, value=1.0, step=0.5)
        unit = col2.selectbox("Egység", UNITS)
        min_quantity = col3.number_input("Minimum mennyiség", min_value=0.0, value=0.0, step=0.5)
        expiry = st.date_input("Lejárati dátum", value=date.today())
        no_expiry = st.checkbox("Nincs lejárati dátuma (pl. só, cukor)")
        submitted = st.form_submit_button("Mentés")

    if submitted:
        if not name.strip():
            st.warning("Add meg a termék nevét!")
            return
        data = {
            "name": name.strip(),
            "category_id": category_ids[category],
            "quantity": quantity,
            "unit": unit,
            "min_quantity": min_quantity,
            "expiry_date": None if no_expiry else expiry.isoformat(),
        }
        if call(api.create_product, data) is not None:
            flash_and_rerun(f"Elmentve: {data['name']}")


def page_consumption(api: ApiClient) -> None:
    st.header("🍽️ Fogyasztás rögzítése")

    products = call(api.get_products)
    if products is None:
        return
    products = [p for p in products if p["quantity"] > 0]  # elfogyottból nem lehet fogyasztani
    if not products:
        st.info("Nincs olyan termék a hűtőben, amiből fogyasztani lehetne.")
        return

    by_id = {p["id"]: p for p in products}
    with st.form("consumption"):
        product_id = st.selectbox(
            "Termék",
            list(by_id),
            format_func=lambda i: f"{by_id[i]['name']} ({by_id[i]['quantity']:g} {by_id[i]['unit']})",
        )
        amount = st.number_input("Mennyiség", min_value=0.01, value=1.0, step=0.5)
        consumed_on = st.date_input("Nap", value=date.today())
        submitted = st.form_submit_button("Rögzítés")

    if submitted and call(api.add_consumption, product_id, amount, consumed_on) is not None:
        flash_and_rerun(f"Rögzítve: {amount:g} {by_id[product_id]['unit']} {by_id[product_id]['name']}")


def page_discard(api: ApiClient) -> None:
    st.header("🗑️ Kidobás")
    st.caption("A kidobott termék a fogyasztási naplójával együtt végleg törlődik.")

    products = call(api.get_products)
    if products is None:
        return
    if not products:
        st.info("A hűtő üres, nincs mit kidobni.")
        return

    by_id = {p["id"]: p for p in products}
    suggested = [p["id"] for p in products if p["status"] == "LEJÁRT" or p["quantity"] == 0]

    def label(product_id: int) -> str:
        p = by_id[product_id]
        expiry = p["expiry_date"] or "nincs lejárat"
        return f"{p['name']} ({p['quantity']:g} {p['unit']}, {expiry}, {p['status']})"

    with st.form("discard"):
        selected = st.multiselect(
            "Kidobandó termékek (alapból a lejártak és az elfogyottak)",
            list(by_id),
            default=suggested,
            format_func=label,
        )
        confirmed = st.checkbox("Biztosan kidobom a kijelölt termékeket")
        submitted = st.form_submit_button("Kidobás")

    if not submitted:
        return
    if not selected:
        st.warning("Nincs kijelölve termék.")
        return
    if not confirmed:
        st.warning("A kidobáshoz jelöld be a megerősítő négyzetet!")
        return

    deleted = [by_id[i]["name"] for i in selected if call(api.delete_product, i)]
    if deleted:
        flash_and_rerun(f"Kidobva: {', '.join(deleted)}")


def page_shopping_list(api: ApiClient) -> None:
    st.header("🛒 Bevásárlólista")
    reference_date = st.date_input("Melyik napra számoljunk?", value=date.today())

    items = call(api.get_shopping_list, reference_date)
    if items is None:
        return
    if not items:
        st.success("Minden van itthon, most nem kell vásárolni. 🎉")
        return

    df = pd.DataFrame(items)
    df["reasons"] = df["reasons"].apply(", ".join)
    st.dataframe(
        df[["name", "suggested_amount", "unit", "usable_quantity", "days_left", "reasons"]].rename(
            columns={
                "name": "Termék", "suggested_amount": "Javasolt mennyiség", "unit": "Egység",
                "usable_quantity": "Használható készlet", "days_left": "Hány napra elég",
                "reasons": "Indoklás",
            }
        ),
        hide_index=True,
    )


# --- főprogram ----------------------------------------------------------

PAGES: dict[str, Callable[[ApiClient], None]] = {
    "🧊 Hűtő tartalma": page_fridge,
    "➕ Új termék": page_new_product,
    "🍽️ Fogyasztás": page_consumption,
    "🛒 Bevásárlólista": page_shopping_list,
    "🗑️ Kidobás": page_discard,
}


def main() -> None:
    st.set_page_config(page_title="Okoshűtő", page_icon="🧊", layout="wide")
    api = ApiClient(get_api_base_url())

    st.sidebar.title("Okoshűtő")
    choice = st.sidebar.radio("Menü", list(PAGES), key="page")
    st.sidebar.caption(f"Backend: {api.base_url}")

    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    PAGES[choice](api)


main()