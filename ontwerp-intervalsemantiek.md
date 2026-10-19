# Ontwerp: intervalsemantiek in de output

**Status:** ontwerp, nog niet geïmplementeerd. Opgesteld 27-08-2026.

**Aanleiding.** Bij elke waarde in de output hoort de vraag: waar in het interval hoort dit, en wat
betekent het getal? Op drie punten is dat antwoord nu onjuist of dubbelzinnig:

1. **`tijdstip`** betekent drie verschillende dingen, afhankelijk van `interval_type__cat` (§1);
2. de afgeleide **vermogens zijn voor `m`-rijen een factor ~30 te laag** (§2);
3. de output bevat **energiewaarden naast vermogens**, en `ghi__kWh_m_2` draagt bovendien een
   verkeerde eenheid (§3).

Die drie horen bij elkaar: ze vragen dezelfde migratie en dezelfde rerun, en ze gaan alle drie over
de betekenis van een waarde binnen een interval.

Dit document beschrijft twee correctiepaden die hetzelfde resultaat moeten opleveren:

1. een **eenmalige migratie** van de bestaande output, zodat de run van 7 uur niet over hoeft;
2. een **fix in de pipeline** voor volgende runs, met een gelijkwaardigheidstest tegen pad 1.

---

## 1. Probleem 1: `tijdstip` betekent drie dingen

`tijdstip` gecombineerd met `interval_duur__s` geeft per intervaltype iets anders:

| type | `tijdstip` (voorbeeld) | `interval_duur__s` | wat het interval werkelijk is | betekenis van `tijdstip` |
|---|---|---|---|---|
| `q` | `2023-03-01 01:15+01:00` | 900 | 01:00 tot 01:15 | **einde** |
| `h` | `2023-03-01 02:00+01:00` | 3600 | 01:00 tot 02:00 | **einde** |
| `d` | `2023-01-30 00:00+01:00` | 86400 | 30 jan 00:00 tot 31 jan 00:00 | **begin** |
| `m` | `2022-03-31 00:00+02:00` | 2678400 (30d23h) | **hele maart** 2022 | noch begin, noch einde |

De `m`-rij is de duidelijkste fout: `tijdstip` wijst naar de laatste **dag**, terwijl
`interval_duur__s` de hele **maand** beschrijft. `tijdstip + duur` en `tijdstip - duur` zijn dan
allebei onzin.

### Wat de conventie normaal is

| bron | conventie |
|---|---|
| pandas `resample` | `label="left"` is de default voor uur/kwartier/dag (alleen maand, kwartaal, jaar en week zijn `"right"`) |
| ENTSO-E / IEC 62325 | begin: `TimeStepPosition = start + (Position-1) × Resolution` |
| CF-conventies (klimaatdata) | geen vaste keuze, maar verplicht expliciete `bounds`; leg de grenzen vast in plaats van een conventie aan te nemen |
| de afnemende simulatie (Kenniscentrum Duurzaam Leven) | gebruikt kale `.resample()`, dus impliciet begin |
| KNMI uurgegevens | einde (`HH=1` is het uur 00:00-01:00) |
| IM3 / RVO | einde, voor `q`/`h` |

**Keuze: begin van het interval, voor alle vier de typen.** Dat sluit aan bij pandas, bij de
energiesector en bij de afnemende repo, en maakt de output voor het eerst intern consistent.

### Waarom geen `pd.Interval` en geen `tijdstip_eind`

Beide zijn overwogen en afgevallen op gemeten gronden:

- **`pd.IntervalDtype` kan niet naar Parquet.** Geverifieerd:
  `TypeError: Conversion to arrow with subtype 'datetime64[us, Europe/Amsterdam]' is not supported`.
- **Een aparte `tijdstip_eind`-kolom kost 1,57× op schijf** (gemeten op 500.000 rijen: 5,95 MB tegen
  9,33 MB met snappy). Over 537 M rijen in drie tabellen loopt dat richting 10 GB extra, voor
  informatie die al afleidbaar is.

`tijdstip` (begin) plus het al bestaande `interval_duur__s` is precies de ISO 8601-vorm
`start/duur`: volledig, eenduidig en gratis, want `interval_duur__s` staat er al en comprimeert
bijna weg.

### Kolomnaam

Voorstel: hernoemen naar **`tijdstip_start`**. Een kolomnaam die blijft terwijl zijn betekenis
verandert, is de gevaarlijkste variant: bestaande code blijft draaien en levert stil iets anders.
Hernoemen breekt de contractcontrole bij de afnemer, en dat is precies de bedoeling:
een luide fout in plaats van een stille verschuiving.

**Besloten (27-08-2026): hernoemen naar `tijdstip_start`.** Als de voorkeur later toch uitgaat
naar `tijdstip` behouden, dan moet de afnemende repo actief geïnformeerd worden vóór de migratie
draait, want dan verandert de betekenis zonder dat de contractcheck aanslaat.

---

## 2. Probleem 2: de vermogens van `m`-rijen zijn een factor ~30 te laag

`derived.build_derived()` rekent voor elke rij `energie / interval_duur__s`. Maar §2.1 van het
hoofdontwerp heeft vastgesteld dat een `m`-waarde **geen maandtotaal is maar het gemiddelde
dagverbruik van die maand**. Er wordt dus een dagwaarde gedeeld door een maandduur.

Gemeten op woning 1000 in de volledige run:

| maand | `e_net__kWh` m-rij | gemiddelde d-rij | `e_net__W` m-rij | gemiddelde d-rij | fout |
|---|---|---|---|---|---|
| 2023-02 | 20,648 | 20,648 | 30,7 | 860,3 | 28,0x te laag |
| 2023-03 | 14,641 | 14,688 | 19,7 | 612,0 | 31,1x te laag |
| 2023-05 | -10,075 | -9,503 | -13,5 | -396,0 | 29,2x te laag |

De energiekolom klopt exact met het daggemiddelde (ratio 1,000), dus §2.1 wordt hiermee op de
volledige dataset bevestigd. De deling is de fout.

Raakt **220.279 rijen** in `e_net__W`, `g_gebruik__m3_s_1` en `g_gebruik__W`.

Wrang: §2.1 waarschuwde hier letterlijk voor, "zouden de vroege periode ~30x te laag laten
meewegen". Die waarschuwing is opgevolgd in de *labeling* (`granulariteit__cat =
maand_gemiddeld_per_dag`) maar niet in de *berekening*. En juist de `m`-rijen dekken de vroegste
periode, waar ze vaak de enige bron zijn.

**Correctie:** voor `interval_type__cat == "m"` delen door **86.400 s**, dus een dag, en niet door
`interval_duur__s`. Voor `q`, `h` en `d` blijft `interval_duur__s` de juiste deler.

`interval_duur__s` zelf blijft ongewijzigd: die beschrijft correct de lengte van het interval waar
de rij over gaat. Het is de betekenis van de *waarde* die afwijkt, niet die van de duur.

---

## 3. Probleem 3: alleen nog vermogens in de output

**Besluit van de opdrachtgever, 27-08-2026: de processed output bevat geen energiewaarden meer
(`__kWh`, `__m3`), alleen het gemiddelde vermogen over het interval (`__W`).**

De onderbouwing is inhoudelijk. Een flow is intervalonafhankelijk, dus `q`, `h`, `d` en `m` worden
direct vergelijkbaar zonder eerst door de duur te delen. En de vraagstukken in de energietransitie
(netbelasting, gelijktijdigheid, piekvermogen, aansluitcapaciteit) gaan over vermogen, niet over
totalen.

### Er gaat geen informatie verloren

Gemeten met een terugrekentest op 2 miljoen waarden per intervaltype
(`E = P x interval_duur__s`, en voor `m` `x 86.400`):

| intervaltype | max relatieve fout | mediaan |
|---|---|---|
| q (15 min) | 1,16e-07 | 0 |
| h (1 uur) | 1,16e-07 | 0 |
| d (1 dag) | 7,76e-08 | 0 |

Dat is de float32-afrondgrens zelf, ongeveer 7 significante cijfers. De energie is dus verliesvrij
terug te rekenen zolang `interval_duur__s` in de tabel blijft, en dat blijft zo.

### Besloten kolomindeling

Het eerdere besluitpunt over het gasveld is beslecht (opdrachtgever, 27-08-2026): **beide gasflows
komen in `derived`, samen met de toegepaste calorische waarde.** Dat de drie uit elkaar afleidbaar
zijn (`g_gebruik__W = g_gebruik__m3_s_1 × actual_gas_std_hhv__J_m_3`) is bewust geaccepteerde
redundantie; daar wordt later eventueel op teruggekomen.

**`measurements`** (standardized, uitsluitend aannamevrije conversies):

| kolom | soort |
|---|---|
| `home_id__str` | sleutel |
| `tijdstip_start` | begin van het interval (§4) |
| `interval_type__cat` | `q`/`h`/`d`/`m` |
| `interval_duur__s` | duur, ongewijzigd |
| `granulariteit__cat` | herkomstlabel, ongewijzigd |
| `e_net__W` | **flow**, vervangt `e_net__kWh` |

**`derived`** (alles wat een externe waarde of koppeling nodig heeft):

| kolom | soort |
|---|---|
| `g_gebruik__m3_s_1` | **flow**, vervangt `g_gebruik__m3` |
| `g_gebruik__W` | **flow**, via de calorische waarde |
| `actual_gas_std_hhv__J_m_3` | toegepaste calorische waarde, intensieve grootheid |
| `gas_hhv_bron__cat` | herkomst van die waarde |
| `weerkoppeling_methode__cat` | koppelmethode |
| `temp_buiten__degC`, `wind__m_s_1` | toestandsgrootheden |
| `ghi__W_m_2` | **flow**, vervangt `ghi__kWh_m_2` (maal 1000) |

`e_net__W` vervalt uit `derived`: die staat dan in `measurements` en stond er nu dubbel in.

**Eén gevolg dat expliciet benoemd moet worden.** `measurements` bevat hiermee wél elektra maar
géén gas, terwijl `g_gebruik__m3_s_1` op zichzelf net zo aannamevrij is als `e_net__W`. De tabel is
dus niet langer een volledige standaardisatie van de twee bronkolommen. Dat is de prijs voor een
`derived` die zelfstandig leesbaar is voor gasanalyse: volumestroom, vermogen en de gebruikte
calorische waarde staan daar bij elkaar. Wil je `g_gebruik__m3_s_1` er tóch ook in `measurements`
bij, dan is dat één regel in de pipeline en ongeveer 2 GB extra op schijf.

### `ghi__kWh_m_2` is geen energie maar een instraling

Gemeten over de volledige run:

| type | max | gemiddeld |
|---|---|---|
| q | 0,975 | 0,1296 |
| h | 0,975 | 0,1289 |
| d | 0,360 | 0,1280 |
| m | 0,288 | 0,1297 |

Het gemiddelde is over alle vier de intervaltypen vrijwel gelijk. Dat is het patroon van een flow,
niet van een totaal: een dagtotaal zou in de zomer 3 a 6 kWh/m2 zijn, geen 0,36. De waarde is de
**gemiddelde instraling in kW/m2**, met een piek van 975 W/m2.

`weer.py` weet dat intern ook: `METRICS` noemt het veld al `ghi__W_m_2`, en pas in
`_naar_weer_kolommen()` wordt door 1000 gedeeld en hernoemd naar `kWh_m_2`. Voor een uurwaarde is
dat numeriek verdedigbaar, maar zodra er over een dag gemiddeld wordt klopt de eenheidsnaam niet
meer.

**Correctie:** de deling door 1000 vervalt en het veld heet overal `ghi__W_m_2`. Dit raakt ook
`weer.parquet` en de matchdrempel `GHI_MATCH_DREMPEL_kWh_m2`, die van 0,05 kWh/m2 naar 50 W/m2 gaat.

*Later gevonden (ontwerp-preprocessing §12.19):* dit gold voor de eigen KNMI-reeks. RVO's eigen
`sun`-kolom, die alleen in de weer-consistentiecheck gebruikt wordt, is wel een uursom in kWh/m² en
moet dus maal 1000; dat gebeurde niet, waardoor de instralingsvergelijking na deze wijziging twee
eenheden naast elkaar legde.

### Wat de flow-conversie NIET verandert

Delen door een positieve duur verandert nooit het teken en nooit of iets exact nul is. Alle
kwaliteitscontroles die daarop leunen blijven dus geldig: `gas_negatief_rapport`,
`gas_voor_koppeling_verdacht_rapport` en de `*_ontbrekend__flag`-kolommen. Die invariant is het
vastleggen waard, want het scheelt een hoop herverificatie.

Wel aan te passen in `quality.py`: `q_h_vs_dag_consistency()` vergelijkt nu kWh-sommen. Dat wordt
`som(P x duur)` tegen `P_dag x duur_dag`, wiskundig equivalent maar een andere formule.
`constante_reeks_flags()` en `uitschieter_flags()` groeperen al per woning en intervaltype,
waarbinnen de duur nagenoeg constant is, dus die veranderen inhoudelijk niet.

### Opslagwinst

`e_net__W` staat nu dubbel: als `e_net__kWh` in `measurements` en als `e_net__W` in `derived`.
Consolideren scheelt één float32-kolom over 537 M rijen, ordegrootte 1 a 2 GB op schijf. Voor gas is
er geen winst, want daar is bewust voor redundantie gekozen. Meegenomen voordeel, niet de reden.

---

## 4. Omzetregels voor `tijdstip`

Per intervaltype, en **niet** uniform. `tijdstip - interval_duur__s` is alleen goed voor `q`/`h`.

| type | regel | toelichting |
|---|---|---|
| `q` | `tijdstip_start = tijdstip - 900 s` | absolute instant, dus zomertijd-neutraal |
| `h` | `tijdstip_start = tijdstip - 3600 s` | idem |
| `d` | `tijdstip_start = tijdstip` | staat al op lokaal middernacht van de juiste dag |
| `m` | `tijdstip_start = eerste dag van diezelfde lokale maand, 00:00 lokaal` | **niet** `tijdstip - duur` |

Voor `q`/`h` mag de aftrek op de absolute (UTC-)instant, want een kwartier en een uur zijn altijd
900 respectievelijk 3600 seconden, ook op een zomertijd-overgangsdag.

Voor `m` is de omzetting: naar `TZ_LOKAAL`, tz-info eraf, `astype("datetime64[M]")` om naar de
eerste van de maand te gaan, en weer lokaliseren. Middernacht op de 1e van een maand is in
Europe/Amsterdam nooit ambigu of niet-bestaand (de overgang valt op 02:00-03:00), dus er is geen
`ambiguous`/`nonexistent`-keuze nodig. Dezelfde redenering als in `timestamps.local_day_window`.

### Wat er NIET verandert

- **`weer.parquet` blijft ongewijzigd.** De KNMI-reeks is al op begin-van-het-uur gelabeld: `HH=1`
  (het uur 00:00-01:00) krijgt bij ons tijdstip 00:00. Onder de nieuwe conventie is dat correct.
- **`homes.parquet` blijft ongewijzigd.** `installatiedatum_wp` is een maandaanduiding, geen
  meetinterval.
- **`interval_duur__s` blijft ongewijzigd.** Die was al goed.

### Gunstig neveneffect: dit repareert de weerkoppeling

De koppeling matcht `h`-rijen exact op tijdstip tegen `weer.parquet`. Nu staat een `h`-rij op het
**einde** (01:00) en de weerwaarde op het **begin** (00:00), dus krijgt de meting over 00:00-01:00
het weer van 01:00-02:00: **structureel een uur te laat**. Zodra beide op begin-van-interval staan,
klopt de match vanzelf.

Dat betekent ook dat de weerkolommen in de huidige `derived.parquet` inhoudelijk fout zijn, niet
alleen verkeerd gelabeld. Zie §5, fase B.

Dit is dezelfde vondst als de "1 uur verschil" uit de consistentiecheck: na correctie matchen 24 van
de 27 stations exact 0,000 tegen de IM3-reeks.

### Openstaande ontwerpvraag, bewust niet hier beslist

Op welk moment hoort het weer voor een `q`-rij geïnterpoleerd te worden? Nu is dat het
eindtijdstip; na deze wijziging wordt het het begintijdstip. Verdedigbaar is dat het **midden** van
het interval het beste is voor een gemiddelde over dat kwartier. Dat is een aparte inhoudelijke
keuze en hoort niet stilzwijgend in een hernoeming mee te liften.

---

## 5. Pad 1: eenmalige migratie van de bestaande output

Doel: de bestaande run van 6.283 woningen bruikbaar maken zonder de 7 uur opnieuw te draaien.

Voorstel: `migreer_intervalsemantiek.py`, een losstaand script, **niet** onderdeel van de pipeline.
Het is eenmalig gereedschap en hoort niet in de reguliere codeweg.

**Het script hoort niet in de PR te landen.** Zodra de pipeline zelf goed is en er een verse
volledige run overheen is gegaan, heeft niemand de migratie nog nodig en is hij alleen nog een
onderhoudslast met een uitnodiging tot verkeerd gebruik. Voorstel: bouw hem op een eigen,
kortlevende branch (`migratie/intervalsemantiek`) die bewust nooit gemerged wordt, of houd hem
lokaal en ongetrackt. De uitkomst die telt is de gemigreerde data plus het bewijs uit §7 dat pad 1
en pad 2 hetzelfde opleveren, niet het gereedschap zelf.

### Fase A: tijdstempels omzetten (goedkoop)

Voor `measurements`, `quality` en `derived`:

1. Lees per row group met `pq.ParquetFile.iter_batches()`. **Streamen is verplicht**: de tabellen
   in één keer in pandas laden geeft `ArrowMemoryError` (gemeten bij 537 M rijen).
2. Pas de omzetregels uit §4 toe, plus de eenheidsconversies uit §2 en §3 op basis van `interval_type__cat`.
3. Hernoem de kolom naar `tijdstip_start`.
4. Schrijf naar `<naam>.parquet.nieuw` met dezelfde `ParquetWriter`-instellingen (snappy,
   `ROW_GROUP_MAX`) en dezelfde vaste categorieën uit `dtypes.py`.
5. Pas na een geslaagde schrijfactie het oude bestand vervangen, zodat een afgebroken migratie de
   bestaande output niet sloopt.

Kosten: één lees- en schrijfronde over ~10 GB, dus ordegrootte tientallen minuten.

### Fase B: weerkolommen in `derived` herberekenen (duurder, optioneel)

Fase A repareert de labels, niet de inhoud. De weerkolommen in `derived` blijven een uur verschoven
tot ze opnieuw gekoppeld zijn.

1. Lees uit de gemigreerde `measurements` de kolommen `home_id__str`, `tijdstip_start`,
   `interval_type__cat` en voeg `weerstation_nr` toe via `homes`.
2. Roep `weer.couple_weather_to_measurements()` aan met de ongewijzigde `weer.parquet`.
3. Overschrijf `weerkoppeling_methode__cat` en de drie weervelden in `derived`.

Kosten: ordegrootte 1 à 2 uur. Nog steeds ruim onder de 7 uur van een volledige run.

**Advies:** doe fase B ook. Zonder fase B is de output half bruikbaar, en juist de weerkoppeling was
gisteren de reden voor de hele herstelronde.

De gaskoppeling hoeft **niet** opnieuw: die reeks is een landelijke uurreeks die met dezelfde
begin-conventie is opgehaald, en `gas_hhv_bron__cat` staat al op 100% `mijnenergiedata_actueel`.
Dat moet in fase B wel expliciet geverifieerd worden in plaats van aangenomen.

---

## 6. Pad 2: de fix in de pipeline

Aanpassingen, klein en op één plek geconcentreerd:

1. **`timestamps.resolve_timestamps()`** levert voortaan het begin van het interval. Dit is de enige
   plek waar de bron-semantiek wordt geïnterpreteerd, dus de wijziging hoort hier en nergens anders.
   De docstring beschrijft nu de bronconventie; die moet blijven staan, met de omrekening erbij.
2. **Kolomnaam** `tijdstip` wordt `tijdstip_start` in `pipeline.build_measurements()`,
   `cleaning.build_quality_table()`, `derived.build_derived()` en in `weer`/`gaskwaliteit`.
3. **`intervals.compute_interval_duur_s()`** blijft ongewijzigd.
4. **`weer.py`** blijft ongewijzigd; de koppeling klopt vanzelf zodra beide kanten begin-gelabeld
   zijn.
5. **Tests**: de bestaande zomertijd-testcases (§2.4) leggen tijdstippen vast en moeten mee. Voeg
   toe: per intervaltype een test dat `tijdstip_start + interval_duur__s` precies het einde van het
   bedoelde interval geeft, inclusief beide overgangsdagen en een maandgrens.

---

## 7. De gelijkwaardigheidstest

Het punt van twee paden is dat ze elkaar controleren.

1. Draai de gefixte pipeline op een kleine steekproef, bijvoorbeeld 20 woningen:
   `--home-ids <20 ids>`, **zonder** `--weer-venster-dagen` en **zonder**
   `--gaskwaliteit-venster-dagen`, zodat het weer- en gasvenster gelijk is aan dat van de volledige
   run. Met een venster-beperking is de vergelijking zinloos.
2. Neem uit de gemigreerde volledige output dezelfde 20 `home_id__str`.
3. Vergelijk met `pandas.testing.assert_frame_equal` na sorteren op
   `(home_id__str, tijdstip_start, interval_type__cat)`, per tabel.

Slaagt dat, dan doen migratie en pipeline aantoonbaar hetzelfde en is de migratie te vertrouwen.

**Twee dingen die de test kunnen laten falen zonder dat er iets mis is,** en die dus vooraf
benoemd moeten worden in plaats van achteraf weggeredeneerd:

- **Chunkgrenzen.** Die mogen niets uitmaken (§12.9: elke kwaliteitscontrole groepeert per woning),
  dus als hier tóch verschil ontstaat is dat een echte bevinding, geen ruis.
- **De gaskwaliteit-API.** `mijnenergiedata.nl` is niet publiek gedocumenteerd en kan tussen twee
  ophaalmomenten andere waarden geven. Wijkt alleen `actual_gas_std_hhv__J_m_3` af, controleer dan
  eerst of de API veranderd is voordat de code verdacht wordt.

---

## 8. Volgorde en documentatie

1. Pad 2 implementeren en de unittests groen krijgen.
2. Pad 1 implementeren en fase A draaien.
3. De gelijkwaardigheidstest uit §5 draaien.
4. Bij succes fase B draaien.
5. `docs/variable-dictionary.md` en `docs/data-description.md` bijwerken: `tijdstip_start` met de
   expliciete vermelding dat dit **afwijkt van de bron** (die `q`/`h` op het einde zet) en met de
   omrekening terug naar de bronconventie.
6. `ontwerp-preprocessing.md` §12.16 met de samenvatting en een verwijzing naar dit document.
7. De afnemende repo informeren: hun contractcontrole moet mee.

Implementatie en tests gebeuren in een aparte stap; dit document bevat bewust nog geen code.
