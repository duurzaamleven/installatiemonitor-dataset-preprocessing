# Variabelen-woordenboek: ruw → standardized

Zie `ontwerp-preprocessing.md` §5 voor de rationale. Implementatie:
`src/im3_preprocessing/bron.py` (de ruwe data uit de zip of uit een map halen),
`src/im3_preprocessing/io.py` (`read_homes_metadata`, `read_customer_stream`),
`src/im3_preprocessing/pipeline.py` (`build_measurements`).

## Dtype-beleid (pandas/Parquet)

Uitgangspunt: zo compact als de data en de semantiek toelaten, maar nooit zuiniger dan wat er
daadwerkelijk aan waarden/precisie nodig is; bij twijfel de ruimere keuze, niet de kleinste.
Elke keuze hieronder is geverifieerd tegen de **volle** metadata-CSV (6.283 rijen, 26-aug-2026),
niet tegen een steekproef.

- **Boolean-kolommen krijgen de suffix `__bool`, niet `__0`.** `__0` (physiquant__unit-conventie)
  betekent "dimensieloos getal", en dat kan ook een telling, ratio of COP zijn, geen boolean. Alle
  `heeft_<x>__bool`/`kookt_op_gas__bool`/`woningtype_bron_afgekapt__bool`/etc. hieronder zijn
  echte ja/nee-vlaggen en horen dus op `__bool`, nooit op `__0`.
- **Integers krijgen de kleinste maat die de daadwerkelijke waardenrange dekt**, geverifieerd
  tegen de volle dataset, niet geraden:
  - `temp_dag_ingesteld__degC`/`temp_nacht_ingesteld__degC`: `int8` (bereik 15-25 / 10-23, altijd
    geheel, nooit leeg in de bron).
  - `weerstation_nr`: `int16` (KNMI-codes 210-391, 28 unieke waarden).
  - `interval_duur__s`: `int32` (grootste geval, een 31-dagen-maand, is ~2,68 miljoen seconden,
    te groot voor `int16`). Plain, niet nullable: elke geldige `interval_type` wordt exhaustief
    gevuld (`intervals.compute_interval_duur_s` raiset zelf als dat niet zo is), dus een nullable
    type zou hier alleen overhead toevoegen zonder ooit een NaN te bevatten.
  - `isde_vermogen__kW`: nullable `Int8`, altijd een geheel getal (0 van 6.277 niet-lege waarden
    had een decimaal) binnen `-1..19`, én moet NaN kunnen bevatten (de `-1`-sentinel wordt NaN,
    plus 6 al-lege waarden), vandaar nullable en niet plain `int8`.
- **Floats zijn `float32`**, niet `float64`, zelfde precisie-keuze als
  `needforheat-diagnosis-software`'s eigen `property_types`-tabel (die expliciet `float32`
  gebruikt voor praktisch alle continue grootheden, `float64` bewaart alleen voor *cumulatieve*
  tellerstanden die over jaren kunnen oplopen). float32 geeft ~7 significante decimalen, ruim
  genoeg voor kWh/m³/°C/m·s⁻¹-precisie op de schaal van deze dataset (tot enkele duizenden kWh
  per kwartier, zie de uitschieter-check). Geen nullable `Float32`-extensietype nodig: float32
  ondersteunt NaN al native (IEEE754), belangrijk voor `g_gebruik__m3`, dat structureel NaN is
  bij de 707/6.283 all-electric woningen zonder gasaansluiting (§12.1).
  - **Let op een numpy-valkuil**: `float32`-array gedeeld/vermenigvuldigd met een `int32`-array
    promoot in numpy naar `float64` (numpy's promotieregels zijn conservatief bij het combineren
    van float32 met een integer-dtype). `derived.py` cast daarom expliciet terug naar `float32`
    ná elke berekening, anders sluipt float64 er alsnog stilzwijgend in.
- **Laag-cardinale, herhaalde strings worden `category`**, niet plain `str`: `interval_type__cat`
  (4 waarden, herhaalt over miljoenen rijen), `granulariteit__cat` (4), `bron__cat` (2: eigen_ingest/
  eigen_ingest_geointerpoleerd), `weerkoppeling_methode__cat` (5), `gas_hhv_bron__cat` (2), en
  in `homes` alle categorische tekstvelden (`woningtype__cat`, `type_glas__cat`, enz.; hoogstens
  29 unieke waarden op 6.283 rijen). **Uitzondering: `home_id__str` blijft plain `str`**, ook in
  `measurements`/`derived`/`quality` waar het wél vaak herhaalt: het is de join-sleutel tussen
  tabellen en `category` geeft daar in pandas soms verrassend gedrag bij merges; de winst op
  schijf is bovendien beperkt omdat Parquet's eigen dictionary-encoding herhaalde strings al
  comprimeert onafhankelijk van het pandas-dtype.
- **Nullable (`Int8`/`boolean`) vs. plain (`int8`/`bool`)**: alleen nullable waar de kolom
  daadwerkelijk NaN/pd.NA kan bevatten (ISDE-vermogen; de gas-afhankelijke kwaliteitsvlaggen
  hieronder). Een kolom die per constructie nooit leeg is (`interval_duur__s`, de multi-select-
  tagbooleans) hoort plain te zijn: de nullable-overhead (validity-bitmask) zonder ooit een NaN
  is pure winstverspilling.

Bij twijfel over een keuze hierboven (bijv. of een toekomstige kolom `__0` of `__bool` moet
worden, of een nieuwe integer-kolom breder moet dan wat de huidige steekproef laat zien),
navragen bij de gebruiker, niet zelf raden (feedback 26-aug-2026).

## `homes` (uit `00_IM_meta_data_openbaar.csv`)

| ruwe kolom | standardized kolom | dtype | opmerking |
|---|---|---|---|
| `Customer_id` | `home_id__str` | `str` | ongewijzigd, is al het anonieme sleutel |
| `Installatiedatum_hp` | `installatiedatum_wp` | `datetime64[us]` | `"YYYY-MM"` → eerste dag van de maand |
| `Heeft_thermosstaat` | `heeft_thermostaat__bool` | `bool` | 1/0 → bool |
| `Dag_temperatuur` | `temp_dag_ingesteld__degC` | `int8` | altijd geheel, 15-25 |
| `Nacht_temperatuur` | `temp_nacht_ingesteld__degC` | `int8` | altijd geheel, 10-23 |
| `Koken_op_gas` | `kookt_op_gas__bool` | `bool` | 1/0 → bool |
| `Weerstation_nr` | `weerstation_nr` | `int16` | foreign key naar `weer.parquet` |
| `Weerstation naam` | `weerstation_naam__cat` | `category` | 28 unieke waarden |
| `Vloer_oppervlak` | `vloeroppervlak_bin__cat` | `category` | blijft een bin (bv. `"115-124"`), geen numerieke aanname |
| `EV_opgegeven` | `heeft_ev_opgegeven__bool` | `bool` | 1/0 → bool |
| `ISDE vermogen` | `isde_vermogen__kW` + `isde_vermogen_onbekend__bool` | `Int8` (nullable) + `bool` | sentinel `-1` → NaN + vlag, geen echte 0-waarde |
| `Verwarmingssysteem` | `verwarmingssysteem_ruw__cat` + 11 losse `heeft_<systeem>__bool`-booleans | `category` + `bool` | multi-select, komma-gescheiden; taglijst zie `io.VERWARMINGSSYSTEEM_TAGS` |
| `Afgiftesysteem` | `afgiftesysteem_ruw__cat` + 7 losse `heeft_<systeem>__bool`-booleans | `category` + `bool` | idem, `io.AFGIFTESYSTEEM_TAGS` |
| `Woningtype` | `woningtype__cat` + `woningtype_bron_afgekapt__bool` | `category` + `bool` | 2 van de 5 categorieën herstelt van een afgekapte bronwaarde |
| `Type_glas` | `type_glas__cat` | `category` | |
| `Isolatie_type` | `muurisolatie_type__cat` | `category` | hernoemd voor duidelijkheid (betreft muurisolatie) |
| `Vloer_isolatie_type` | `vloerisolatie__cat` | `category` | 3 categorieën (Ja/Nee/Weet ik niet), geen boolean |
| `Dak_isolatie_type` | `dakisolatie_type__cat` | `category` | |

### Verwarmingssysteem-tags (`io.VERWARMINGSSYSTEEM_TAGS`)

`heeft_airco_verwarming__bool`, `heeft_all_electric_wp__bool`, `heeft_hr_ketel__bool`, `heeft_houtkachel__bool`,
`heeft_hybride_wp__bool`, `heeft_infrarood_panelen_verwarming__bool`, `heeft_pvt__bool`,
`heeft_stadswarmte__bool`, `heeft_ventilatiewarmtepomp__bool`, `heeft_warmtepompboiler__bool`,
`heeft_zonneboiler__bool`.

### Afgiftesysteem-tags (`io.AFGIFTESYSTEEM_TAGS`)

`heeft_convectoren__bool`, `heeft_convectorputten__bool`, `heeft_elektrische_verwarming_afgifte__bool`,
`heeft_infraroodpanelen_afgifte__bool`, `heeft_luchtverwarming__bool`, `heeft_radiatoren__bool`,
`heeft_vloerverwarming__bool`.

Beide taglijsten zijn geverifieerd tegen álle voorkomende tokens in de dataset (25-aug-2026); een
nieuw, ongezien token in een latere data-levering geeft een `SchemaError`, geen stille misser.

## `measurements` (uit `IM_customer_<id>.csv`)

Sinds `ontwerp-intervalsemantiek.md` bevat `measurements` uitsluitend **aannamevrije conversies**:
geen energiewaarden meer (`__kWh`/`__m3`), alleen het gemiddelde vermogen over het interval (`__W`).
Gas (`g_gebruik__m3_s_1`/`g_gebruik__W`) staat sinds diezelfde wijziging in `derived`, niet meer
hier (zie de toelichting daar).

| ruwe kolom | standardized kolom | dtype | opmerking |
|---|---|---|---|
| bestandsnaam | `home_id__str` | `str` | |
| `datetime` + `interval` | `tijdstip_start` | `datetime64[ns, Europe/Amsterdam]` | **begin** van het interval, voor alle vier de typen (zie `timestamps.resolve_timestamps` en `ontwerp-intervalsemantiek.md` §1/§4). Wijkt af van RVO's eigen bronconventie, die `q`/`h` op het EINDE zet: terugrekenen naar de bronconventie is `tijdstip_start + interval_duur__s` voor `q`/`h`, `tijdstip_start` ongewijzigd voor `d`, en "laatste dag van dezelfde maand" voor `m` |
| `interval` | `interval_type__cat` | `category` | `q`/`h`/`d`/`m`, behouden |
| (afgeleid) | `interval_duur__s` | `int32` | zie `intervals.compute_interval_duur_s`, zomertijd-aware voor d/m; beschrijft de lengte van het interval, **niet** de deler voor de vermogens-afleiding bij `m` (zie hieronder) |
| (afgeleid) | `granulariteit__cat` | `category` | `kwartier_totaal` / `uur_totaal` / `dag_totaal` / `maand_gemiddeld_per_dag` |
| `elec` | `e_net__W` | `float32` | `e_net__kWh * 3.6e6 / deler_s`, negatief = teruglevering. `deler_s = interval_duur__s` voor q/h/d, maar **86.400 s (één dag) voor m**: een m-waarde is het gemiddelde dagverbruik van die maand, geen maandtotaal (hoofdontwerp §2.1), dus delen door de maandduur zou een factor ~30 te laag geven (`ontwerp-intervalsemantiek.md` §2; zie `intervals.compute_energie_deler_s`) |
| `wind`, `temp`, `sun` | (vervalt) | | verplaatst naar `weer.parquet`, niet in `measurements` (§5.1); de RVO-geleverde reeks zelf staat niet meer in de output (§12.8) |

## `weer`

Blijft ongewijzigd door `ontwerp-intervalsemantiek.md` (§4, "Wat er NIET verandert"): de KNMI-reeks
was al op begin-van-het-uur gelabeld, dus `tijdstip` betekent hier al hetzelfde als `tijdstip_start`
elders en wordt niet hernoemd.

| kolom | dtype | opmerking |
|---|---|---|
| `weerstation_nr` | `int16` | KNMI-stationscode |
| `tijdstip` | `datetime64[ns, Europe/Amsterdam]` | uurresolutie, begin van het uur |
| `temp_buiten__degC`, `wind__m_s_1` | `float32` | |
| `ghi__W_m_2` | `float32` | gemiddelde instraling over dat uur (een flow, geen energietotaal); was tot `ontwerp-intervalsemantiek.md` §3 `ghi__kWh_m_2` (÷1000, verkeerd gelabeld als energie) |
| `bron__cat` | `category` | `"eigen_ingest"`: de rauwe uurwaarde van het KNMI-station zelf, opgehaald via `needforheat-dutch-weather-software` (sinds §12.13 zonder RBF-geospatiale interpolatie, want er wordt altijd een bekend station opgevraagd) / `"eigen_ingest_geointerpoleerd"`: idem mét die interpolatiestap, alleen aanwezig na `--weer-geointerpoleerd-diagnose`. De RVO-geleverde reeks (`"im3"`) staat sinds §12.8 niet meer in de output |

## `quality`

Sleutel: `home_id__str`, `tijdstip_start`, `interval_type__cat` (zelfde betekenis als in
`measurements`). Vlaggen werken sinds `ontwerp-intervalsemantiek.md` §3 op de FLOW-kolommen
(`e_net__W`, `g_gebruik__m3_s_1`), niet meer op de energiekolommen: delen door een positieve duur
verandert het teken en de nul-eigenschap nooit, dus blijven alle onderstaande checks inhoudelijk
geldig op de flow-waarden.

| kolom | dtype | opmerking |
|---|---|---|
| `e_net_ontbrekend__flag` / `g_gebruik_ontbrekend__flag` | `bool` | `isna()` is per definitie nooit onbepaald |
| `g_gebruik_negatief__flag` | `boolean` (nullable) | `pd.NA` bij een all-electric woning zonder gas-kolom: "niet van toepassing", geen "nee" |
| `e_net_constante_reeks__flag` / `g_gebruik_constante_reeks__flag` | `boolean` (nullable) | hele reeks van die woning+interval_type varieert nooit (std==0); zie `quality.constante_reeks_flags` |
| `e_net_uitschieter__flag` / `g_gebruik_uitschieter__flag` | `boolean` (nullable) | > 3σ van het (woning, interval_type)-gemiddelde; zie `quality.uitschieter_flags` |

## `derived`

Alles wat een externe waarde of koppeling nodig heeft. `e_net__W` staat sinds
`ontwerp-intervalsemantiek.md` §3 in `measurements` (aannamevrij, geen externe waarde nodig) en dus
niet meer hier. `g_gebruik__m3_s_1` staat hier wél (en niet in `measurements`): dat maakt
`measurements` niet langer een volledige standaardisatie van de twee brongrootheden (`elec`/`gas`),
de prijs voor een `derived` die zelfstandig leesbaar is voor gasanalyse (volumestroom, vermogen en
de gebruikte calorische waarde bij elkaar).

| kolom | dtype | opmerking |
|---|---|---|
| `g_gebruik__m3_s_1` | `float32` | `g_gebruik__m3 / deler_s`, aannamevrije volumestroom. `deler_s` is dezelfde m-rij-correctie als bij `e_net__W` hierboven (86.400 s voor m, anders `interval_duur__s`) |
| `g_gebruik__W` | `float32` | `g_gebruik__m3_s_1 * actual_gas_std_hhv__J_m_3` (volumestroom × calorische waarde, geen aparte deling meer nodig) |
| `actual_gas_std_hhv__J_m_3` | `float32` | werkelijke, NL-gemiddelde calorische waarde per uur (`gaskwaliteit.py`, `mijnenergiedata.nl`); valt terug op de vaste Groningen-gas-constante buiten het opgehaalde venster |
| `gas_hhv_bron__cat` | `category` | `"mijnenergiedata_actueel"` / `"vast_gemiddelde_fallback"` |
| `weerkoppeling_methode__cat` | `category` | `punt_interpolatie` (q) / `punt_uur` (h) / `gemiddelde_dag` (d) / `gemiddelde_maand` (m) / `ontbrekend_buiten_archief` |
| `temp_buiten__degC`, `wind__m_s_1`, `ghi__W_m_2` | `float32` | gekoppeld weer, zie `weerkoppeling_methode__cat`. `ghi__W_m_2` was `ghi__kWh_m_2` (zie `weer`-tabel hierboven) |

### Energie is verliesvrij terug te rekenen

Er gaat geen informatie verloren door alleen nog vermogen weg te schrijven: `E = P x interval_duur__s`
(en voor `m`-rijen `P x 86.400`) geeft de energie terug tot op de float32-afrondgrens
(gemeten max. relatieve fout 1,16e-7 op 2 miljoen waarden per intervaltype, zie
`ontwerp-intervalsemantiek.md` §3).
