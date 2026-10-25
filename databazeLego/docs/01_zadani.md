# Zadání a plán

Matyáš Amler, říjen 2026

Tohle jsem si sepsal ještě předtím, než jsem začal cokoli programovat. Jde o to, co má projekt umět, z čeho vycházím a podle čeho poznám, že je hotový.

Data jsou simulovaná a projekt není spojený s žádnou firmou. Provoz jsem se ale snažil nasimulovat co nejblíž realitě balicích linek (PrePack), hlavně směny.

## 1. O co jde

Na konci balicí linky je kontrolní váha. Každý sáček s dílky má danou cílovou hmotnost (součet dílků + fólie). Když sáček váží víc nebo míň, než povoluje tolerance, váha ho vyřadí. Tak se zachytí sáček, ve kterém dílek chybí nebo přebývá.

Linka zváží asi 40 sáčků za minutu, takže přes 28 000 za 12hodinovou směnu. Data z vážení se ale většinou použijí jen na to, aby se vadný sáček vyhodil. Když se nikdo nedívá na dlouhodobý průběh, zůstanou schované tyhle problémy:

1. **Váha se rozkalibruje.** Začne pomalu měřit víc (nebo míň). Dlouho ještě nic nevyhazuje, jen se posouvá průměr. Když se to projeví, vyhazují se i dobré sáčky.
2. **Problém jedné party.** Víc chyb v noci může být problém noci obecně (únava), nebo jen jedné party (postup, seřízení). Bez toho, abych u vážení věděl, která parta zrovna jela, se to nedá rozlišit.
3. **Špatný rozběh po přestavbě.** Po změně výrobku je chvíli víc zmetků, to je normální. Když je to ale na jedné lince výrazně horší než jinde, ztrácí se tam výkon při každé přestavbě.

## 2. Cíle

- uložit **každé vážení** tak, aby u něj byla linka, váha, zakázka, směna a parta,
- poznat rozkalibrovanou váhu **aspoň 2 hodiny předtím**, než výmět za hodinu přeleze 1 %,
- u problému party poznat, jestli jde o partu, nebo o noční směnu,
- najít linku se špatným rozběhem po přestavbě,
- souhrnné dotazy nad celým obdobím (asi 7 milionů vážení) **pod 1 sekundu**,
- výstup srozumitelný i pro mistra: upozornění normálními větami a HTML report.

## 3. Co v projektu je a co ne

Je tam:

- návrh databáze (ER a ERA diagram, logické schéma) a její implementace v PostgreSQL,
- linky, váhy, výrobky, dílky a složení sáčků, party a typy směn,
- směnový kalendář podle rotace 2-2-4,
- simulace 16 dní provozu se třemi schovanými problémy (kap. 5),
- analýza, která problémy najde a uloží jako upozornění,
- HTML report, testy, Docker s databází.

Není tam:

- napojení na skutečný výrobní systém nebo skutečné váhy (místo toho je simulace, ale dá se vyměnit),
- jednotliví zaměstnanci. Pracuju jen s partou jako celkem, takže tam nejsou žádné osobní údaje,
- aplikace na zadávání dat a upozornění v reálném čase.

## 4. Z čeho vycházím

| | |
|---|---|
| Linky | 8 balicích linek, PP-01 až PP-08 |
| Rychlost | 40 sáčků za minutu |
| Váhy | na každé lince jedna, CW-101 až CW-108, rozlišení 0,01 g |
| Směny | denní 6:00-18:00, noční 18:00-6:00 (dvanáctky, provoz nonstop) |
| Rotace | 2-2-4: dvě denní, dvě noční, čtyři dny volna (cyklus 8 dní) |
| Party | čtyři, A-D, v rotaci posunuté o 2 dny. V každé chvíli jede právě jedna. |
| Výrobky | sáčky se 4-9 druhy dílků |
| Tolerance | ± polovina nejlehčího dílku v sáčku, aby se poznalo, i když chybí ten nejlehčí |
| Zakázky | jeden výrobek na jedné lince, 4-10 hodin. Mezi zakázkami přestavba 20-40 minut. |
| Období | 5. 10. 2026 6:00 - 21. 10. 2026 6:00, tedy 16 dní = dva celé cykly rotace. Každá parta má 4 denní a 4 noční. |

Časy směn mám podle toho, jak se jezdí v Kladně. Kdyby se lišily, mění se na jednom místě v kódu.

## 5. Co v datech schovám

Analýza tyhle tři věci musí najít sama a nesmí hlásit nic dalšího.

| | Problém | Jak ho simuluju |
|---|---|---|
| S1 | váha CW-105 (linka PP-05) se rozkalibruje | od 12. 10. 8:00 měří každou hodinu o 0,010 g víc, až do kalibrace 13. 10. 22:00 |
| S2 | parta C na PP-07 v noci | 2 % sáčků s chybějícím dílkem místo běžných 0,25 %, jen noční směny party C |
| S3 | špatný rozběh na PP-03 | prvních 20 minut po přestavbě výmět 8 %. Ostatní linky mají prvních 10 minut asi 2 %. |

## 6. Co má systém umět

- evidovat linky, váhy, výrobky, dílky a složení sáčků,
- spočítat cílovou hmotnost a toleranci výrobku ze složení,
- vytvořit směnový kalendář a přiřadit party podle rotace,
- u každého vážení uložit čas, hmotnost, výsledek (OK / podváha / nadváha), zakázku, váhu a směnu,
- evidovat kalibrace vah,
- najít rozkalibrovanou váhu podle regulačních mezí (SPC),
- porovnat chyby part na stejné lince a stejném typu směny,
- porovnat rozběhy po přestavbě mezi linkami,
- uložit každé zjištění jako upozornění s popisem,
- vytvořit HTML report,
- všechno ovládat z příkazové řádky.

A k tomu:

- PostgreSQL v Dockeru, založení jedním příkazem,
- integrita hlídaná v databázi (cizí klíče, CHECK), ne jen v kódu,
- stejný seed = stejná data, aby šly výsledky zopakovat,
- testy, hesla jen v `.env`,
- v databázi a v kódu anglické názvy, dokumentace česky.

## 7. Kdo by to používal

- **Mistr:** ráno chce vidět, jestli se v noci na některé lince něco zhoršilo.
- **Metrologie / údržba:** chce vědět, kterou váhu zkalibrovat, dřív než začne vyhazovat dobré sáčky.
- **Kvalita:** chce porovnat party a zjistit, jestli jde o postup, nebo o noc.
- **Vedoucí výroby:** chce jeden report za období, kde je hned vidět, kde je problém.

## 8. Rizika

- **Simulace nemusí odpovídat realitě.** Proto jsou parametry na jednom místě a simulace jde vyměnit za skutečná data.
- **Falešná upozornění.** Kdyby systém hlásil moc věcí, nikdo by je nečetl. Prahy proto počítám z běžného provozu a mám test, že se neobjeví nic navíc.
- **Pomalé dotazy nad miliony řádků.** Řeším rozdělením tabulky po dnech, indexy a předpočítanými hodinovými souhrny.

## 9. Kdy je projekt hotový

1. `make all` založí databázi, nasimuluje 16 dní, pustí analýzu a vytvoří report.
2. Analýza najde všechny tři problémy S1-S3 a nic jiného.
3. Upozornění na S1 přijde aspoň 2 hodiny předtím, než výmět přeleze 1 %.
4. S2 je nahlášený jako problém party C, ne noční směny.
5. Souhrnné dotazy běží pod 1 sekundu.
6. Projdou všechny testy.

Jak to dopadlo, je v [06 - Výsledky](06_vysledky.md).

## Pojmy

- **výmět:** sáček, který váha vyřadila (podváha nebo nadváha)
- **odchylka:** naměřená hmotnost mínus cílová hmotnost
- **zakázka:** výroba jednoho výrobku na jedné lince
- **přestavba:** přechod linky na jiný výrobek
- **rozběh:** prvních 20 minut zakázky po přestavbě
- **parta:** lidi, kteří jezdí směny spolu (A-D)
- **SPC, regulační meze:** sleduje se, jestli je proces pořád uvnitř mezí průměr ± 3 směrodatné odchylky, spočítaných z běžného provozu
