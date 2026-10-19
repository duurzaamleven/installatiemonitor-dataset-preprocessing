# Installatiemonitor 3.0 dataset preprocessing

Deze repository bevat software om de RVO/KITE-dataset Installatiemonitor 3.0 om te zetten naar een
klein aantal getypeerde, herleidbare, semantisch eenduidige Parquet-tabellen
(`raw` → `standardized` → `cleaned` → `derived`).

> [!IMPORTANT]
> Dit is **geen open dataset**. Lees [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md) vóór je deze
> code tegen de data draait of resultaten deelt. De **code** valt onder `EUPL-1.2` (zie
> [Licentie](#licentie)); de **data** blijft onder de voorwaarden van RVO en KITE.

## Inhoud

- [Algemene informatie](#algemene-informatie)
- [De dataset verkrijgen](#de-dataset-verkrijgen)
- [Installeren](#installeren)
  - [Vereisten](#vereisten)
- [Gebruik](#gebruik)
  - [Uitvoer](#uitvoer)
  - [Machineleesbare beschrijving: datapackage.json](#machineleesbare-beschrijving-datapackagejson)
  - [Capaciteitseisen en looptijd](#capaciteitseisen-en-looptijd)
- [Documenten](#documenten)
- [Ontwikkelen](#ontwikkelen)
  - [Vereisten](#vereisten-1)
  - [Testen](#testen)
  - [Bijdragen](#bijdragen)
- [Functionaliteit](#functionaliteit)
- [Status](#status)
- [Licentie](#licentie)
- [Credits](#credits)
  - [Gebruik van AI-hulpmiddelen](#gebruik-van-ai-hulpmiddelen)

## Algemene informatie

De Installatiemonitor 3.0-dataset bevat energiegebruik van 6.283 Nederlandse woningen met een
warmtepomp, aangeleverd als één CSV-bestand per woning met kwartier-, uur-, dag- en maandwaarden
door elkaar. Die vorm is niet direct bruikbaar voor analyse: de vier intervaltypen hebben elk een
andere tijdstempelsemantiek, de maandrijen betekenen iets anders dan het informatiedocument
suggereert, en het meegeleverde weer staat per woning gedupliceerd in de reeks.

Deze software is een **preprocessinglaag, geen analyse**. Ze standaardiseert die brondata, legt
vast wát er precies is aangetroffen, en vlagt kwaliteitsproblemen in plaats van ze stilzwijgend te
repareren. Elke afgeleide waarde is terug te voeren op een expliciete, gedocumenteerde keuze; `raw`
wordt nooit overschreven.

Het volledige ontwerp, de geverifieerde bevindingen in de brondata en de openstaande vragen staan
in [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md). Kolomnamen volgen de
[`physiquant__unit`](https://github.com/energietransitie/physiquant__unit)-conventie, zodat de
uitvoer zonder vertaallaag te joinen is met de NeedForHeat-datasets van de onderzoeksgroep
Energietransitie.

## De dataset verkrijgen

De dataset zit niet in deze repository en kan er ook niet in: het is geen open data. Je haalt hem
zelf op bij KITE, het Kennis- en Dataplatform Individuele Technieken van RVO. Dat is een besloten
community op [Pleio](https://kennisdelen.rvo.nl/), dus er zijn drie stappen nodig:

1. Maak een **Pleio-account** aan op [kennisdelen.rvo.nl](https://kennisdelen.rvo.nl/) en log in.
2. Word **lid van de KITE-community**: [kennisdelen.rvo.nl/kite](https://kennisdelen.rvo.nl/kite). De groep is
   publiek zichtbaar, de inhoud niet; lidmaatschap aanvragen kan op de groepspagina zelf of via
   <kite@rvo.nl>.
3. Open in die groep de pagina **Installatiemonitor (ledenversie)** en download
   `dataset_openbaar.zip` (3,2 GB). Directe link, werkt alleen als je ingelogd én lid bent:
   [Installatiemonitor (ledenversie)](https://kennisdelen.rvo.nl/groups/view/1434df6b-d9c4-4d87-8c73-36834399abeb/kennis-en-dataplatform-individuele-technieken-kite/page/view/90c302e3-40ab-4f0d-a54c-e70c8ce78e2c/installatiemonitor-ledenversie).

Zet die zip daarna ongewijzigd in `data/raw/`. **Niet uitpakken**: de pipeline leest hem als
stream, zie [Gebruik](#gebruik).

> [!NOTE]
> Gebruik van de dataset **moet je melden bij KITE** (<kite@rvo.nl>), en uitkomsten moeten onder
> dezelfde voorwaarden met de KITE-community gedeeld worden. Lees
> [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md) voordat je begint.

Achtergrond bij het onderzoek zelf, zonder inloggen te lezen:
[installatiemonitor.nl](https://www.installatiemonitor.nl/) en het RVO-nieuwsbericht
[Warmtepompen verlagen energieverbruik van huishoudens](https://www.rvo.nl/nieuws/warmtepompen-verlagen-energieverbruik).

## Installeren

### Vereisten

- Python 3.11 of nieuwer
- De dataset als `dataset_openbaar.zip` in `data/raw/`, zie
  [De dataset verkrijgen](#de-dataset-verkrijgen)

```bash
pip install -e .                        # basis: bron/io/timestamps/intervals/cleaning/quality/derived
pip install -e ".[weer]"                # + eigen KNMI-ingest (netwerk nodig)
pip install -e ".[gaskwaliteit]"        # + werkelijke calorische-gaswaarde-ingest (netwerk nodig)
pip install -e ".[weer,gaskwaliteit]"   # allebei
pip install -e ".[dev]"                 # + pytest en frictionless (validatie van datapackage.json)
```

## Gebruik

**Uitpakken hoeft niet.** Zet `dataset_openbaar.zip` zoals gedownload in `data/raw/` en laat hem
daar staan: de pipeline leest de klantbestanden rechtstreeks als stream uit het archief. Dat
scheelt 23,9 GB aan losse CSV's op je schijf en kost ongeveer 13% rekentijd. Zie ontwerp §12.11.

```bash
python -m im3_preprocessing.pipeline --sample-size 30 -v                                  # steekproef, met eigen weer- en gaskwaliteit-ingest
python -m im3_preprocessing.pipeline --sample-size 30 --skip-weer --skip-gaskwaliteit -v  # zonder netwerkcalls
python -m im3_preprocessing.pipeline --sample-size 30 --weer-venster-dagen 30 -v          # snelle steekproef-validatie
python -m im3_preprocessing.pipeline -v                                                   # volledige dataset (6.283 woningen)
python -m im3_preprocessing.pipeline --chunk-grootte 10 -v                                # zuiniger met geheugen
python -m im3_preprocessing.pipeline -v                                                   # afgebroken run: hervat vanzelf (zie hieronder)
python -m im3_preprocessing.pipeline --opnieuw -v                                         # begin schoon i.p.v. te hervatten
```

**Hervatten na een afbreking.** Elke chunk schrijft zijn deel atomisch weg naar `data/processed/parts/`
vóórdat de eindtabellen samengevoegd worden (ontwerp §12.9/§12.17). Een afgebroken run (Ctrl-C,
stroomstoring) hoeft bij een volgende poging niet bij chunk 0 te beginnen: chunks die al compleet op
schijf staan worden overgeslagen, gelogd niet stilzwijgend. `--opnieuw` gooit `data/processed/parts/`
weg en begint schoon; nodig als de woningselectie of `--chunk-grootte` sinds de vorige (onvoltooide)
poging is veranderd, al detecteert de pipeline dat verschil ook zelf en negeert dan de oude
deelbestanden vanzelf (`im3_preprocessing.chunking.plan_vingerafdruk`).

**Het rapport herbouwen zonder de pijplijn opnieuw te draaien.** Elke run bewaart de rapportcijfers
naar `data/processed/rapport_accumulator.json`. Een latere wijziging aan alleen de rapporttekst
(`report.py`) kost daardoor geen nieuwe run van uren:

```bash
python -m im3_preprocessing.report --out-dir data/processed --docs-dir docs
```

`--raw-dir` (standaard `data/raw`) mag een map zijn of rechtstreeks het pad naar de zip. Staan de
zip en losse `IM_customer_*.csv` in dezelfde map, dan wint de zip: die is de canonieke ruwe data,
en de losse CSV's mogen dan weg. Met `--raw-bron csv` dwing je het omgekeerde af.

### Uitvoer

De uitvoer komt in `data/processed/`:

```
homes.parquet          : één rij per woning (metadata)
measurements.parquet   : home_id__str, tijdstip_start, interval_type__cat, interval_duur__s,
                         granulariteit__cat, e_net__W
weer.parquet           : weerstation_nr, tijdstip (uur), temp_buiten__degC, wind__m_s_1,
                         ghi__W_m_2, bron__cat
quality.parquet        : home_id__str, tijdstip_start, interval_type__cat, <veld>__flag
derived.parquet        : home_id__str, tijdstip_start, interval_type__cat, g_gebruik__m3_s_1,
                         g_gebruik__W, actual_gas_std_hhv__J_m_3, gas_hhv_bron__cat,
                         weerkoppeling_methode__cat, weervelden
rapport_accumulator.json : de rapportcijfers van deze run, voor `python -m im3_preprocessing.report`
parts/                   : per-chunk deelbestanden (hervatten, ontwerp §12.9/§12.17); mag na een
                           voltooide run blijven staan of weg, allebei is geldig
```

Elke tijdkolom in de uitvoer is tz-aware `Europe/Amsterdam` (ontwerp §12.10): lokale tijd is direct
afleesbaar zonder dat de absolute tijd verloren gaat, want `.dt.tz_convert("UTC")` geeft die terug.

Zie [`docs/datacatalogus.md`](docs/datacatalogus.md) voor de beschrijving van elke uitvoertabel
(rijen, woningen, kolommen, en de exacte regel achter elke kwaliteitsvlag), en de tabel onder
[Documenten](#documenten) voor de overige documentatie.

### Machineleesbare beschrijving: datapackage.json

Naast `docs/datacatalogus.md` (voor mensen) schrijft de pipeline aan het eind van elke run ook
`datapackage.json` in de repo-root: een machineleesbare beschrijving van de vijf uitvoertabellen
volgens de [Frictionless Data Package-standaard](https://datapackage.org/) (kolomnamen, types,
beschrijvingen, vaste categorieën, primaire en vreemde sleutels). Het wordt uit de code gegenereerd
(de schema's in `src/im3_preprocessing/tabellen.py`), niet met de hand bijgehouden; regenereren kan
zonder run met `python -m im3_preprocessing.datapackage`. De licentie erin verwijst naar
[`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md): de data is niet vrij herverspreidbaar.
`tests/test_datapackage.py` borgt dat code, datapackage en de werkelijk geschreven Parquet-bestanden
niet uit de pas lopen.

### Capaciteitseisen en looptijd

Gemeten op de echte dataset (26-08-2026, Windows, 8 cores, 7,8 GB RAM), behalve waar
"extrapolatie" staat.

**Schijf.** 3,2 GB voor de zip in `data/raw/` en **7,2 GB** voor de uitvoer in `data/processed/`
(gemeten over de volledige run). `data/interim/` bevat alleen een JSON-cache van enkele honderden
kB.

**Geheugen.** Het piekgebruik wordt bepaald door `--chunk-grootte`, niet door de omvang van de
dataset: ruwweg 0,35 GB vast plus 17 MB per woning in de chunk. Gemeten over 100 woningen:

| `--chunk-grootte` | tijd | piek-RSS |
|---|---|---|
| 5 | 134 s | 0,43 GB |
| 10 | 129 s | 0,60 GB |
| 25 *(standaard)* | 159 s | 1,07 GB |
| 50 | 161 s | 1,71 GB |
| 100 | 237 s | 2,03 GB |

Een grotere chunk is dus niet sneller. Heb je weinig vrij geheugen, kies dan gerust 10; veel lager
dan 10 laat de Parquet-uitvoer groeien doordat de row groups te klein worden.

**Looptijd.** De eerste volledige run over alle 6.283 woningen duurde **5 uur en 45 minuten**
(26-08-2026, 15:20 tot 21:00, `--chunk-grootte 10`), goed voor 537.470.922 measurement-rijen en
7,2 GB output. Dat is gemeten, geen extrapolatie; een eerdere schatting van 2,5 à 3 uur kwam van
een benchmark van 100 woningen op een verder rustige machine en bleek te optimistisch. Daar komt
eenmalig bij:

- de tijdbereik-scan over de zip: ongeveer 63 s de eerste keer, daarna 0 (gecachet in
  `data/interim/`, en helemaal overgeslagen met `--skip-weer --skip-gaskwaliteit`);
- de KNMI- en calorische-gaswaarde-ingest, afhankelijk van het netwerk en van
  `--weer-venster-dagen` en `--gaskwaliteit-venster-dagen`.

## Documenten

| document | waarover |
|---|---|
| [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md) | de voorwaarden van de dataset, de meldplicht, en hoe je de dataset zelf verkrijgt |
| [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md) | het ontwerp, de geverifieerde bevindingen in de brondata, de keuzes en de open vragen |
| [`ontwerp-intervalsemantiek.md`](ontwerp-intervalsemantiek.md) | begin-labeling van de tijdstempels, alleen vermogens, de correctie van de `m`-rijen |
| [`docs/datacatalogus.md`](docs/datacatalogus.md) | metadatabeschrijving van de uitvoer voor een datacatalogus: werving, meting, tabellen, kolommen, kwaliteit, hoe te laden, beperkingen, met bronvermelding |
| [`docs/data-description.md`](docs/data-description.md) | de bronbestanden en de afwijkingen van RVO's datadictionary |
| [`docs/variable-dictionary.md`](docs/variable-dictionary.md) | de vertaling van ruw naar gestandaardiseerd en het dtype-beleid |
| [`docs/data-quality.md`](docs/data-quality.md) | gegenereerd kwaliteitsrapport van de laatst gedraaide run, door de pipeline zelf geschreven |
| [`datapackage.json`](datapackage.json) | machineleesbare Frictionless Data Package-beschrijving van de uitvoer, door de pipeline zelf gegenereerd |

## Ontwikkelen

### Vereisten

- Python 3.11 of nieuwer
- Aanbevolen: een virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # Linux / macOS
pip install -e ".[weer,gaskwaliteit,dev]"
```

### Testen

```bash
pytest                # offline tests
pytest -m network     # ook de tests die echt KNMI bevragen
```

De testsuite bevat verplichte testcases voor de zomertijdovergangen (ontwerp §2.4), niet als losse
edge-case-opmerking, want dit raakt precies 2 van de 365 dagen per jaar. Ook de belofte dat het
voor de uitkomst niet uitmaakt of de brondata gezipt of uitgepakt is (§12.11) staat als test in
`tests/test_bron.py`, inclusief een end-to-end vergelijking van alle Parquet-tabellen.

### Bijdragen

Werk in een feature branch en dien een pull request in. Houd de bestaande stijl aan: elke keuze die
een aanname bevat, hoort in de code én in `ontwerp-preprocessing.md` te worden toegelicht, met de
verificatie erbij.

Heb je een AI-codeerhulpmiddel gebruikt, zet dat dan in de commit als trailer, bijvoorbeeld
`Co-Authored-By: Claude <noreply@anthropic.com>` of `Assisted-By: <tool>`. Zie
[Gebruik van AI-hulpmiddelen](#gebruik-van-ai-hulpmiddelen).

## Functionaliteit

Klaar:

- inlezen en schema-validatie van alle 6.283 klantbestanden, rechtstreeks uit de zip;
- zomertijd-correcte tijdstempel- en intervalduur-resolutie voor `q`/`h`/`d`/`m`;
- eigen KNMI-ingest met geospatiale interpolatie, plus consistentiecheck tegen het meegeleverde weer;
- werkelijke, per-uur calorische gaswaarde in plaats van een vaste jaarconstante;
- kwaliteitsvlaggen (ontbrekend, negatief, constante reeks, uitschieter) en een gegenereerd
  kwaliteitsrapport;
- chunked verwerking met incrementeel wegschrijven, geschikt voor een gewone laptop;
- hervatbaar na een afbreking (per-chunk deelbestanden, `--opnieuw` om schoon te beginnen, ontwerp
  §12.17);
- het kwaliteitsrapport herbouwen zonder de pijplijn opnieuw te draaien (`python -m
  im3_preprocessing.report`, ontwerp §12.17);
- een datacatalogus van de uitvoer (`docs/datacatalogus.md`) en een uit de code gegenereerde
  `datapackage.json`.

Nog te doen:

- de pipeline één keer over de volledige dataset draaien;
- matchdrempels voor de weer-consistentiecheck extern laten bevestigen (§10.4);
- de geospatiale interpolatie in `needforheat-dutch-weather-software` vectorizen, zodat een
  multi-jaar venster over 28 stations niet onnodig traag is (§7.3, kanttekening).

## Status

Project is: _in ontwikkeling_. De pipeline werkt end-to-end en is over de volledige dataset van
6.283 woningen gedraaid.

## Licentie

De **code** in deze repository valt onder de European Union Public Licence 1.2 (`EUPL-1.2`),
besluit van Kenniscentrum Duurzaam Leven van 19-10-2026. Zie [`LICENSE`](LICENSE) voor de volledige
tekst.

Copyright © 2026 Kenniscentrum Duurzaam Leven, Stichting Milieu Centraal

De licentie van de **data** is een andere zaak en staat daar los van: de Installatiemonitor
3.0-dataset is geen open data, en de ruwe data staat niet in deze repository. Data en resultaten
die uit de data volgen, vallen onder de voorwaarden van RVO en KITE. Zie
[`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md).

## Credits

Deze software is geschreven door:

- Henri ter Hofte · [@henriterhofte](https://github.com/henriterhofte)

De aanpak is geïnspireerd op:

- [needforheat-diagnosis-software](https://github.com/energietransitie/needforheat-diagnosis-software),
  door [@henriterhofte](https://github.com/henriterhofte) en bijdragers, gelicentieerd onder
  [Apache 2.0](https://opensource.org/licenses/Apache-2.0); bron van de
  `filter_id_prop_with_std_zero`- en `filter_static_outliers`-aanpak in `quality.py`, van de
  `property_filter`-aanbeveling in het kwaliteitsrapport, en van `RHC_gas_quality.ipynb` als
  vertrekpunt voor `gaskwaliteit.py`
- [physiquant__unit](https://github.com/energietransitie/physiquant__unit), door
  [@henriterhofte](https://github.com/henriterhofte) en bijdragers; de naamgevingsconventie voor
  alle kolomnamen in dit project
- [dsmr-info](https://github.com/energietransitie/dsmr-info), door
  [@henriterhofte](https://github.com/henriterhofte) en bijdragers; gebruikt om te onderbouwen
  waarom dag- en maandwaarden verder terug kunnen gaan dan kwartier- en uurwaarden (§12.7)

We gebruiken en danken de makers van de volgende broncode en libraries:

- [needforheat-dutch-weather-software](https://github.com/energietransitie/needforheat-dutch-weather-software),
  door [Onderzoeksgroep Energietransitie, Windesheim](https://windesheim.nl/energietransitie),
  gelicentieerd onder [Apache 2.0](https://opensource.org/licenses/Apache-2.0)
- [pandas](https://pandas.pydata.org/), door het pandas development team, gelicentieerd onder
  [BSD-3-Clause](https://opensource.org/licenses/BSD-3-Clause)
- [NumPy](https://numpy.org/), door het NumPy development team, gelicentieerd onder
  [BSD-3-Clause](https://opensource.org/licenses/BSD-3-Clause)
- [Apache Arrow / PyArrow](https://arrow.apache.org/), door de Apache Software Foundation,
  gelicentieerd onder [Apache 2.0](https://opensource.org/licenses/Apache-2.0)
- [SciPy](https://scipy.org/), door de SciPy community, gelicentieerd onder
  [BSD-3-Clause](https://opensource.org/licenses/BSD-3-Clause)
- [Requests](https://requests.readthedocs.io/), door Kenneth Reitz en bijdragers, gelicentieerd
  onder [Apache 2.0](https://opensource.org/licenses/Apache-2.0)
- [tqdm](https://tqdm.github.io/), door Casper da Costa-Luis en bijdragers, gelicentieerd onder
  [MPL-2.0](https://opensource.org/licenses/MPL-2.0) en [MIT](https://opensource.org/licenses/MIT)
- [pytest](https://pytest.org/), door Holger Krekel en bijdragers, gelicentieerd onder
  [MIT](https://opensource.org/licenses/MIT)
- [Hatchling](https://hatch.pypa.io/), door Ofek Lev en bijdragers, gelicentieerd onder
  [MIT](https://opensource.org/licenses/MIT)

We gebruiken en danken de aanbieders van de volgende gegevensbronnen:

- de dataset **Installatiemonitor 3.0**, van [RVO](https://www.rvo.nl/) via de KITE-community
  ([kennisdelen.rvo.nl/kite](https://kennisdelen.rvo.nl/kite)); zie
  [`GEBRUIKSVOORWAARDEN.md`](GEBRUIKSVOORWAARDEN.md) voor de voorwaarden waaronder dat mag
- **uurlijkse weergegevens** van het [KNMI](https://www.knmi.nl/)
- **werkelijke calorische gaswaarden** van
  [mijnenergiedata.nl](https://www.mijnenergiedata.nl/calorische-gaswaarden/); let op: die API is
  niet publiek gedocumenteerd en kan zonder aankondiging wijzigen (ontwerp §12.3)

### Gebruik van AI-hulpmiddelen

Een groot deel van de code, de tests en de documentatie in deze repository is geschreven met
[Claude Code](https://claude.com/claude-code) (Anthropic) als hulpmiddel, onder inhoudelijke
aansturing en review van de auteur. Het hulpmiddel is geen auteur en staat daarom niet in de lijst
hierboven; deze paragraaf legt vast dát het gebruikt is.

Wat dat concreet betekent voor wie deze code beoordeelt of hergebruikt: de bevindingen over de
brondata in [`ontwerp-preprocessing.md`](ontwerp-preprocessing.md) zijn niet aangenomen maar
gemeten, en de aannames die er tóch in zitten staan daar expliciet als openstaande vraag (§10). De
[testsuite](#testen) is de plek waar de gedragsbeloftes van deze code hard zijn vastgelegd.

Commits waarin een AI-codeerhulpmiddel is gebruikt, dragen vanaf 26-08-2026 een
`Co-Authored-By`-trailer met het adres van dat hulpmiddel (voor Claude Code:
`noreply@anthropic.com`). De vier commits van vóór die datum hebben hem nog niet, maar vallen wel
onder de verklaring hierboven. Dit is de conventie waar
[CHAOSS `disclosure`](https://github.com/chaoss/disclosure) op zoekt bij het inventariseren van
AI-bijdragen in open source. Voor een uitgebreidere, machineleesbare variant bestaat de
[AI-disclosure-conventie](https://github.com/ggfevans/ai-disclosure) met
`SPDX-AI-Disclosure`-tags per bestand en een `AI_DISCLOSURE.md` in de repo-root; die is hier
bewust nog niet toegepast, omdat één repo-brede verklaring de lading dekt.
