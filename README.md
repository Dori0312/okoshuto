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
- az elfogyott termékek alapból rejtettek, megjelenítve pirossal jelöltek
- lejárt vagy elfogyott termékek kidobása (törlés megerősítéssel)
- diagram: termékek száma kategóriánként, lejárati státusz szerint

### Témaspecifikus szabály (`backend/rules.py`)

| | |
|---|---|
| **Bemenet** | termékek, az utolsó 14 nap fogyasztása, referencia-dátum, küszöbértékek |
| **Eredmény 1** | lejárati státusz: lejárt, ha a lejárat a referencia-nap előtt van; hamarosan lejár, ha legfeljebb 3 napon belül (a mai nap is) |
| **Eredmény 2** | bevásárlólista: az a termék kerül rá, amely a napi átlagfogyás alapján 3 napon belül kifogy, vagy a minimum mennyiség alá esett; javasolt mennyiség = 7 napi fogyasztás (de legalább a minimum) − meglévő készlet |
| **Feltételek** | a lejárt termék nem számít készletnek |
| **Korlátok** | fogyasztási adat nélkül csak a minimum mennyiség számít; lejárati dátum nélküli termék mindig `RENDBEN`; negatív mennyiség esetén `ValueError` |

### Adatforrások
Saját adatbevitel a Streamlit-felületen (vagy közvetlenül az API-n) keresztül.
A kategóriákat (`Tejtermék`, `Zöldség`, `Hús`, `Felvágott`, `Tojás`, `Üdítő`)
a `backend/seed.py` tölti be a backend indulásakor. A termékadatok fiktív
mintaadatok; valós személyes adatot az alkalmazás nem használ.

### Komponensek
- **Backend:** FastAPI (`backend/`) – REST API, adatellenőrzés, a feldolgozás vezérlése
- **Adatbázis:** SQLAlchemy ORM; helyben SQLite, a felhőben PostgreSQL
- **Frontend:** Streamlit (`frontend/`) – csak a saját API-t hívja, az adatbázist közvetlenül nem éri el
- **Karbantartó program:** (`maintenance/`) – *(készül)*

### Adatút (példa: bevásárlólista)
Streamlit (`frontend/app.py`, `page_shopping_list`) → `ApiClient.get_shopping_list()`
→ `GET /shopping-list` → `main.shopping_list()` → `FridgeService.shopping_list()`
(adatok betöltése az adatbázisból) → `rules.shopping_list()` (számítás)
→ JSON-válasz → táblázat a felületen

### Paradigmák
- **Funkcionális:** a `backend/rules.py` függvényei (`expiry_status`, `daily_usage`,
  `usable_quantity`, `evaluate_product`, `shopping_list`) tiszták: nem módosítják
  a bemenetüket (`frozen` dataclassok), és nem végeznek adatbázis-, fájl- vagy
  hálózati műveletet. Ugyanilyen a `database.normalize_database_url()` és a
  felület `highlight_empty()` függvénye is.
- **Objektumorientált:** a `backend/services.py` `FridgeService` osztálya kezeli
  a lekérdezéseket, a módosításokat és a tranzakciókat (commit/rollback), és ez
  hívja meg a szabályt. A `frontend/api_client.py` `ApiClient` osztálya fogja
  össze a felület összes HTTP-kérését, időkorláttal és hibakezeléssel.
- **Procedurális:** a `seed.seed_categories()` lépésenkénti adatbetöltése;
  a karbantartó program munkafolyamata – *(készül)*

## Használat

### Követelmények
- Python 3.12.16 (helyben, a Renderen és a Streamlit Cloudon is)
- A függőségek pontos verziói: `requirements.txt`

### Telepítés (Windows, PowerShell)
```
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

**Windows 11 megjegyzések** (az Intelligens alkalmazásvezérlés miatt):
- Ha letiltja a `pip.exe`, `uvicorn.exe` stb. indítófájlokat, minden parancs
  `python -m ...` formában futtatható.
- A pyarrow egyik DLL-jét is letilthatja, ilyenkor a Streamlit-felület nem indul
  (`DLL load failed while importing _compute`). Megoldás: az Intelligens
  alkalmazásvezérlés kikapcsolása, vagy Linux-környezet (pl. GitHub Codespaces)
  használata. A felhős telepítést (Linux) ez nem érinti.

### Beállítások
A beállítások a `.env` fájlban vannak (minta: `.env.example`):
- `DATABASE_URL`: az adatbázis címe; alapértéke a helyi SQLite-fájl (`sqlite:///./okoshuto.db`)
- `API_BASE_URL`: a backend címe a felület számára (helyben `http://127.0.0.1:8000`)
- `LOG_LEVEL`: a naplózás szintje (pl. `INFO`)

A helyi és a felhős környezet külön adatbázist használ, ezért a helyben felvett
adatok nem jelennek meg a felhőben, és fordítva. A helyi környezet kísérletezésre,
a felhős a bemutatásra szolgál.

### Adatbázis-inicializálás
A táblákat és a kategóriákat a backend induláskor automatikusan létrehozza.
Külön is futtatható: `python -m backend.seed`

### Indítás
A komponensek külön terminálból indulnak, a projekt gyökérkönyvtárából:
- Backend: `python -m uvicorn backend.main:app --reload`
  (API-dokumentáció: http://127.0.0.1:8000/docs)
- Frontend: `python -m streamlit run frontend/app.py` (http://localhost:8501)
- Tesztek: `python -m pytest`
- Indítószkript: *(készül)*

### API-végpontok

| Metódus | Útvonal | Leírás |
|---|---|---|
| GET | `/categories` | kategóriák listája |
| GET | `/products` | termékek; szűrés: `category_id`, `status` |
| GET | `/products/{product_id}` | egy termék részletei (404, ha nincs) |
| POST | `/products` | új termék (201; 404, ha nincs ilyen kategória; 422 hibás adatra) |
| DELETE | `/products/{product_id}` | termék kidobása a fogyasztási naplójával együtt (204; 404, ha nincs) |
| POST | `/products/{product_id}/consumptions` | fogyasztás rögzítése (409, ha több fogyna, mint amennyi van) |
| GET | `/shopping-list` | bevásárlólista; opcionális `reference_date` |
| GET | `/health` | állapotellenőrzés |

### Felhős elérés és üzemeltetési korlátok
- **Frontend (Streamlit Community Cloud):** https://okoshuto.streamlit.app
- **Backend (Render):** https://okoshuto.onrender.com (API-dokumentáció: `/docs`)
- **Adatbázis:** Render PostgreSQL 18 (Frankfurt), ingyenes csomag

**Korlátok:**
- A Render ingyenes webszolgáltatása 15 perc inaktivitás után leáll; az első kérés
  ilyenkor kb. 1 percig tarthat. A bemutató előtt az alkalmazást el kell indítani.
- Az ingyenes PostgreSQL-példány 30 nap után lejár, és egyszerre csak egy lehet
  belőle. A cseréjét a karbantartó program végzi (lásd: Karbantartás).
- A frontend a backend címét a Streamlit Cloud *Secrets* beállításából olvassa
  (`API_BASE_URL`), a backend az adatbázis címét a Render környezeti változójából
  (`DATABASE_URL`). Egyik sincs a kódban vagy a Git-tárolóban.
- A `main` ágra történő `push` után a Render és a Streamlit Cloud automatikusan
  újratelepít.

## Karbantartás
*(készül)*

## Ellenőrzések
- **Tesztek futtatása:** `python -m pytest`
- **Egységtesztek** (`tests/test_rules.py`): a szabály normál esete, határesetei
  (`@pytest.mark.parametrize`) és hibás bemenete, kézzel kiszámolt elvárt eredményekkel.
- **API-integrációs tesztek** (`tests/test_api.py`): FastAPI `TestClient`-tel,
  minden teszthez újonnan létrehozott SQLite-tesztadatbázissal (a `get_db` függőség
  felülírásával). Ellenőrzik a termékfelvételt, a visszaolvasást, a fogyasztást,
  az adatbázis állapotát, a bevásárlólistát, a kidobást és a hibás kérések
  státuszkódjait. A tesztek nem érik el a fejlesztői vagy a felhős adatbázist.
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
3. **Elfogyás és kidobás külön kezelése.** A fogyasztás csak a mennyiséget csökkenti,
   a termék 0 mennyiséggel is megmarad, mert a bevásárlólista szabálya éppen az
   elfogyott termék fogyasztási előzményéből számol. A felület az elfogyott
   termékeket alapból elrejti, megjelenítve pirossal jelöli. A végleges eltávolítás
   külön művelet (kidobás, `DELETE`): minden termék egy konkrét csomagot jelent,
   az újonnan vásárolt termék új rekord saját előzménnyel, így a kidobott termék
   naplójára már nincs szükség, és vele együtt törlődik. Alternatíva az automatikus
   törlés (elveszne az előzmény) vagy a logikai törlés (`deleted` jelző; megőrizné
   az előzményt, de bonyolítaná a lekérdezéseket). A véletlen törlés ellen a felület
   megerősítést kér.

### Ismert korlátok
- Ugyanaz a termék többször is felvehető (pl. két külön doboz tej eltérő lejárattal);
  a rendszer ezeket külön termékként kezeli, és nem vonja össze.
- A fogyasztási előzmény termékpéldányhoz kötődik, nem terméktípushoz, ezért
  egy újonnan vásárolt termék bevásárlólista-javaslata nulláról indul.

## Források és AI-használat
- **AI-eszköz:** Claude (Anthropic).
- **Felhasználás:** a projekt szerkezetének és lépéseinek megtervezése; a kód nagy
  részének lépésenkénti elkészítése magyarázatokkal; hibakeresés (pl. a Windows
  alkalmazásvezérlése miatti telepítési hibák, Git-problémák); a felhős telepítés
  lépéseinek végigvezetése.
- **Ellenőrzés:** a kód átolvasása és megértése, egységtesztek és integrációs tesztek
  futtatása helyben és a GitHub Actionsben, a végpontok kézi kipróbálása a `/docs`
  oldalon, a felület kipróbálása helyben és a felhőben, szándékosan elrontott
  teszttel a tesztek működésének ellenőrzése.
- **Átvett kód:** nincs; a megoldás a hivatalos FastAPI-, SQLAlchemy-, Streamlit-
  és pytest-dokumentáció mintáit követi.
- **Bővítések:** *(készül)*
