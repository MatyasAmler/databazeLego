# Architektura

Jak to celé běží dohromady a proč jsem zvolil zrovna tyhle věci.

## Jak to funguje

Projekt má tři části:

1. **Databáze** (PostgreSQL v Dockeru) ukládá data, hlídá integritu a počítá hodinové souhrny. SQL je v `db/migrations/`.
2. **Simulace** (Python) vytváří data místo skutečného výrobního systému: směnový kalendář, plán zakázek a jednotlivá vážení.
3. **Analýza** (Python) čte souhrny z databáze, hledá problémy a ukládá upozornění do tabulky `alert`. Nakonec se z toho udělá HTML report.

Co se stane po spuštění `python -m hlidac all`:

1. smaže a znovu založí schéma (migrace 001-003),
2. vytvoří kmenová data, směnový kalendář a zakázky a uloží je,
3. generuje vážení a rovnou je posílá do databáze přes `COPY` (v paměti se nikdy nedrží všechny),
4. obnoví hodinové souhrny a pustí tři detektory,
5. uloží upozornění a vytvoří `out/report.html`.

## Struktura

```
db/migrations/       SQL: 001 tabulky, 002 pohledy a souhrny, 003 hromadné nahrávání
docs/                dokumentace a diagramy
scripts/benchmark.py měření rychlosti dotazů
src/hlidac/
  config.py          nastavení z .env
  db.py              připojení a migrace
  domain.py          doménové třídy
  catalog.py         linky, váhy, dílky a výrobky pro simulaci
  shifts.py          rotace 2-2-4 a směnový kalendář
  repository.py      zápis a čtení tabulek
  simulation/        plánovač zakázek, scénáře, generátor vážení
  analysis/          detektory
  report/            HTML report a grafy
  cli.py             příkazová řádka
tests/               testy
```

## Nastavení

Všechno jde přes proměnné prostředí nebo soubor `.env` (vzor je v `.env.example`):

| Proměnná | Výchozí | K čemu |
|---|---|---|
| `DATABASE_URL` | `postgresql://hlidac:hlidac@localhost:5433/hlidac` | připojení k databázi |
| `POSTGRES_PASSWORD` | `hlidac` | heslo pro kontejner |
| `HLIDAC_TIMEZONE` | `Europe/Prague` | časové pásmo |
| `HLIDAC_SIM_START` | `2026-10-05` | první den simulace |
| `HLIDAC_SIM_DAYS` | `16` | kolik dní simulovat |
| `HLIDAC_SEED` | `42` | seed, stejný seed = stejná data |
| `HLIDAC_REPORT_PATH` | `out/report.html` | kam uložit report |

Časy směn, parametry simulace a prahy detektorů jsou v kódu (`catalog.py`, `simulation/scenarios.py` a konstruktory detektorů).

## Testy

- **Bez databáze:** rotace, kalendář (i přes změnu času), výpočet hmotnosti a tolerance, plánovač, generátor.
- **S databází:** omezení v databázi, jestli data po simulaci sedí, oddíly, cizí klíče po hromadném nahrání. Testy si zakládají vlastní databázi `hlidac_test`, takže nepřepíšou hlavní data.
- **Celé období** (`HLIDAC_FULL=1`): analýza musí najít přesně ty tři problémy a upozornění na váhu musí přijít aspoň 2 hodiny předem.

Na GitHubu se testy pouští automaticky přes GitHub Actions (`.github/workflows/ci.yml`).

## Bezpečnost

- databáze poslouchá jen na `127.0.0.1:5433`,
- hesla jsou jen v `.env`, který není v gitu,
- žádné osobní údaje, jen party.

## Proč jsem co zvolil

### PostgreSQL místo SQLite

V minulém projektu (linky-monitor) mi stačilo SQLite v paměti, protože tam byly tisíce řádků. Tady jsou miliony a potřeboval jsem věci, které SQLite neumí:

- rozdělení tabulky po dnech,
- `EXCLUDE` omezení (hlídání, aby se nepřekrývaly směny a zakázky),
- materializované pohledy,
- rychlé hromadné nahrávání.

Zvažoval jsem i MS SQL Server, protože je ve firmách běžný. Na Macu s ARM procesorem se ale v Dockeru používá hůř a PostgreSQL má všechno, co potřebuju, zadarmo. Power BI se k němu umí připojit.

### Rozdělení po dnech, BRIN a hodinové souhrny

Dotazy se většinou ptají buď na souhrny (party, linky, hodiny), nebo na krátký úsek jedné váhy. Proto:

- tabulka je rozdělená po dnech, takže dotaz na pár hodin čte jen jeden oddíl,
- primární klíč (`scale_id`, `measured_at`) se hodí na dotazy na jednu váhu v čase,
- BRIN index na čas je malinký a stačí na rozsahy přes všechny váhy,
- hodinové souhrny v materializovaném pohledu: analýza pak čte 3 tisíce řádků místo 7 milionů (0,8 ms místo 669 ms).

Nevýhoda je, že se souhrny musí po nahrání dat obnovit (1,5 s) a oddíly na další dny se musí zakládat dopředu.

### Hromadné nahrávání

První verze nahrávala 4,5 minuty. Při `COPY` se u každého řádku kontrolovaly tři cizí klíče. Teď je před nahráním odeberu, po nahrání vrátím a databáze je zkontroluje najednou. Nahrání trvá 18 s. Celé to je v jedné transakci, takže když se něco pokazí, nezůstane tabulka bez kontrol.

### Souhrny v SQL, rozhodování v Pythonu

Zkoušel jsem si představit, že by detektory byly celé v SQL. Medián ostatních part, hledání souvislých hodin mimo meze a hlavně skládání českých vět se ale v SQL píšou a testují špatně. A tahat 7 milionů řádků do Pythonu je zase pomalé. Takže:

- SQL pohledy připraví souhrny (stovky až tisíce řádků),
- detektory v Pythonu nad nimi počítají meze, mediány a poměry a skládají text,
- prahy jsou parametry detektorů, ne čísla roztroušená po kódu.

### Anglické názvy, česká dokumentace

V databázi a v kódu mám anglické názvy, protože je to běžné a nedělá to problém s diakritikou. Dokumentace a texty upozornění jsou česky, protože je čtou lidi z provozu.

## Napojení na skutečný provoz

1. místo `WeighingGenerator` třída, která čte vážení z výrobního systému nebo přímo z vah (zbytek kódu zůstane),
2. nahrávat po dávkách, třeba každých 5 minut, oddíly zakládat dopředu a souhrny obnovovat přes `REFRESH ... CONCURRENTLY`,
3. nová upozornění posílat do Teams a Power BI připojit přímo na pohledy.
