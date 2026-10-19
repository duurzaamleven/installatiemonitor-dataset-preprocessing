# Datakwaliteitsrapport

**Gegenereerd door** `im3_preprocessing.report`, niet handmatig bijgehouden (ontwerp §9).

## Overzicht

- Aantal woningen: 6283
- Aantal measurement-rijen: 537.470.922
- Periode: 2021-06-01 00:00:00+02:00 .. 2026-02-04 23:45:00+01:00
- Granulariteit-verdeling: d=4.473.988, h=104.108.502, m=220.279, q=428.668.153

## §2.2 Woningtype-afkapping in de bron

- 1841 van 6283 woningen (29,3 %) hadden een afgekapte `Woningtype`-waarde in de bron, hersteld naar de volledige categorie (`woningtype_bron_afgekapt__bool`-vlag).

## §12.1 Woningen zonder `gas`-kolom in de bron (all-electric)

- 707 van 6283 woningen in deze run hadden geen `gas`-kolom in het bronbestand (geen gasaansluiting), aangevuld met NaN en nooit 0. Over de volle dataset was dit 707/6.283 (11,3%), geverifieerd 26-aug-2026 (ontwerp §12.1). `g_gebruik_ontbrekend__flag` is voor deze woningen structureel 100%, en dat is verwacht gedrag, geen datakwaliteitsprobleem.

## Cleaning-vlaggen (`quality.parquet`)

- `e_net_ontbrekend__flag`: 0 rijen (0,0 %)
- `g_gebruik_ontbrekend__flag`: 439.621.834 rijen (81,8 %)
- `g_gebruik_negatief__flag`: 2690 rijen (0,0 %)
- `e_net_constante_reeks__flag`: 125.057 rijen (0,0 %)
- `g_gebruik_constante_reeks__flag`: 9.344.417 rijen (1,7 %)
- `e_net_uitschieter__flag`: 7.558.447 rijen (1,4 %)
- `g_gebruik_uitschieter__flag`: 2.332.051 rijen (0,4 %)

`*_constante_reeks__flag`: de HELE reeks van die woning+interval_type varieert nooit (std==0). Een tijdelijke reeks identieke waarden (ook exacte nullen, ook niet-nul) telt hier niet mee, want dat is op zichzelf geen bewijs van een kapotte sensor (ontwerp §3 principe 4; zelfde aanpak als `Preprocessor.filter_id_prop_with_std_zero` in needforheat-diagnosis-software). `*_uitschieter__flag`: > 3,0σ van het (woning, interval_type)-gemiddelde (`Preprocessor.filter_static_outliers`), een voorlopige, niet extern gevalideerde drempel.

## §12.6 Hypothese: meterwissel + ontbrekend filter in de prepublicatiefase

**Hypothese** (26-aug-2026, nog niet bevestigd door RVO/KITE): extreem negatieve waarden (vooral op `m`-rijen) worden veroorzaakt door een meterwissel (elektra en/of gas) waarbij RVO's eigen prepublicatieproces de knik tussen de oude en de nieuwe cumulatieve meterstand niet filtert vóór het verschillen/aggregeren.

De meest extreme uitschieters in deze run (top 10, `beide_uitschieter__bool`=True betekent dat zowel `e_net__W` als `g_gebruik__m3_s_1` voor diezelfde woning+tijdstip als uitschieter zijn gevlagd: een sterkere aanwijzing voor een gelijktijdige meterwissel dan een uitschieter in slechts één signaal):

| woning | tijdstip_start | interval | veld | waarde | beide (e+g) uitschieter |
|---|---|---|---|---|---|
| 5694 | 2024-11-23 18:15:00+00:00 | q | `e_net__W` | 40.003.860,00 | False |
| 2210 | 2025-03-08 15:45:00+00:00 | q | `e_net__W` | 40.000.368,00 | False |
| 5694 | 2025-11-26 11:45:00+00:00 | q | `e_net__W` | 39.999.972,00 | False |
| 7673 | 2025-09-05 04:15:00+00:00 | q | `e_net__W` | -39.999.832,00 | False |
| 5423 | 2024-01-02 03:45:00+00:00 | q | `e_net__W` | -39.999.832,00 | False |
| 2210 | 2026-01-05 00:15:00+00:00 | q | `e_net__W` | -39.999.792,00 | False |
| 5434 | 2024-07-07 16:15:00+00:00 | q | `e_net__W` | -39.999.792,00 | False |
| 5694 | 2024-05-26 00:15:00+00:00 | q | `e_net__W` | -39.999.764,00 | False |
| 1670 | 2024-10-29 07:30:00+00:00 | q | `e_net__W` | -39.999.760,00 | False |
| 2711 | 2025-07-02 13:30:00+00:00 | q | `e_net__W` | -39.999.732,00 | False |

**Hoe `needforheat-diagnosis-software` dit deel** (`Preprocessor.property_filter`, `process_meter_reading=True`): werkt op de **cumulatieve** meterstand (niet op een al-verschilde reeks zoals IM3 publiceert), neemt het verschil tussen opeenvolgende standen, en zet elk **negatief** verschil expliciet op 0 (een cumulatieve meterstand kan nooit dalen; een negatief verschil is dus per definitie een meterwissel/-reset, geen gebruik) vóór de reeks weer op te cumuleren en opnieuw te verschillen. Dat gebeurt **vóór** de z-score-uitschieterdetectie; de laatste is bij hen een extra vangnet, niet de eerste verdedigingslijn.

**Waarom deze preprocessing dat zelf niet kan repareren:** IM3 publiceert alleen de al-verschilde reeks, niet de onderliggende cumulatieve meterstanden. De correctie die needforheat-diagnosis-software toepast is dus alleen mogelijk **vóór** publicatie, in RVO/KITE's eigen pijplijn. Deze preprocessing kan de symptomen alleen signaleren (`*_uitschieter__flag`), niet de oorzaak wegnemen; vandaar de aanbeveling hieronder.

**Aanbeveling voor de makers van de prepublicatiefase (RVO/KITE/BDH):** vóór het verschillen/aggregeren naar kwartier-/uur-/dag-/maandwaarden, controleer of de onderliggende cumulatieve meterstand ooit **daalt** tussen twee opeenvolgende aflezingen, en dat kan alleen bij een meterwissel/-reset, nooit bij normaal gebruik. Zet dat specifieke interval op 0 (of vlag het) in plaats van het als een geldig, extreem negatief verbruik te publiceren. Zie `needforheat-diagnosis-software`'s `Preprocessor.property_filter` voor een werkende implementatie van dit principe. Dit hoort meegenomen te worden in een volgend inhoudelijk overleg met RVO/KITE (§4/§10.1), niet als losse technische bug-report.

## §12.7 Gas op exact 0 vóór koppeling: waarschijnlijk 'nog niet gemeten', geen genuine nul

**Let op: dit is een ANDER punt dan §2.3/§12.6.** Dat `d`/`m`-rijen verder teruggaan dan `h`/`q` is zelf verwacht, gedocumenteerd gedrag (§2.3): een ODA kan via de netbeheerder historische dagstanden opvragen (zie [dsmr-info](https://github.com/energietransitie/dsmr-info) voor de achtergrond van het DSMR/P1-ecosysteem), dus dat verbruik vóór het live-monitoring-moment alsnog uit dag-/maandstanden gevuld wordt, is op zichzelf niet verkeerd. Dit punt gaat specifiek over de **waarde 0** die daarbij voor gas verschijnt waar dat niet aannemelijk is.

711 woning(en) in deze run hadden de eerste 60 dagen met een `d`-gasrij stuk voor stuk exact 0, waarvan 62 met metadata die reëel gasgebruik verwacht (`Koken_op_gas` of een HR-ketel). Voor die woning(en) is permanent nul gas voor twee maanden niet aannemelijk, en is `NaN` (nog niet gekoppeld) logischer dan een genuine 0.

| woning | eerste 60 dagen altijd 0 | kookt op gas | heeft HR-ketel | fractie 0 in latere periode | verdacht |
|---|---|---|---|---|---|
| 1027 | True | True | True | 0,39 | True |
| 6876 | True | True | False | 0,23 | True |
| 2836 | True | False | True | 0,72 | True |
| 2859 | True | False | True | 1,00 | True |
| 3896 | True | False | True | 1,00 | True |
| 2912 | True | False | True | 1,00 | True |
| 1805 | True | True | True | 1,00 | True |
| 2971 | True | False | True | 1,00 | True |
| 5961 | True | False | True | 1,00 | True |
| 1740 | True | False | True | 1,00 | True |
| 7645 | True | True | False | 0,53 | True |
| 7654 | True | True | True | 0,44 | True |
| 7658 | True | True | True | 0,39 | True |
| 7685 | True | False | True | 0,40 | True |
| 9081 | True | False | True | 0,76 | True |

(Ingekort tot de eerste 15 van 711 rijen.)

Een woning die ook in de latere periode permanent op 0 blijft staan (en waarvoor geen gasgebruik verwacht wordt) is hier terecht **niet** als verdacht gemarkeerd; dat is zelf-consistent (bv. een all-electric woning met een letterlijke, niet-ontbrekende gaskolom vol nullen, in tegenstelling tot de woningen uit §12.1 die de kolom helemaal missen).

**Nog niet bevestigd, alleen gerapporteerd** (ontwerp §3 principe 5): dit is een hypothese op basis van steekproefbewijs, geen aangenomen regel, en zeker geen aanleiding om deze 0-waarden zelf naar NaN om te zetten zonder externe bevestiging. Hoort net als §12.6 meegenomen te worden in een volgend inhoudelijk overleg met RVO/KITE.

## §7.1 q/h-som versus dagwaarde

- Som van kwartierrijen (q) vs. dagwaarde: 4.104.423 dagen vergeleken, mediane absolute afwijking 0,000 kWh, 95e percentiel 0,806 kWh.
- Som van uurrijen (h) vs. dagwaarde: 4.059.380 dagen vergeleken, mediane absolute afwijking 0,000 kWh, 95e percentiel 0,943 kWh.

  (Vergelijking gebruikt het lokale-dagvenster, niet een naïef UTC-etmaal; ontwerp §2.4.)

## §2.4 Zomertijdovergangen: ontbrekende d-rijen op de transitiedatum

- Van de 50.264 (woning × transitiedatum)-combinaties: 50.264 zonder d-rij op exact die datum (100,0 %).
  Ontwerp §2.4 verwacht hier **0%** aanwezig (dus 100% afwezig) over de volle dataset Dat is een patroon, geen toevallige uitval.

## §10.3 Komt gas ooit negatief voor? (open vraag, alleen gerapporteerd)

- 2690 rijen met negatieve `g_gebruik__m3_s_1`, verspreid over 235 woning(en) in deze run.
  Dit wordt pas een cleaning-regel na bevestiging over de volle dataset (§3 principe 5) Hier alleen geregistreerd.

## §7.2/§7.3 Consistentie IM3-weer vs. eigen KNMI-ingest

Voorlopige, vooraf vastgelegde matchdrempels (open vraag §10.4, nog niet extern bevestigd): temperatuur < 0,5 °C, wind < 0,5 m/s, ghi < 50 W/m² (mediane absolute afwijking).

> RVO's `sun` is gesommeerde instraling in kWh/m² per interval; vóór de vergelijking is die omgerekend naar gemiddelde W/m² (x 1000 / duur in uren), dezelfde eenheid als KNMI's `Q` in de eigen ingest. Een mediaan over alle uren telt ook de nachturen mee (beide 0), dus bij instraling zegt een lage mediaan weinig over de uitschieters overdag.

> De IM3-geleverde reeks zelf staat **niet** in `weer.parquet` (§12.8): die wordt per woning gedupliceerd aangeleverd en is altijd terug te halen uit de bron. Hij wordt tijdens de run wel ingelezen om deze consistentiecheck te kunnen doen.

| station | n overlap | temp mediane afw. (°C) | binnen drempel | wind mediane afw. (m/s) | binnen drempel | ghi mediane afw. (W/m²) | binnen drempel |
|---|---|---|---|---|---|---|---|
| 210 | 24749 | 0,600 | False | 2,000 | False | 0,0 | True |
| 235 | 24763 | 0,000 | True | 0,000 | True | 0,0 | True |
| 240 | 25062 | 0,600 | False | 1,062 | False | 0,8 | True |
| 249 | 24794 | 0,000 | True | 0,000 | True | 0,0 | True |
| 251 | 21437 | 0,000 | True | 0,000 | True | 0,0 | True |
| 260 | 28925 | 0,000 | True | 0,000 | True | 0,0 | True |
| 269 | 24746 | 0,000 | True | 0,000 | True | 0,0 | True |
| 270 | 24894 | 0,000 | True | 0,000 | True | 0,0 | True |
| 273 | 22919 | 0,000 | True | 0,000 | True | 0,0 | True |
| 275 | 24971 | 0,000 | True | 0,000 | True | 0,0 | True |
| 278 | 30096 | 0,000 | True | 0,000 | True | 0,0 | True |
| 279 | 24940 | 0,000 | True | 0,000 | True | 0,0 | True |
| 280 | 24925 | 0,000 | True | 0,000 | True | 0,0 | True |
| 283 | 24926 | 0,000 | True | 0,000 | True | 0,0 | True |
| 286 | 24972 | 0,000 | True | 0,000 | True | 0,0 | True |
| 290 | 24878 | 0,000 | True | 0,000 | True | 0,0 | True |
| 310 | 24321 | 0,000 | True | 0,000 | True | 0,0 | True |
| 319 | 24183 | 0,000 | True | 0,000 | True | 0,0 | True |
| 340 | 23822 | 0,500 | False | 1,000 | False | 0,2 | True |
| 344 | 28624 | 0,000 | True | 0,000 | True | 0,0 | True |
| 348 | 24632 | 0,000 | True | 0,000 | True | 0,0 | True |
| 350 | 24998 | 0,000 | True | 0,000 | True | 0,0 | True |
| 356 | 24942 | 0,000 | True | 0,000 | True | 0,0 | True |
| 370 | 25046 | 0,000 | True | 0,000 | True | 0,0 | True |
| 375 | 24852 | 0,000 | True | 0,000 | True | 0,0 | True |
| 377 | 24821 | 0,000 | True | 0,000 | True | 0,0 | True |
| 380 | 24927 | 0,000 | True | 0,000 | True | 0,0 | True |
| 391 | 22209 | 0,000 | True | 0,000 | True | 0,0 | True |

**Station(s) [210, 240, 340] vallen buiten de drempel.** Dit is een bevinding, geen cleaning-beslissing (§7.3 stap 3): eerst uitzoeken wat het verschil verklaart (ander station, ander KNMI-product, interpolatiemethode, tijdzone-offset) vóór te kiezen welke bron 'juist' is.

## Calorische gaswaarde (`derived.actual_gas_std_hhv__J_m_3`)

`g_gebruik__W` gebruikt zoveel mogelijk de **werkelijke**, per-uur gepubliceerde calorische waarde (NL-gemiddelde over netgebieden, via `mijnenergiedata.nl/calorische-gaswaarden`, zie `gaskwaliteit.py`) i.p.v. een vaste Groningen-gas-constante. IM3 levert geen netbeheerder/netgebied per woning, dus dit is een NL-breed gemiddelde, geen exacte per-woning-waarde.

- Bron van de gebruikte calorische waarde in deze run: `mijnenergiedata_actueel`=537.470.922, `vast_gemiddelde_fallback`=0. `vast_gemiddelde_fallback` gebruikt de publieke Gaswet-referentiewaarde (35,17 MJ/m³) en hoort in een volledige run een uitzondering te zijn, niet de meerderheid.

## Bekende, nog niet extern bevestigde aannames

- Matchdrempels voor de weer-consistentiecheck (hierboven) zijn een voorlopige keuze, geen extern bevestigde norm (§10.4).
- `UITSCHIETER_N_SIGMA = 3.0` (z-score-drempel voor `*_uitschieter__flag`) is een voorlopige, statistisch gangbare keuze, niet extern gevalideerd voor déze dataset.
- De calorische-gaswaarde-API (`mijnenergiedata.nl`) is niet publiek gedocumenteerd, ontdekt via inspectie van de website zelf, kan zonder aankondiging wijzigen.
