# Hlídač vážení | Sledování kontrolních vah na balicích linkách

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/pytest-22%20passed-brightgreen?logo=pytest&logoColor=white)](tests/)
[![Architecture](https://img.shields.io/badge/docs-Architecture%20%26%20Benchmarks-orange)](docs/)

> **Databáze a analýza vážení, která včas upozorní na problémy s kvalitou na balicích linkách.**  
> *Projekt je inspirovaný provozem balení stavebnic (PrePack v LEGO Kladno) včetně směnového modelu 2-2-4.*

---

## O projektu v kostce

Na balicích linkách projde kontrolní váhou každý jednotlivý sáček s dílky (rychlostí cca 40 sáčků/min, tedy přes 28 000 sáčků za směnu na jednu linku). Pokud sáček nesedí v toleranci, váha ho automaticky vyřadí.

V běžné praxi se však data z vah často využívají pouze reaktivně – vyhodí se zmetek, ale neřeší se dlouhodobé trendy. Tím unikají skryté problémy: **postupné rozkalibrování vah**, **systematické chyby konkrétní party** nebo **ztráty při rozběhu linek po přestavbách**.

**Hlídač vážení** monitoruje 8 balicích linek v nepřetržitém provozu. Ukládá každé jednotlivé vážení do PostgreSQL (cca **7 milionů záznamů** za 16 dní) a pomocí statistické regulace procesů (**SPC**) automaticky odhaluje závady dříve, než způsobí tisíce zmetků.

Projekt koncepčně navazuje na můj dřívější projekt [linky-monitor](https://github.com/MatyasAmler/linky-monitor), tady jsem se ale víc zaměřil na velké množství dat, optimalizaci SQL a statistické řízení jakosti.

### Hlavní výsledky v číslech

| Výsledek | Hodnota | Co to znamená pro výrobu |
|---|---|---|
| **Předstih varování před rozkalibrováním** | **6 hodin** | Upozorní dříve, než výmět přesáhne 1 %. **Ušetří ~30 000 vyhozených dobrých sáčků.** |
| **Rozlišení příčiny** | **Parta vs. noční směna** | Odhalí, že parta C má v noci 7,8× vyšší chybovost, zatímco ve dne je v normálu (0,2 %). Nejde tedy o únavu noční směny, ale o seřízení/postup. |
| **Detekce špatného rozběhu** | **8,0 % vs. 1,2 %** | Identifikuje linku PP-03 se špatným náběhem po přestavbě (ztráta ~2 960 sáčků za 16 dní). |
| **Rychlost hromadného nahrání (7 mil. řádků)** | **17,6 s** (původně 276 s) | Zrychlení nahrávání dat o **94 %** díky dočasnému odebrání cizích klíčů. |
| **Odezva souhrnných dotazů** | **0,8 ms** (původně 669 ms) | Souhrny z milionů řádků jsou předpočítané v materializovaném pohledu. |
| **Spolehlivost detekce** | **0 falešných poplachů** | Systém ohlásí přesně 3 nasimulované problémy a nic navíc (ověřuje to test). |

---

## Co analýza odhalí (3 scénáře)

Na konci se vytvoří HTML report pro mistra směny, technology kvality i vedoucího výroby.

![Upozornění v reportu](docs/img/report_upozorneni.png)

### 1. Rozkalibrování kontrolní váhy
* **Problém:** Váha CW-105 začne pomalu ujíždět do plusu (+0,01 g/hod). Zpočátku se ještě žádné sáčky nevyhazují, ale střední hodnota se posouvá.
* **Detekce:** Systém každou hodinu spočítá průměrnou odchylku dobrých sáčků od cílové hmotnosti a porovná ji s regulačními mezemi z prvních 4 dnů (průměr ± 3σ). Odchylka překročí mez 2 hodiny po začátku posunu, po dvou hodinách mimo meze přijde upozornění – **6 hodin předtím**, než podíl zmetků překročí 1 %.
* **Bez sledování trendu:** Váha by se seřídila až po hromadném nárůstu zmetků, což by znamenalo vyřazení cca 30 000 balení.

![Regulační diagram](docs/img/regulacni_diagram.png)
*(Modrá křivka průměrné odchylky opustí regulační meze mnohem dříve, než vůbec vyletí červené sloupce výmětu).*

### 2. Problém party vs. únava z noční směny
* **Problém:** Na lince PP-07 přibývá sáčků s chybějícím dílkem.
* **Detekce:** Běžný systém by mohl chybu svést na noční únavu. Hlídač vážení přiřadí každé vážení ke konkrétní směně a partě. Výsledek: parta C má v noci zmetkovitost 2,0 % (ostatní party v noci jen 0,3 %), ale **ve dne má parta C pouhých 0,2 %**. Nejde tedy o problém noční práce, ale o specifický postup či dohled party C při nočním provozu.

### 3. Špatný rozběh po přestavbě zakázky
* **Problém:** Po změně formátu sáčku a přestavbě linky je mírně vyšší chybovost normální.
* **Detekce:** Linka PP-03 vykazuje v prvních 20 minutách výmět 8,0 % (ostatní linky mají v rozběhu kolem 1,2 %). Systém měří *relativní nárůst* oproti běžnému provozu, takže nezamění špatný rozběh s linkou, které pouze driftuje váha.

---

## Technické řešení

Struktura projektu:

```
├── db/migrations/        # SQL migrace (tabulky, indexy, materializované pohledy)
├── docs/                 # Dokumentace, ER/ERA diagramy, diagramy tříd, výsledky
├── scripts/benchmark.py  # Měření rychlosti dotazů a velikosti tabulek
├── src/hlidac/
│   ├── domain.py         # Doménové třídy bez vazby na databázi
│   ├── shifts.py         # Rotace 2-2-4, kalendář směn, změna času
│   ├── repository.py     # Práce s databází, nahrávání přes COPY
│   ├── simulation/       # Generátor vážení a scénářů
│   ├── analysis/         # Detektory (váha, party, rozběh)
│   └── report/           # HTML report a grafy
└── tests/                # 22 testů (logika i databáze)
```

### Databáze (PostgreSQL 16)

Při 7 milionech záznamů už je potřeba myslet na výkon. Použil jsem tyto věci z PostgreSQL:

1. **Rozdělení tabulky po dnech (partitioning):**
   * Tabulka `weighing` je rozdělena do denních oddílů. Dotaz na kratší časový úsek čte jen oddíly, které potřebuje: jedna váha za 6 hodin = 1 oddíl z 18 a **2,7 ms**.
2. **BRIN index místo B-stromu:**
   * Časová razítka vážení přibývají sekvenčně. BRIN index pro 7 mil. řádků zabírá pouhých **0,4 MB** (běžné B-stromové indexy na stejné tabulce mají **207 MB**). Index je 500× menší a na dotazy přes časový rozsah stačí.
3. **Rychlejší hromadné nahrávání (COPY):**
   * Při běžném nahrávání kontroloval PostgreSQL cizí klíče pro každý řádek zvlášť (276 s, tedy přes 4,5 minuty).
   * Dočasným odebráním a následným hromadným obnovením integritních omezení (`ALTER TABLE ... ADD CONSTRAINT`) klesl čas nahrání na **17,6 sekund** (15× rychlejší).
4. **Materializovaný pohled s hodinovými souhrny:**
   * Předpočítané hodinové souhrny zkrátily dotaz z **669 ms na 0,8 ms**, takže report a detektory nemusí pokaždé procházet miliony vážení.
5. **Kontroly přímo v databázi:**
   * Využití `EXCLUDE (line_id WITH =, interval WITH &&)` přes rozšíření `btree_gist` – databáze sama zabrání překrytí dvou směn nebo dvou zakázek na stejné lince.

### Python

* **Časová pásma a přechod na zimní čas:** Směnový kalendář počítá s podzimní změnou času, kdy má noční směna **13 hodin** (ověřuje to test). Časy vážení se počítají v UTC a směny se určují podle zóny `Europe/Prague`.
* **Paměť:** Vážení se posílají do databáze po dávkách 20 000 řádků, v paměti se nikdy nedrží všech 7 milionů najednou.
* **Oddělení od databáze:** Doménové třídy (`Product`, `Scale`, `Shift`) o databázi nic nevědí a obsahují jen logiku výroby (výpočet tolerancí podle nejlehčího dílku v sáčku).

---

## Spuštění

K vyzkoušení stačí mít nainstalovaný **Docker** a **Python 3.9+**.

### Nejrychleji přes make:

```bash
make install
make all
open out/report.html
```

> Příkaz `make all` nastartuje PostgreSQL v Dockeru, provede migrace, vygeneruje 16 dní provozu (7 mil. záznamů), spustí statistické detektory a vytvoří HTML report. Celé to na běžném počítači trvá **cca 20 sekund**.

### Spuštění krok za krokem:

```bash
# 1. Příprava prostředí a instalace
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Spuštění databáze v Dockeru (port 5433)
docker compose up -d --wait

# 3. Spuštění celého zpracování
python -m hlidac all

# 4. Zobrazení výsledného reportu
open out/report.html
```

Jednotlivé fáze lze volat i samostatně:
* `python -m hlidac migrate` – spuštění SQL migrací
* `python -m hlidac simulate` – generování dat a nahrání do DB
* `python -m hlidac analyze` – vyhodnocení anomálií a zápis do tabulky `alert`
* `python -m hlidac report` – export HTML reportu

### Testy a benchmark:

```bash
# Rychlé testy (test nad celým obdobím se přeskočí)
make test

# Všechny testy včetně testu nad celým 16denním obdobím
make test-full

# Měření rychlosti SQL dotazů (EXPLAIN ANALYZE)
python scripts/benchmark.py
```

---

## Dokumentace

Dokumentace jde postupně od zadání po naměřené výsledky:

1. **[Zadání a plán](docs/01_zadani.md)** – Provozní předpoklady, specifikace linek, tolerancí a cílů.
2. **[Konceptuální model](docs/02_konceptualni_model.md)** – ER a ERA diagramy, kardinality a integritní omezení.
3. **[Logické schéma](docs/03_logicke_schema.md)** – Návrh relačních tabulek, normalizace, typy indexů a particionování.
4. **[Diagram tříd](docs/04_diagram_trid.md)** – Objektový návrh, oddělení domény od infrastruktury a detektory.
5. **[Architektura systému](docs/05_architektura.md)** – Průběh zpracování, konfigurace prostředí a zdůvodnění volby PostgreSQL.
6. **[Výsledky a benchmarky](docs/06_vysledky.md)** – Naměřená data, časy dotazů, paměťová náročnost a vyhodnocení.

---

## Použité technologie

* **Jazyk:** Python 3.9+ (standardní knihovna + psycopg)
* **Databáze:** PostgreSQL 16 (particionování, BRIN indexy, materializované pohledy, `btree_gist`)
* **Databázový ovladač:** `psycopg 3` (streaming přes `COPY`)
* **Prostředí a CI:** Docker, Docker Compose, GitHub Actions
* **Testování:** `pytest` (testy logiky i testy nad databází)
* **Dokumentace:** diagramy v draw.io

---

## Co jsem se na projektu naučil

* **Změna času:** Při přechodu na zimní čas vzniká 13hodinová směna. Porovnávání lokálních časů v Pythonu nefungovalo, proto je směnový kalendář navázán na UTC unixové časové značky.
* **Falešný poplach:** První verze detektoru rozběhu linek označila jako problematickou i linku PP-05. Ukázalo se, že linka neměla problém s přestavbou, ale ujížděla jí váha. Úpravou metriky na *relativní nárůst chybovosti vůči běžnému stavu linky* falešný poplach zmizel.
* **BRIN index:** Pochopil jsem, kdy je lepší použít lehký BRIN index místo B-stromu – BRIN index na čas má jen 0,4 MB, zatímco běžné B-stromové indexy na stejné tabulce mají přes 200 MB.

---

## Co by šlo přidat

* **Napojení na skutečnou linku:** Místo simulace číst data z linky (např. přes MQTT nebo OPC UA) – zbytek programu by se měnit nemusel, stačí nová část na načítání dat.
* **Průběžné vyhodnocování:** Místo jednoho vyhodnocení na konci pouštět třeba každých 15 minut `REFRESH MATERIALIZED VIEW CONCURRENTLY` a detektory.
* **Upozornění a dashboard:** Posílat upozornění do MS Teams a napojit Power BI nebo Grafanu na pohledy v PostgreSQL.

---

## Autor

**Matyáš Amler**  
* Zajímám se o backend, databáze a průmyslovou automatizaci
* Web: [matyasamler.cz](https://matyasamler.cz)
* GitHub: [@MatyasAmler](https://github.com/MatyasAmler)
