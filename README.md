# Okoshűtő

Python-beadandó – Multi paradigmás programozási nyelvek gyakorlat, 2026/2027. tanév I. félév

## Az alkalmazás

### Cél
Az Okoshűtő nyilvántartja a hűtőben lévő termékeket (mennyiség, lejárati dátum),
rögzíti a fogyasztást, és ebből javaslatot ad arra, mit kell előbb elfogyasztani,
és mit kell megvenni.

### Fő funkciók
- termékek felvétele, listázása, szűrése kategóriára és lejárati státuszra
- fogyasztás rögzítése (a készlet csökken, a fogyasztás naplózódik)
- lejárati státusz minden termékre: `LEJÁRT` / `HAMAROSAN_LEJÁR` / `RENDBEN`
- bevásárlólista a fogyasztási szokások alapján

### Témaspecifikus szabály (`backend/rules.py`)

| | |
|---|---|
| **Bemenet** | termékek, az utolsó 14 nap fogyasztása, referencia-dátum, küszöbértékek |
| **Eredmény 1** | lejárati státusz: lejárt, ha a lejárat a referencia-nap előtt van; hamarosan lejár, ha legfeljebb 3 napon belül (a mai nap is) |
| **Eredmény 2** | bevásárlólista: az a termék kerül rá, amely a napi átlagfogyás alapján 3 napon belül kifogy, vagy a minimum mennyiség alá esett; javasolt mennyiség = 7 napi fogyasztás (de legalább a minimum) − meglévő készlet |
| **Feltételek** | a lejárt termék nem számít készletnek |
| **Korlátok** | fogyasztási adat nélkül csak a minimum mennyiség számít; lejárati dátum nélküli termék mindig `RENDBEN`; negatív mennyiség esetén `ValueError` |

### Adatforrások
Saját adatbevitel az API-n (később a felületen) keresztül. A kategóriákat
(`Tejtermék`, `Zöldség`, `Hús`, `Felvágott`, `Tojás`, `Üdítő`) a `backend/seed.py`
tölti be a backend indulásakor. Valós személyes adatot az alkalmazás nem használ.

### Komponensek
- **Backend:** FastAPI (`backend/`)
- **Adatbázis:** SQLAlchemy ORM; helyben SQLite, a felhőben PostgreSQL
- **Frontend:** Streamlit (`frontend/`) – *(készül)*
- **Karbantartó program:** (`maintenance/`) – *(készül)*

### Adatút (példa: bevásárlólista)
`GET /shopping-list` → `main.shopping_list()` → `FridgeService.shopping_list()`
(adatok betöltése az adatbázisból) → `rules.shopping_list()` (számítás) → JSON-válasz

### Paradigmák
- **Funkcionális:** a `backend/rules.py` függvényei (`expiry_status`, `daily_usage`,
  `usable_quantity`, `evaluate_product`, `shopping_list`) tiszták: nem módosítják
  a bemenetüket (`frozen` dataclassok), és nem végeznek adatbázis-, fájl- vagy
  hálózati műveletet. Ugyanilyen a `database.normalize_database_url()` is.
- **Objektumorientált:** a `backend/services.py` `FridgeService` osztálya kezeli
  a lekérdezéseket, a módosításokat és a tranzakciókat (commit/rollback), és ez
  hívja meg a szabályt.
- **Procedurális:** a `seed.seed_categories()` lépésenkénti adatbetöltése;
  a karbantartó program munkafolyamata – *(készül)*

## Használat



### Követelmények
- Python 3.12.16
- A függőségek pontos verziói: `requirements.txt`

### Telepítés (Windows, PowerShell)
```
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Windows 11-en az Intelligens alkalmazásvezérlés letilthatja a pyarrow egyik DLL-jét, emiatt a Streamlit-felület nem indul (DLL load failed while importing _compute). Megoldás: a funkció kikapcsolása

Megjegyzés: ha a Windows alkalmazásvezérlése letiltja a `pip.exe`, `uvicorn.exe`
stb. indítófájlokat, minden parancs `python -m ...` formában futtatható.

### Beállítások
A beállítások a `.env` fájlban vannak (minta: `.env.example`). A legfontosabb
a `DATABASE_URL`; alapértéke a helyi SQLite-fájl (`sqlite:///./okoshuto.db`).

### Adatbázis-inicializálás
A táblákat és a kategóriákat a backend induláskor automatikusan létrehozza.
Külön is futtatható: `python -m backend.seed`

### Indítás
- Backend: `python -m uvicorn backend.main:app --reload`
  (API-dokumentáció: http://127.0.0.1:8000/docs)
- Frontend: *(készül)*
- Indítószkript: *(készül)*

### API-végpontok

| Metódus | Útvonal | Leírás |
|---|---|---|
| GET | `/categories` | kategóriák listája |
| GET | `/products` | termékek; szűrés: `category_id`, `status` |
| GET | `/products/{product_id}` | egy termék részletei (404, ha nincs) |
| POST | `/products` | új termék (201; 404, ha nincs ilyen kategória; 422 hibás adatra) |
| POST | `/products/{product_id}/consumptions` | fogyasztás rögzítése (409, ha több fogyna, mint amennyi van) |
| GET | `/shopping-list` | bevásárlólista; opcionális `reference_date` |
| GET | `/health` | állapotellenőrzés |

### Felhős elérés és üzemeltetési korlátok
*(készül)*

## Karbantartás
*(készül)*

## Ellenőrzések
- Tesztek futtatása: `python -m pytest`
- Egységtesztek: `tests/test_rules.py` (a szabály normál esete, határesetei és hibás bemenete)

- **GitHub Actions:** minden `push` és `pull_request` után lefut a teljes tesztcsomag
  (`.github/workflows/tests.yml`, Ubuntu, Python 3.12).
- **Dokumentált hibajavítás** (a `ci-hibademo` ágon, amely nincs a felhős telepítéshez kötve):
  - **Tünet:** a CI elbukott; a `test_expiry_status` paraméterezett teszt határesete
    (a ma lejáró termék) `HAMAROSAN_LEJÁR` helyett `LEJÁRT` eredményt kapott.
    Sikertelen futás: IDE_A_PIROS_FUTÁS_LINKJE
  - **Ok:** a `rules.expiry_status` függvényben a `expiry_date < reference_date`
    feltétel helyett `<=` szerepelt (szándékosan előidézett „eggyel elcsúszás” hiba).
  - **Javítás:** a feltétel visszaállítása `<`-re.
  - **Ellenőrzés:** a CI újra lefutott, minden teszt sikeres.
    Sikeres futás: IDE_A_ZÖLD_FUTÁS_LINKJE

## Tervezési döntések
1. **A referencia-dátum paraméter.** A szabály a „mai napot” paraméterként kapja,
   nem a `date.today()`-ből veszi. Alternatíva a rendszeridő közvetlen használata
   lett volna, de akkor a függvény nem lenne tiszta, és a tesztek eredménye
   napról napra változna. Korlát: a hívónak kell megadnia a dátumot.
2. **A lejárt termék nem számít készletnek.** Így a lejárt termék felkerülhet
   a bevásárlólistára. Alternatíva a teljes mennyiség figyelembevétele lett volna,
   de az hamisan mutatná a használható készletet.
3. *(nyitott)* **Ismétlődő termékek kezelése:** mi történjen, ha ugyanazt
   a terméket kétszer veszik fel?

## Források és AI-használat
- **AI-eszköz:** Claude (Anthropic). Felhasználás: kódvázak készítése, hibakeresés.
- **Ellenőrzés:** a kód átolvasása és megértése, egységtesztek futtatása,
  a végpontok kézi kipróbálása a `/docs` oldalon, szándékosan elrontott teszttel
  a tesztek működésének ellenőrzése.
- **Átvett kód:** a hivatalos FastAPI-, SQLAlchemy- és pytest-dokumentáció mintái alapján.
- **Bővítések:** *(készül)*
