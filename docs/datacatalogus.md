# Datacatalogus: Installatiemonitor 3.0-dataset (voorbewerkte uitvoer)

Dit document beschrijft de UITVOER van deze repo: de vijf getypeerde Parquet-tabellen die
`im3_preprocessing` maakt van `dataset_openbaar.zip`, de RVO/KITE-dataset Installatiemonitor 3.0.
Het volgt de opbouw van het
[energietransitie-dataset-template](https://github.com/energietransitie/energy-transition-dataset-template)
en is bedoeld om in een datacatalogus te zetten naast (een verwijzing naar) de dataset zelf.

**Deze repo is niet de data-eigenaar en de data staat hier niet in**, ook niet in voorbewerkte vorm.
De dataset is geen open data; de voorwaarden, en hoe je hem zelf verkrijgt, staan in
[`GEBRUIKSVOORWAARDEN.md`](../GEBRUIKSVOORWAARDEN.md).

Alle kolomnamen volgen de conventie
[`physiquant__unit`](https://github.com/energietransitie/physiquant__unit): eenheid na de dubbele
underscore. Daarnaast gebruikt deze repo `__bool` voor een ja/nee-vlag, `__cat` voor een categorie
en `__str` voor vrije tekst ([Ontwerp] §3 principe 2, §12.2; `dtypes.py`).

**Hoe de beweringen hieronder onderbouwd zijn.** Elke bewering over de dataset, de werving of de
meting heeft een verwijzing tussen rechte haken naar de bronnenlijst in §10, met pagina of
paragraaf. Rijaantallen, woningaantallen, perioden en tellingen zijn afgelezen uit de echte uitvoer
van de volledige run van 6 en 7 september 2026 (6.283 woningen, `--chunk-grootte 25`): uit de
Parquet-footers en de rijgroepstatistieken van `data/processed/` [Uitvoer], of uit het door de
pipeline zelf geschreven kwaliteitsrapport [Kwaliteitsrapport]. Wat een kolom betekent en wanneer
een vlag aan gaat, komt uit de code; de module en functie staan er steeds bij. Waar een bron iets
niet vastlegt, staat er **niet vastgesteld**.

## 1. Wat deze set is

Voorbewerkte slimme-meterdata van woningen met een warmtepomp, uit het onderzoek
**Installatiemonitor 3.0**, uitgevoerd in opdracht van RVO, Techniek Nederland en Netbeheer
Nederland [Eindrapport, p. 1; §1.3, p. 12]. RVO stelt de dataset die aan de basis lag van de
analyses beschikbaar via KITE, het Kennis- en Dataplatform Individuele Technieken: "de slimme meter
gegevens van ruim 6000 woningen, de bijbehorende woningkenmerken en de klimaatgegevens
(dichtstbijzijnde KNMI meetstation)" [RVO 2026, p. 1].

- **Bron:** `dataset_openbaar.zip` (3,20 GB, 23,91 GB uitgepakt, 6.286 leden): een metadatabestand
  `00_IM_meta_data_openbaar.csv` (plus dezelfde tabel als `.xlsx`), het informatiedocument van RVO
  als PDF, en één `IM_customer_<id>.csv` per woning [Datadescr, Bronbestanden; Ontwerp §1, §12.11;
  Uitvoer].
- **Omvang:** 6.283 woningen [Uitvoer; Kwaliteitsrapport, Overzicht], 537.470.922 meetrijen, waarvan
  428.668.153 kwartier (`q`), 104.108.502 uur (`h`), 4.473.988 dag (`d`) en 220.279 maand (`m`)
  [Kwaliteitsrapport, Overzicht].
- **Periode** (`tijdstip_start`, begin van het interval): 1 juni 2021 00:00 t/m 4 februari 2026
  23:45 lokale tijd [Uitvoer; Kwaliteitsrapport, Overzicht]. Het eindrapport noemt januari 2023 t/m
  januari 2026 als verzamelperiode [Eindrapport §3.4, p. 24]; het vroegere deel zijn de historische
  dag- en maandwaarden van vóór de aanmelding (§3).
- **Vijf uitvoertabellen**, alle Parquet in `data/processed/`: `homes` (woningkenmerken),
  `measurements` (elektriciteit), `weer` (eigen KNMI-reeks), `quality` (vlaggen) en `derived` (gas en
  gekoppeld weer); zie §5.
- **Beschikbaarstelling, voorwaarden en melding:** RVO, via KITE. De dataset "is beschikbaar voor onderzoek en
  analyses met een maatschappelijk doel"; gebruik moet gemeld worden bij KITE en uitkomsten moeten
  onder dezelfde voorwaarden met de KITE-community gedeeld worden [RVO 2026, p. 1]. Zie
  [`GEBRUIKSVOORWAARDEN.md`](../GEBRUIKSVOORWAARDEN.md).
- **Niet openbaar gemaakt** "om de onherleidbaarheid van de woningen te waarborgen": bouwjaar, de
  eerste vier cijfers van de postcode, energielabel en huishoudgrootte [RVO 2026, p. 1-4].

## 2. Werving, in- en uitsluitcriteria

- **Werving.** "Deelnemers aan Installatiemonitor worden geworven via de subsidieaanvraag voor de
  Investeringssubsidie duurzame energie en energiebesparing (ISDE). Na de aanvraag van subsidie voor
  een warmtepomp ontvangen geselecteerde bewoners een uitnodiging om deel te nemen" [Eindrapport
  §2.1, p. 15]. Bij de online aanmelding geven deelnemers toestemming om hun slimme-meterdata uit te
  lezen en vullen ze een korte vragenlijst in over woning en installatie [Eindrapport §2.1, p. 15].
- **Inclusiecriterium bouwperiode.** "De selectie van deelnemers richtte zich op woningen gebouwd
  tussen 1920 en 2012" [Eindrapport §3.1.2, p. 19]. Het bouwjaar is niet gepubliceerd [RVO 2026,
  p. 3], dus met deze dataset is niet na te gaan of dat voor elke woning geldt.
- **Hoe "geselecteerde bewoners" gekozen zijn**, en welke opt-out- of uitsluitgronden er bij de
  werving golden: **niet vastgesteld**; het eindrapport noemt geen selectieregel naast de
  bouwperiode.
- **Aantallen.** 6.307 huishoudens meldden zich tussen 2023 en 2026 aan, 4.707 met een hybride en
  1.600 met een all-electric warmtepomp [Eindrapport §3, p. 19]. De openbare dataset bevat 6.283
  woningen [Uitvoer]. In `homes` hebben 4.459 woningen de tag hybride warmtepomp en 1.668 de tag
  all-electric, 20 allebei en 176 geen van beide [Uitvoer]. Het verschil tussen 6.307 en 6.283 is in
  de bronnen niet toegelicht.
- **Geen uitsluiting op datakwaliteit in de openbare set.** Het eindrapport beschrijft voor zijn
  eigen analyses een uitval van aanmelding naar geslaagde analyse (onder meer wisseling van
  energieleverancier, geen historische data, afgesloten gasmeter) [Eindrapport §2.5 en Figuur 2-2,
  p. 17-18]. Dat de openbare set vrijwel alle aanmeldingen bevat en niet alleen de geanalyseerde
  subset, volgt uit de aantallen hierboven; een expliciete uitspraak daarover staat in geen van de
  bronnen. Deze pipeline sluit zelf geen woningen uit: elke woning met een klantbestand komt in de
  uitvoer (`pipeline._run_met_bron`), op de volledige dataset alle 6.283 [Uitvoer].
- **Representativiteit.** "Hoewel de dataset een brede variatie aan woningen bevat, vormt de
  populatie geen volledige afspiegeling van de Nederlandse woningvoorraad. Het is daarentegen een
  goede afspiegeling van de populatie in Nederland die de afgelopen drie jaar een warmtepomp heeft
  gekocht" [Eindrapport §3.8, p. 27]. Deelnemers zijn "relatief vaak voorlopers"; grotere
  eengezinswoningen zijn over- en appartementen ondervertegenwoordigd [Eindrapport §3.8-3.9,
  p. 27-28]. Ruim 95% heeft zonnepanelen en circa 27% laadt thuis een elektrische auto [Eindrapport
  §3.3, p. 23]. Een eigen representativiteitsanalyse doet deze repo bewust niet [Ontwerp §8].

## 3. Meetopstelling

- **Slimme meter, geen extra meetapparatuur.** "In Installatiemonitor wordt uitsluitend
  gebruikgemaakt van data die via de slimme meter beschikbaar is. Er wordt geen extra meetapparatuur
  in woningen geplaatst" [Eindrapport §2.3, p. 16]. De data komt via de P4-poort [Eindrapport,
  Begrippenlijst p. 3; §2.2, p. 15]; BDH haalt haar als Onafhankelijke Diensten Aanbieder (ODA) op
  bij EDSN [Eindrapport §2.1, p. 15].
- **Resolutie.** Vanaf de aanmelding is het elektriciteitsgebruik per kwartier en het gasverbruik
  per uur gemonitord [RVO 2026, p. 2; Eindrapport §2.3, p. 16]. Bij de aanmelding heeft BDH de
  historische meterstanden opgehaald, met een meetinterval van dagen en maanden [RVO 2026, p. 2].
  Die historische reeks gaat aantoonbaar tot ongeveer een jaar terug vóór de eerste kwartier- en
  uurwaarde, en de dagreeks loopt daarna parallel door [Ontwerp §2.3].
- **Aanmelddatum = installatiemaand.** "De aanmelddatum voor het project is aangehouden als het
  moment van installeren van de warmtepomp in de woning", terug te vinden als de installatiemaand in
  de metadata [RVO 2026, p. 2].
- **Verschilstanden, geen meterstanden.** Elke waarde is "de verschilstand met het vorig meetpunt met
  hetzelfde meetinterval", "gecorrigeerd/gecontroleerd voor uitgevallen meetpunten" [RVO 2026,
  p. 2]. De onderliggende cumulatieve standen zijn niet gepubliceerd, en daarom kan deze pipeline
  meterproblemen alleen signaleren, niet herstellen [Ontwerp §12.6, §12.18].
- **Elektriciteit** is het totaal opgenomen verbruik, hoog- en laagtarief en levering en teruglevering
  gecombineerd; "een negatieve waarde is teruglevering" [RVO 2026, p. 2]. Het verbruik van de
  warmtepomp zelf is niet apart gemeten [Eindrapport §2.3, p. 16].
- **Gas** in m³, per uur, dag en maand [RVO 2026, p. 3]. Bij 707 van de 6.283 woningen (11,3%)
  ontbreekt de gaskolom helemaal: woningen zonder gasaansluiting [Ontwerp §12.1; Kwaliteitsrapport
  §12.1].
- **Woningkenmerken** komen uit de vragenlijst bij aanmelding [Eindrapport §2.4, p. 16], het ISDE-
  vermogen uit het ISDE-register [RVO 2026, p. 4].
- **Weer.** RVO koppelde per woning de KNMI-waarden van het dichtstbijzijnde meetstation [RVO 2026,
  p. 2]; de 6.283 woningen hangen samen aan 28 stations [Ontwerp §1; Uitvoer]. Die meegeleverde,
  per woning gedupliceerde reeks staat bewust niet in de uitvoer: `weer.parquet` bevat een eigen,
  reproduceerbare KNMI-ophaal (`bron__cat = eigen_ingest`) [Ontwerp §7.3, §12.8, §12.13].
- **Meetonzekerheid, meterklasse en kalibratie** van de slimme meters: **niet vastgesteld**; geen van
  de bronnen specificeert ze.

## 4. Tijdconventies

- **Bron.** Volgens RVO staat een kwartier- en uurwaarde op het EINDE van het interval, een dagwaarde
  op het begin van de dag, en een maandwaarde op de laatste dag van de maand, 00:00 [RVO 2026, p. 2];
  `datetime` heet UTC [RVO 2026, p. 3]. In de data zijn `q`/`h`-tijdstempels inderdaad UTC, maar
  `d`/`m`-tijdstempels kale lokale datums zonder tijdzone [Ontwerp §1].
- **Uitvoer: `tijdstip_start` is overal het BEGIN van het interval**, voor alle vier de typen
  (`timestamps.resolve_timestamps`) [Ontwerp-IS §1, §4]. Einde van het interval is `tijdstip_start +
  interval_duur__s`. Terugrekenen naar de bronconventie: `tijdstip_start + interval_duur__s` voor
  `q`/`h`, `tijdstip_start` ongewijzigd voor `d`, en de laatste dag van dezelfde maand voor `m`
  [Varwoordenboek, measurements].
- **Tijdzone.** Elke tijdkolom is tz-aware `Europe/Amsterdam` (`timestamps.naar_lokale_tijdzone`, een
  `tz_convert`, geen `tz_localize`): het instant verandert niet, alleen de weergave; UTC is
  `.dt.tz_convert("UTC")` verderop [Ontwerp §12.10]. Onderbouwing voor Europe/Amsterdam: alle
  woningen hangen aan een Europees-Nederlands KNMI-station, en de ISDE-regeling geldt alleen voor
  Europees Nederland; RVO bevestigt het niet met zoveel woorden [Ontwerp §12.10, §10 punt 7].
- **`weer.tijdstip`** is het begin van het KNMI-uur: het KNMI-uur 00:00-01:00 (`HH=1`) krijgt tijdstip
  00:00 [Ontwerp-IS §4, "Wat er NIET verandert"].
- **`homes.installatiedatum_wp`** is een maand, weergegeven als de eerste dag om 00:00 lokale tijd
  (`pipeline._run_met_bron`), geen meetinterval [Ontwerp-IS §4].
- **Intervalduur.** `interval_duur__s` is 900 (`q`) of 3.600 (`h`); voor `d` de werkelijke lengte van
  de lokale kalenderdag (82.800 s op de voorjaars-, 90.000 s op de najaarsovergang), voor `m` die van
  de lokale kalendermaand (`intervals.compute_interval_duur_s`) [Ontwerp §2.4].

### 4.1 Zomertijd

- Op alle acht zomertijdovergangsdagen van 2022 t/m 2025 ontbreekt bij elke woning de `d`-rij:
  50.264 van 50.264 (woning, overgangsdatum)-combinaties [Kwaliteitsrapport §2.4; Ontwerp §2.4]. De
  meest waarschijnlijke verklaring is dat RVO's eigen dagcontrole een vaste 24-uursdag verwacht; dat
  is een hypothese, geen vaststelling [Ontwerp §2.4].
- `q`/`h` zijn in de bron UTC, dus een UTC-etmaal telt altijd 96 kwartieren of 24 uren [Ontwerp §2.4].
  Een aparte controle op gaten of dubbele tijdstempels rond de overgangen, zoals de WarmingUP- en
  DACS-HW-preprocessing die doen, zit niet in deze pipeline; de primaire sleutel (§9) is wel uniek
  over de volledige uitvoer [Uitvoer].

## 5. Uitvoertabellen

Alle tabellen zijn Parquet in `data/processed/`. `measurements`, `quality` en `derived` hebben
dezelfde rijen in dezelfde volgorde (één rij per bronregel) en dezelfde sleutel `(home_id__str,
tijdstip_start, interval_type__cat)`; ze zijn per chunk van woningen weggeschreven en daarna
samengevoegd tot één bestand met 1.108 rijgroepen [Uitvoer; Ontwerp §12.9, §12.17]. Kolomtypen
staan zoals `tabellen.py` ze vastlegt; `category` is in Parquet een dictionary-kolom.

| tabel | rijen | woningen | omvang op schijf |
|---|---|---|---|
| `homes.parquet` | 6.283 | 6.283 | 0,13 MB |
| `measurements.parquet` | 537.470.922 | 6.283 | 2,86 GB |
| `weer.parquet` | 1.147.239 | n.v.t. (28 stations) | 5,6 MB |
| `quality.parquet` | 537.470.922 | 6.283 | 1,91 GB |
| `derived.parquet` | 537.470.922 | 6.283 | 5,12 GB |

Bron van deze tabel: [Uitvoer] (rijen uit de footers, woningen door de unieke `home_id__str` per
rijgroep te tellen, omvang uit het bestandssysteem).

### 5.1 `homes.parquet`

**6.283 rijen, één per woning, 38 kolommen**, uit `00_IM_meta_data_openbaar.csv` (18 kenmerken;
rij 2 van de CSV is een eenheden-toelichting en wordt overgeslagen) door `io.read_homes_metadata`
[Varwoordenboek, homes]. Statisch: geen tijdas behalve de installatiemaand.

| kolom | type | eenheid | beschrijving | bronkolom |
|---|---|---|---|---|
| `home_id__str` | string | | geanonimiseerde woningsleutel, ook het getal in `IM_customer_<id>.csv` | `Customer_id` |
| `installatiedatum_wp` | timestamp(us, Europe/Amsterdam) | | installatiemaand van de warmtepomp, als eerste dag 00:00; volgens RVO ook de aanmelddatum [RVO 2026, p. 2]; zie §8 voor onwaarschijnlijke jaren | `Installatiedatum_hp` (`YYYY-MM`) |
| `heeft_thermostaat__bool` | bool | | programmeerbare thermostaat aanwezig | `Heeft_thermosstaat` (1/0) |
| `temp_dag_ingesteld__degC` | int8 | °C | daginstelling thermostaat, 15-25 | `Dag_temperatuur` |
| `temp_nacht_ingesteld__degC` | int8 | °C | nachtinstelling thermostaat, 10-23 | `Nacht_temperatuur` |
| `kookt_op_gas__bool` | bool | | koken op gas | `Koken_op_gas` (1/0) |
| `weerstation_nr` | int16 | | KNMI-stationscode (210-391, 28 unieke), koppelt aan `weer` | `Weerstation_nr` |
| `weerstation_naam__cat` | category | | naam van dat station | `Weerstation naam` |
| `vloeroppervlak_bin__cat` | category | m² | vloeroppervlak als bin, bijvoorbeeld `115-124`; bewust geen getal | `Vloer_oppervlak` |
| `heeft_ev_opgegeven__bool` | bool | | elektrische auto of laadpaal opgegeven | `EV_opgegeven` (1/0) |
| `isde_vermogen__kW` | int8, nullable | kW | bivalent vermogen uit het ISDE-register [RVO 2026, p. 4]; leeg bij bronwaarde `-1` (onbekend, 361 woningen) of leeg (6 woningen) | `ISDE vermogen` |
| `isde_vermogen_onbekend__bool` | bool | | bron had de sentinel `-1` | `ISDE vermogen` |
| `verwarmingssysteem_ruw__cat` | category | | het multi-selectveld letterlijk, komma-gescheiden | `Verwarmingssysteem` |
| `heeft_<systeem>__bool` (11) | bool | | één vlag per token uit `io.VERWARMINGSSYSTEEM_TAGS`: airco voor verwarmen, all-electric warmtepomp, HR-ketel, hout-/pelletkachel, hybride warmtepomp, infraroodpanelen, PVT-panelen, stadswarmte, ventilatiewarmtepomp, warmtepompboiler, zonneboiler | `Verwarmingssysteem` |
| `afgiftesysteem_ruw__cat` | category | | het multi-selectveld letterlijk | `Afgiftesysteem` |
| `heeft_<systeem>__bool` (7) | bool | | één vlag per token uit `io.AFGIFTESYSTEEM_TAGS`: convectoren, convectorputten, elektrische verwarming, infraroodpanelen, luchtverwarming, radiatoren, vloerverwarming | `Afgiftesysteem` |
| `woningtype_bron_afgekapt__bool` | bool | | woningtype was in de bron afgekapt en is hersteld (1.841 woningen, 29,3%) | `Woningtype` |
| `woningtype__cat` | category | | `Vrijstaand`, `Twee-onder-een-kap`, `Rijwoning (tussenwoning)`, `Rijwoning (hoekwoning)`, `Appartement` | `Woningtype` |
| `type_glas__cat` | category | | type beglazing | `Type_glas` |
| `muurisolatie_type__cat` | category | | type muurisolatie | `Isolatie_type` |
| `vloerisolatie__cat` | category | | `Ja`, `Nee`, `Weet ik niet` | `Vloer_isolatie_type` |
| `dakisolatie_type__cat` | category | | kwaliteit dakisolatie | `Dak_isolatie_type` |

Bronnen voor deze tabel: code in `io.py` [Varwoordenboek, homes]; aantallen 361 en 6 en de
categorieën zijn geteld in de bron-CSV en in `homes.parquet` [Uitvoer]; de afkapping
[Ontwerp §2.2; Kwaliteitsrapport §2.2]. Beide taglijsten zijn geverifieerd tegen alle voorkomende
tokens; een onbekend token geeft een `SchemaError` [Varwoordenboek, homes].

### 5.2 `measurements.parquet`

**537.470.922 rijen, 6.283 woningen.** Eén rij per regel in een klantbestand, elektriciteit als
gemiddeld vermogen; uitsluitend aannamevrije omzettingen [Ontwerp-IS §3]. Gas staat in `derived`
(§5.5), niet hier [Ontwerp-IS §3, "Besloten kolomindeling"].

| kolom | type | eenheid | interval | beschrijving | bronkolom |
|---|---|---|---|---|---|
| `home_id__str` | string | | | woningsleutel | bestandsnaam |
| `tijdstip_start` | timestamp(ns, Europe/Amsterdam) | | per rij | begin van het interval (§4) | `datetime` + `interval` |
| `interval_type__cat` | category | | | `q`, `h`, `d` of `m` | `interval` |
| `interval_duur__s` | int32 | s | per rij | lengte van het interval, zomertijd-aware (§4) | afgeleid |
| `granulariteit__cat` | category | | | `kwartier_totaal`, `uur_totaal`, `dag_totaal`, `maand_gemiddeld_per_dag` | afgeleid uit `interval` |
| `e_net__W` | float32 | W | per rij | gemiddeld netto elektrisch vermogen; negatief is teruglevering | `elec` (kWh) |

- **`e_net__W` = `elec` x 3.600.000 / deler**, met deler = `interval_duur__s` voor `q`/`h`/`d` en
  86.400 s voor `m` (`pipeline.build_measurements`, `intervals.compute_energie_deler_s`). Een `m`-rij
  is namelijk niet het maandtotaal dat het informatiedocument suggereert, maar het gemiddelde
  dagverbruik van die maand [Ontwerp §2.1; Ontwerp-IS §2]. Energie is verliesvrij terug te rekenen:
  `E = e_net__W x interval_duur__s` (voor `m`: `x 86.400`), tot op de float32-afrondgrens (maximale
  relatieve fout 1,16e-7) [Ontwerp-IS §3].
- **`e_net__W` is op de volledige run nergens leeg** [Uitvoer; Kwaliteitsrapport, Cleaning-vlaggen].

### 5.3 `weer.parquet`

**1.147.239 rijen: 28 stations, uurwaarden van 31 mei 2021 02:00 t/m 7 februari 2026 00:00 lokale
tijd, allemaal `bron__cat = eigen_ingest`** [Uitvoer]. Opgehaald met
`needforheat-dutch-weather-software` voor precies de stations en de periode van de woningen, terug
tot de vroegste maandrij [Ontwerp §2.3, §7.3]. Sinds §12.13 de rauwe stationswaarde, zonder
geospatiale interpolatie, want er wordt altijd een bestaand KNMI-station opgevraagd [Ontwerp §12.13].

| kolom | type | eenheid | beschrijving | bron |
|---|---|---|---|---|
| `weerstation_nr` | int16 | | KNMI-stationscode, koppelt aan `homes.weerstation_nr` | KNMI |
| `tijdstip` | timestamp(ns, Europe/Amsterdam) | | begin van het uur (§4) | KNMI `HH` |
| `temp_buiten__degC` | float32 | °C | buitentemperatuur | KNMI `T` x 0,1 |
| `wind__m_s_1` | float32 | m/s | windsnelheid | KNMI `FH` x 0,1 |
| `ghi__W_m_2` | float32 | W/m² | globale horizontale instraling, gemiddeld over het uur | KNMI `Q` (J/cm²) x 10.000 / 3.600 |
| `bron__cat` | category | | `eigen_ingest`, of `eigen_ingest_geointerpoleerd` alleen na `--weer-geointerpoleerd-diagnose` | |

Omrekenfactoren: `weer.METRICS`. `ghi__W_m_2` heette eerder `ghi__kWh_m_2` en was door 1.000 gedeeld;
het is een instraling, geen energietotaal [Ontwerp-IS §3, "`ghi__kWh_m_2` is geen energie maar een
instraling"]. De door RVO meegeleverde weerreeks staat hier bewust niet in [Ontwerp §12.8].

### 5.4 `quality.parquet`

**537.470.922 rijen, 6.283 woningen.** Eén rij per `measurements`-rij, met de sleutel en zeven
vlaggen (`cleaning.build_quality_table`). Vlaggen markeren, ze verwijderen of vervangen niets
[Ontwerp §3 principes 3-5]. Kolommen en exacte regels: §6.1.

| kolom | type | beschrijving |
|---|---|---|
| `home_id__str`, `tijdstip_start`, `interval_type__cat` | als in `measurements` | sleutel, rij voor rij overgenomen |
| `e_net_ontbrekend__flag`, `g_gebruik_ontbrekend__flag` | bool | waarde ontbreekt (NaN) |
| `g_gebruik_negatief__flag` | bool, nullable | gas negatief |
| `e_net_constante_reeks__flag`, `g_gebruik_constante_reeks__flag` | bool, nullable | hele reeks van de woning en het intervaltype constant |
| `e_net_uitschieter__flag`, `g_gebruik_uitschieter__flag` | bool, nullable | meer dan 3 standaarddeviaties van het gemiddelde |

De vlaggen op gas werken op `g_gebruik__m3_s_1`, dat in `derived` staat, niet in `measurements`.

### 5.5 `derived.parquet`

**537.470.922 rijen, 6.283 woningen.** Eén rij per `measurements`-rij: alles wat een externe waarde
of koppeling nodig heeft, plus de gasvolumestroom [Ontwerp-IS §3; Varwoordenboek, derived].

| kolom | type | eenheid | beschrijving | bron |
|---|---|---|---|---|
| `home_id__str`, `tijdstip_start`, `interval_type__cat` | als in `measurements` | | sleutel | |
| `g_gebruik__m3_s_1` | float32 | m³/s | gemiddelde gasvolumestroom: `gas` / deler, deler als bij `e_net__W` (§5.2) | `gas` (m³) |
| `g_gebruik__W` | float32 | W | `g_gebruik__m3_s_1` x `actual_gas_std_hhv__J_m_3` (`derived.build_derived`) | afgeleid |
| `actual_gas_std_hhv__J_m_3` | float32 | J/m³ | toegepaste calorische bovenwaarde van gas (`gaskwaliteit.py`) | mijnenergiedata.nl |
| `gas_hhv_bron__cat` | category | | `mijnenergiedata_actueel` of `vast_gemiddelde_fallback` | |
| `weerkoppeling_methode__cat` | category | | hoe het weer gekoppeld is, zie hieronder | |
| `temp_buiten__degC`, `wind__m_s_1`, `ghi__W_m_2` | float32 | °C, m/s, W/m² | gekoppeld weer uit `weer.parquet` | `weer` |

- **Gas ontbreekt op 439.621.834 rijen** (81,8%) [Kwaliteitsrapport, Cleaning-vlaggen]: de
  kwartierrijen, want gas is er alleen per uur, dag en maand [RVO 2026, p. 3], plus alle rijen van
  de 707 woningen zonder gaskolom [Ontwerp §12.1]. De bron-NaN blijft NaN, nooit 0 (`io.read_customer_stream`).
- **Calorische waarde.** Het landelijk gemiddelde over alle netgebieden per uur van
  `mijnenergiedata.nl/calorische-gaswaarden`, via een niet publiek gedocumenteerde API; IM3 levert
  geen netgebied per woning. Koppeling als bij het weer (uur exact, kwartier lineair
  geïnterpoleerd, dag en maand het gemiddelde over het lokale venster); buiten het opgehaalde
  venster de vaste 35,17 MJ/m³ (`gaskwaliteit.couple_gas_hhv_to_measurements`) [Ontwerp §12.3]. Op
  de volledige run kregen alle 537.470.922 rijen de werkelijke waarde, bereik 35,68 t/m
  36,26 MJ/m³ [Kwaliteitsrapport, Calorische gaswaarde; Uitvoer].
- **Weerkoppeling** (`weer.couple_weather_to_measurements`) [Ontwerp §2.3]: `punt_interpolatie` voor
  een `q`-rij (lineair tussen de omliggende uurwaarden van het station, op `tijdstip_start`),
  `punt_uur` voor `h` (exacte match op het uur), `gemiddelde_dag` en `gemiddelde_maand` voor `d`/`m`
  (gemiddelde van de uurwaarden over de lokale kalenderdag of -maand, dus 23 of 25 uren op een
  overgangsdag). Kreeg een rij geen waarde, dan `ontbrekend_buiten_archief`. Verdeling op de volledige
  run [Uitvoer]:

  | `weerkoppeling_methode__cat` | rijen |
  |---|---|
  | `punt_interpolatie` | 427.540.883 |
  | `punt_uur` | 103.934.661 |
  | `gemiddelde_dag` | 4.461.970 |
  | `gemiddelde_maand` | 220.043 |
  | `ontbrekend_buiten_archief` | 1.313.365 (0,24%) |

  De weervelden zijn leeg op precies die 1.313.365 rijen [Uitvoer].
- **Weervelden ontbreken bij `--skip-weer`**: dan heeft `derived` geen `weerkoppeling_methode__cat` en
  geen weervelden, en wordt `weer.parquet` niet geschreven (`pipeline._verwerk_chunk`,
  `pipeline._run_met_bron`). Deze catalogus en `datapackage.json` beschrijven de volledige run.

## 6. Kwaliteit

Cijfers uit [Kwaliteitsrapport] (volledige run, 6.283 woningen) en [Uitvoer].

### 6.1 Wanneer elke vlag aan gaat

Vastgelegd in `cleaning.build_quality_table` en `quality.py`. "Reeks" betekent hier steeds alle
rijen van één woning met één intervaltype (`groupby(["home_id__str", "interval_type__cat"])`); de
standaarddeviatie is die van pandas (steekproef, `ddof=1`, lege waarden overgeslagen). "Leeg"
is `pd.NA` in een nullable-booleankolom: niet te beoordelen, iets anders dan `False`.

| vlag | `True` als | `False` als | leeg als | aantal `True` | aantal leeg |
|---|---|---|---|---|---|
| `e_net_ontbrekend__flag` | `e_net__W` is NaN | anders | nooit | 0 | 0 |
| `g_gebruik_ontbrekend__flag` | `g_gebruik__m3_s_1` is NaN | anders | nooit | 439.621.834 | 0 |
| `g_gebruik_negatief__flag` | `g_gebruik__m3_s_1 < 0` | `g_gebruik__m3_s_1 >= 0` | `g_gebruik__m3_s_1` is NaN | 2.690 | 439.621.834 |
| `e_net_constante_reeks__flag` | standaarddeviatie van `e_net__W` over de reeks is exact 0 én de reeks heeft minstens 2 niet-lege waarden | anders | `e_net__W` van deze rij is NaN | 125.057 | 0 |
| `g_gebruik_constante_reeks__flag` | idem op `g_gebruik__m3_s_1` | anders | `g_gebruik__m3_s_1` van deze rij is NaN | 9.344.417 | 439.621.834 |
| `e_net_uitschieter__flag` | `abs(e_net__W - m) > 3,0 x s`, met `m` en `s` het gemiddelde en de standaarddeviatie van de reeks | `abs(...) <= 3,0 x s` | `e_net__W` is NaN, of `s` is 0 of onbepaald (minder dan 2 waarden) | 7.558.447 | 125.068 |
| `g_gebruik_uitschieter__flag` | idem op `g_gebruik__m3_s_1` | idem | idem | 2.332.051 | 448.966.258 |

Aantallen `True`: [Kwaliteitsrapport, Cleaning-vlaggen]; aantallen leeg: rijgroepstatistieken van
`quality.parquet` [Uitvoer]. Die laatste kloppen onderling: leeg bij de uitschietervlaggen is precies
leeg bij de constantevlag plus de constante reeksen zelf (standaarddeviatie 0) plus een handvol
reeksen met één waarde.

Achtergrond per vlag:

- **Ontbrekend.** Een 0 is een geldige waarde, een NaN niet; die twee worden nooit verward
  [Ontwerp §3 principe 4]. `g_gebruik_ontbrekend__flag` is voor de 707 woningen zonder gaskolom
  structureel `True`; dat is verwacht, geen kwaliteitsprobleem [Ontwerp §12.1].
- **Negatief gas** is informatief, geen filter: of gas ooit negatief mag zijn, is een open vraag aan
  RVO [Ontwerp §10 punt 3]. De 2.690 rijen zitten bij 235 woningen [Kwaliteitsrapport §10.3].
  Negatieve elektriciteit wordt niet gevlagd, want dat is teruglevering [RVO 2026, p. 2].
- **Constante reeks** is dezelfde aanpak als `Preprocessor.filter_id_prop_with_std_zero` in
  needforheat-diagnosis-software, hier als vlag in plaats van verwijdering; een tijdelijke reeks
  gelijke waarden telt bewust niet [Ontwerp §12.5].
- **Uitschieter** is dezelfde aanpak als `Preprocessor.filter_static_outliers`, met
  `cleaning.UITSCHIETER_N_SIGMA = 3.0` als voorlopige, niet extern bevestigde drempel; een uitschieter
  is niet per definitie fout [Ontwerp §12.5; Kwaliteitsrapport, Bekende aannames].

### 6.2 Bevindingen in het kwaliteitsrapport

- **Tellersoverloop van 10.000 kWh.** De extreemste `e_net__W`-waarden liggen rond ±40 MW, precies
  10.000 kWh in een kwartier. Alle 410 rijen met `|e_net__W| > 1 MW` (112 woningen) zijn een sprong
  van 10.000 kWh met een marge van 13 kWh: een register dat bij 9.999,9 omslaat. Niet te repareren
  zonder de cumulatieve standen; `e_net_uitschieter__flag` is het signaal [Ontwerp §12.18;
  Kwaliteitsrapport §12.6].
- **Gas exact 0 vóór koppeling.** 711 woningen hebben de eerste 60 dagen met een `d`-gasrij stuk voor
  stuk exact 0, waarvan 62 met metadata die gasgebruik verwacht (koken op gas of een HR-ketel).
  Vermoedelijk "nog niet gemeten", als 0 in plaats van NaN gepubliceerd; hypothese, niet omgezet
  [Kwaliteitsrapport §12.7; Ontwerp §12.7].
- **Kwartier- en uursom tegen dagwaarde.** Over 4.104.423 respectievelijk 4.059.380 dagen is de
  mediane absolute afwijking 0,000 kWh, het 95e percentiel 0,806 respectievelijk 0,943 kWh
  [Kwaliteitsrapport §7.1].
- **Eigen KNMI-reeks tegen het door RVO meegeleverde weer.** 25 van de 28 stations vallen binnen de
  voorlopige drempels (temperatuur en wind < 0,5, instraling < 50 W/m² mediane absolute afwijking);
  210, 240 en 340 niet, op temperatuur en wind [Kwaliteitsrapport §7.2/§7.3]. Op instraling vallen
  alle 28 binnen de drempel, maar bij diezelfde drie stations alleen door de mediaan; zie §8.
- **Woningtype afgekapt** bij 1.841 woningen (29,3%), hersteld [Kwaliteitsrapport §2.2].

## 7. Hoe te laden

`homes` en `weer` passen gewoon in geheugen. `measurements`, `quality` en `derived` hebben elk 537
miljoen rijen; volledig inladen in pandas vraagt tientallen GB. Lees daarom per woning of per kolom
met een filter, dan leest pyarrow alleen de rijgroepen die ertoe doen:

```python
import pandas as pd
import pyarrow.parquet as pq

homes = pd.read_parquet("data/processed/homes.parquet")
weer = pd.read_parquet("data/processed/weer.parquet")

# Eén woning, alleen kwartierrijen
m = pq.read_table(
    "data/processed/measurements.parquet",
    filters=[("home_id__str", "==", "1000"), ("interval_type__cat", "==", "q")],
).to_pandas()

# Vlaggen en gas erbij: zelfde sleutel, zelfde rijvolgorde
sleutel = ["home_id__str", "tijdstip_start", "interval_type__cat"]
q = pq.read_table("data/processed/quality.parquet", filters=[("home_id__str", "==", "1000")]).to_pandas()
m = m.merge(q, on=sleutel, how="left")

# Energie terugrekenen (m-rijen: maal 86.400 s, zie §5.2)
m["e_net__kWh"] = m["e_net__W"] * m["interval_duur__s"] / 3.6e6
```

`datapackage.json` (§9) beschrijft alle vijf tabellen machineleesbaar.

## 8. Bekende beperkingen en open vragen

- **`m`-rijen zijn gemiddeld dagverbruik, geen maandtotaal**, anders dan RVO's voorbeeld suggereert;
  hier gelabeld als `maand_gemiddeld_per_dag` en in de vermogensberekening verwerkt [Ontwerp §2.1;
  Ontwerp-IS §2].
- **Tellersoverloop en gas-0 vóór koppeling** (§6.2) zijn alleen gesignaleerd, niet gecorrigeerd;
  beide liggen als vraag bij RVO/KITE [Ontwerp §10 punten 5 en 6].
- **Geen `d`-rij op zomertijdovergangsdagen** (§4.1).
- **Onwaarschijnlijke installatiedatums.** `installatiedatum_wp` bevat 31 woningen met een jaar vóór
  2015 of na 2026, waaronder de jaren 20, 23, 24, 203, 223, 224 en 2924 (vermoedelijk tikfouten voor
  2020-2024), en 37 met een jaar tussen 2015 en 2021 [Uitvoer]. Deze pipeline vlagt ze niet. De
  jaren 20 t/m 224 krijgen bij de omzetting naar Europe/Amsterdam bovendien de historische
  lokale-tijdoffset uit de tijdzonedatabase (+00:17:30), zodat ze bij teruglezen niet op 00:00
  uitkomen (bijvoorbeeld `0020-11-01 00:42:30+01:00`) [Uitvoer]. Ook `vloeroppervlak_bin__cat` bevat een
  onwaarschijnlijke bin, `15-1600` (3 woningen) [Uitvoer].
- **Metadata wijkt af van RVO's datadictionary.** Vergeleken met de veldentabel in het
  informatiedocument [RVO 2026, p. 3-4] en Bijlage F van het eindrapport [Eindrapport, p. 78-80]:
  de installatiedatum staat in de data als `YYYY-MM`, niet `MM-YYYY`; woningtype heeft
  `Appartement` waar de dictionary `Meergezinswoning` noemt; vloerisolatie is `Ja`/`Nee`/`Weet ik
  niet`, niet `Goed`/`Matig`/`Slecht`/`Weet ik niet`; dakisolatie is `Goede`/`Redelijke`/`Matige`/
  `Geen isolatie`/`Weet niet`; `Weekdays` en `Weekenddays` (verwarmingsgedrag) staan in de dictionary
  zonder "niet openbaar gemaakt", maar ontbreken in de metadata [Uitvoer, telling op de bron-CSV].
  Bijlage F zegt verder dat elk klantbestand een header met de statische kenmerken heeft; in
  werkelijkheid staan die in het aparte metadatabestand [Eindrapport, p. 78; Datadescr].
- **Weer in de bron alleen op `h`-rijen**; `d`/`m` hebben nooit weer [Ontwerp §2.3]. De eigen
  KNMI-reeks dekt de hele periode, maar het deel vóór de eerste `h`-rij kon niet tegen de RVO-reeks
  worden gecontroleerd [Ontwerp §7.3 stap 4].
- **Instraling tegen KNMI: 25 stations exact, 210, 240 en 340 niet.** RVO's `sun` is "gesommeerde
  zoninstraling" in kWh/m² [RVO 2026, p. 3], per uur, in stappen van 1/360 kWh/m² (1 J/cm², de
  resolutie van KNMI's `Q`). Tot en met de run van 6 en 7 september werd die waarde zonder
  omrekening als W/m² met de eigen KNMI-reeks vergeleken; de toen gerapporteerde mediane afwijking
  van 2,8 tot 8,3 W/m² was in feite de mediane KNMI-waarde zelf. `weer.extract_im3_weather` rekent nu
  om naar gemiddelde W/m² (x 1000 / duur in uren) [Ontwerp §12.19]. Herberekend uit de bewaarde
  IM3-weerreeks van die run: de mediane absolute afwijking is 0,0 W/m² bij 25 stations (85 tot 91%
  van de uren exact gelijk, 99e percentiel 1,3 W/m², bij 391 36,9 W/m²) en 0,0, 0,8 en 0,2 W/m² bij
  210, 240 en 340. Die mediaan telt de nachturen mee. Overdag (KNMI > 0) is de mediane afwijking bij
  210, 240 en 340 13,9, 22,2 en 19,4 W/m², wijkt 12 tot 15% van de uren meer dan 50 W/m² af, en
  loopt het 99e percentiel op tot 236 tot 285 W/m² (maximaal 761 W/m²) [Ontwerp §12.19]. Het zijn dezelfde drie stations die op temperatuur en wind afwijken. De
  uitvoertabellen raakt dit niet: de RVO-reeks staat er niet in.
- **Stations 210, 240 en 340** wijken op temperatuur en wind af van de meegeleverde reeks; de oorzaak
  is niet uitgezocht [Kwaliteitsrapport §7.2/§7.3; Ontwerp §12.4].
- **Drempels voorlopig**: de uitschieterdrempel van 3 standaarddeviaties en de matchdrempels voor
  het weer zijn niet extern bevestigd [Kwaliteitsrapport, Bekende aannames; Ontwerp §10 punt 4].
- **Calorische waarde is een landelijk gemiddelde** uit een niet gedocumenteerde API; tussen twee
  ophaalmomenten veranderde die tot 0,5% [Ontwerp §12.3, §12.16].
- **Geen netgebied, postcode, bouwjaar of energielabel** in de openbare set [RVO 2026, p. 3-4], dus
  geen koppeling aan BAG of andere registraties.
- **Europe/Amsterdam** als tijdzone is onderbouwd maar niet door RVO bevestigd [Ontwerp §10 punt 7].
- **Werving en selectie** zijn maar deels beschreven (§2); meterklasse en meetonzekerheid zijn niet
  vastgesteld (§3).

## 9. Datapackage (machineleesbare beschrijving)

`datapackage.json` in de repo-root is een machineleesbare beschrijving van deze vijf tabellen volgens
de [Frictionless Data Package-standaard](https://datapackage.org/): per tabel een Table Schema met
kolomnamen, types, beschrijvingen, verplichte kolommen, de vaste waarden van elke `__cat`-kolom uit
`dtypes.py`, primaire en vreemde sleutels, plus licentie- en herkomstinformatie. Het wordt UIT DE CODE
gegenereerd (`im3_preprocessing.datapackage`, uit de schema's in `tabellen.py`), aan het eind van
elke pipeline-run herschreven, en is los te regenereren met `python -m im3_preprocessing.datapackage`.
Paden in het datapackage zijn relatief aan de uitvoermap (`data/processed/`).

**Primaire sleutels**, alle vijf geverifieerd uniek op de volledige run [Uitvoer]: `homes`
`home_id__str`; `weer` `(weerstation_nr, tijdstip, bron__cat)`; `measurements`, `quality` en
`derived` `(home_id__str, tijdstip_start, interval_type__cat)`. `tijdstip_start` alleen is geen
sleutel: een `d`-rij en de eerste `q`/`h`-rij van dezelfde dag beginnen op hetzelfde moment.

**Borging.** `tests/test_datapackage.py` controleert dat elk veld in een schema in het datapackage
staat en omgekeerd; dat de echte pipeline op een synthetische dataset precies die schema's schrijft;
dat de footers van de volledige-run-uitvoer ermee kloppen (als die op de machine staat); dat het
gecommitte `datapackage.json` actueel is; en, als `frictionless` geïnstalleerd is, dat het
datapackage structureel geldig is. De licentie verwijst naar
[`GEBRUIKSVOORWAARDEN.md`](../GEBRUIKSVOORWAARDEN.md): de data is niet vrij herverspreidbaar.

## 10. Bronnen

- **[RVO 2026]** Rijksdienst voor Ondernemend Nederland (2026, 20 augustus). *Installatiemonitor
  Dataset: omschrijving gebruiksvoorwaarden en toelichting op dataset Installatiemonitor* (versie
  1.0, 4 pagina's). Kennis- en Dataplatform Individuele Technieken (KITE). Bijgeleverd in
  `dataset_openbaar.zip` als `00_Informatie document IM dataset - 20260820.pdf`.
- **[Eindrapport]** Poiesz, T., Janssen, G., Biemans, A., Wagener, P., & Hommelberg, M. (2026, 15
  juni). *Installatiemonitor 3.0: de warmtepomp in de gebouwde omgeving* (eindrapportage, versie
  definitief 1.02). Opdrachtgevers: RVO, Techniek Nederland, Netbeheer Nederland. Publiek via
  <https://kennisdelen.rvo.nl/kite/installatiemonitor> [RVO 2026, p. 1]. Paginanummers zijn die in de
  koptekst van het rapport.
- **[Ontwerp]** [`ontwerp-preprocessing.md`](../ontwerp-preprocessing.md), deze repo: het ontwerp,
  de geverifieerde bevindingen in de brondata (§1-§2, §12) en de open vragen (§10).
- **[Ontwerp-IS]** [`ontwerp-intervalsemantiek.md`](../ontwerp-intervalsemantiek.md), deze repo:
  begin-labeling, alleen vermogens, de `m`-rijcorrectie.
- **[Datadescr]** [`data-description.md`](data-description.md), deze repo: de bronbestanden en de
  afwijkingen van RVO's datadictionary.
- **[Varwoordenboek]** [`variable-dictionary.md`](variable-dictionary.md), deze repo: de vertaling van
  ruw naar gestandaardiseerd en het dtype-beleid.
- **[Kwaliteitsrapport]** [`data-quality.md`](data-quality.md), deze repo, door de pipeline
  gegenereerd uit de volledige run van 6 en 7 september 2026.
- **[Uitvoer]** Eigen telling op de uitvoer van diezelfde run in `data/processed/` (25 september
  2026): rijaantallen en schema's uit de Parquet-footers, leeg-aantallen en bereiken uit de
  rijgroepstatistieken, unieke woningen en de verdeling van de categoriekolommen per rijgroep, de
  uniciteit van de sleutel per chunk-deelbestand in `data/processed/parts/`, tellingen op
  `homes.parquet`, `weer.parquet` en `00_IM_meta_data_openbaar.csv`, en de ledenlijst van
  `dataset_openbaar.zip`. Niet in git, zie
  `GEBRUIKSVOORWAARDEN.md`.
- De code in `src/im3_preprocessing/`, per bewering bij naam genoemd.
