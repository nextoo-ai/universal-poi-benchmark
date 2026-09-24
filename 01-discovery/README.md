# Step 1 — Universal POI Discovery (Rome v1)

Tento balík je prvý krok pipeline: autonómny agent vyhľadá, overí a vyexportuje
nezávislý POI dataset. UI benchmark je oddelený v `../03-ui-benchmark` a dostane až
výsledok konsolidácie z kroku 2. Toto nie je hotový dataset 500 POI; **reálne POI ani
ratingy neboli v tomto balíku vygenerované**.

## Súbory

| Súbor | Účel |
|---|---|
| `AGENT_TASK.md` | Kompletné anglické zadanie odovzdané agentovi |
| `poi.schema.json` | Univerzálny dátový kontrakt (JSON Schema Draft 2020-12) |
| `taxonomy.json` | Kanonické kategórie, podkategórie a tagy, vrátane `hidden_gem` |
| `destination.json` | Profil a približný bbox Ríma; chýbajúce štatistiky zostávajú `null` |
| `benchmark.config.json` | Fixné minimá pre porovnateľný Rome v1 test; návrh adaptívneho modelu pre budúce testy |
| `tools/validate.py` | Offline kontrola schémy, kvót, taxonómie, evidencie, rating metadát a pokrytia metra |
| `tests/test_validator.py` | Regresné testy validačného skriptu |
| `examples/empty-dataset.example.json` | Schémovo platná **prázdna ilustrácia**; zámerne nespĺňa benchmark |
| `examples/poi-record.TEMPLATE-NOT-DATA.json` | Ilustrácia všetkých POI polí; obsahuje placeholdery a **nesmie sa odovzdať ako reálny POI** |
| `discovery-report.template.json` | Šablóna reportu; skript môže vygenerovať vlastný report |
| `EVALUATION.md` | Dvojstupňové hodnotenie a obmedzenia automatickej validácie |

## Spustenie

Z koreňového adresára tohto balíka:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/validate.py examples/empty-dataset.example.json --report /tmp/poi-validation-report.json
```

**Posledný príkaz má skončiť chybovým návratovým kódom 1**, pretože ukážka nemá 500 POI. Pri dodanom datasete:

```bash
python tools/validate.py pois.json --report discovery-report.json
```

Na vytvorenie `pois.json` odovzdaj Discovery agentovi `AGENT_TASK.md` spolu so štyrmi vstupnými JSON súbormi; `tools/validate.py` je referenčná lokálna kontrola. Hotový `pois.json` **nie je** súčasťou tohto balíka, aby sa nevytváral dojem, že test už overil 500 miest.

## Stabilný dátový model

Každý POI má `id`, originálne/alternatívne mená, kategóriu a podkategóriu, tagy, dôvody subjektívnych tagov, WGS84 polohu, adresu, atribúty, rating snapshot, dopravné metadáta, odkazy, priamy obrázok, licenčné metadáta, ľudí súvisiacich s miestom a odkazy na register dôkazových zdrojov. `hidden_gem` je **iba tag** a vyžaduje `tagRationales.hidden_gem`.

Povinné pre **každý POI**: stránka konkrétneho miesta (`links.reference`), priamy Google Maps place link (`links.googleMaps`), asset URL fotografie, stránka pôvodu obrázka a známa licencia alebo `"unknown"`. Neznáma licencia **neznamená oprávnenie na použitie**; vyhodnotí ju Rome Explorer. Pri gastronomických podnikoch okrem `food_market` je povinný reálny Google rating ≥ 4,0 s dátumom a počtom recenzií. Bez doloženého ratingu podnik do verifikovaného datasetu nepatrí.

`ratings.google` je dátová snímka, nie prísľub trvalej aktuálnosti; distribúcia alebo zobrazovanie údajov z Google môže byť obmedzené podmienkami príslušnej služby. Agent nesmie vydávať neoverené skóre za Google rating.

## Univerzálnosť a zmena destinácie

Pre nové mesto/oblasť vytvor novú verziu `destination.json`, `benchmark.config.json` a podľa potreby `taxonomy.json`. Nemiešaj výsledky s rôznymi vstupmi do jedného benchmarkového porovnania. JSON schéma POI ostáva stabilná. Atribút `destinationIds` dovoľuje priradiť POI viacerým destináciám; pre budúci globálny katalóg môže byť ID nezávislé od mesta.

Rome v1 používa **fixný minimálny cieľ 500**, gastronomy 80, culture 150, hidden gems 80; všetko je kontrolované skriptom. `destination.json` nemá vymyslené údaje o počte obyvateľov alebo turizme.

`adaptiveModel` v konfigurácii je **explicitne provizórny a nekalibrovaný**. Príklad sublineárneho výpočtu využíva počet obyvateľov, ročné príchody návštevníkov a rozlohu, ale jeho koeficienty treba najprv overiť na rôznych destináciách. Zatiaľ **sa nepoužíva pri Rome v1**. Ak sa v samostatnej novej verzii zapne `target.mode=adaptive`, skript vyžaduje zdrojované vstupy a odmietne chýbajúce hodnoty namiesto odhadovania. Rome špecifické kvóty sa nesmú preniesť na iné mesto.

Bbox je iba hrubá kontrola súradníc; skutočnú príslušnosť k hraniciam a správne umiestnenie bodu preveruje samostatný geografický audit. `geometry: null` znamená, že polygon nebol poskytnutý. Data model netvrdí, že mesto alebo metropolitná oblasť má konkrétnu hranicu bez zdroja.

## Riziká a hranice automatizácie

Validator **nekontroluje internet** a nepreukazuje pravosť POI, kvalitu zdroja, presnosť geolokácie, identitu zobrazeného obrázka, skutočnú licenciu, aktuálnosť Google ratingu ani funkčnosť všetkých URL. Kontroly odkazu na Google Maps sú iba syntaktické a môžu vyžadovať manuálne preklikanie. Preto je druhá fáza (`EVALUATION.md`) povinná pri finálnom hodnotení agentov.
