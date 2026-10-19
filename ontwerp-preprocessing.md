# Ontwerp: preprocessing van de Installatiemonitor 3.0-dataset

**Status:** ontwerp, nog geen implementatie. Bedoeld als startpunt voor wie (mens of AI-collega)
de daadwerkelijke preprocessing hierna bouwt.

**Herkomst van dit document.** Gebaseerd op een eerste analyse door een ander AI-model (structuur
raw→standardized→cleaned→derived, aansluiting bij de Windesheim/NeedForHeat-datasets zoals Twomes
en Brains4Buildings, `physiquant__unit`-naamgeving). Die analyse is hier aangepast op basis van
**daadwerkelijke inspectie van de nu gedownloade dataset** (`dataset_openbaar/`, 6.283 woningen) en
op kennis van een aansluitend, niet-openbaar simulatieproject dat deze preprocessing straks als
validatiebron gaat gebruiken.

## 0. Wat dit is en niet is

Dit is een **preprocessinglaag**, geen analyse. Doel: van 6.283 losse CSV's met een eigenzinnige
tijdas naar een klein aantal goed getypeerde, herleidbare, semantisch eenduidige tabellen, zonder
al aannames te maken die bij een specifieke analysevraag horen (H/C/τ-schatting, COP-modellen,
vakantiedetectie). Die aannames horen thuis in een latere, aparte analysestap (mogelijk deels in
deze repo als tweede module, mogelijk in een aansluitend analyseproject).

## 1. De brondata, zoals ze werkelijk zijn (niet zoals het rapport ze beschrijft)

`dataset_openbaar/` bevat:

- `00_IM_meta_data_openbaar.csv`: 6.283 woningen × 18 kenmerken (statisch), waaronder
  `Weerstation_nr`/`Weerstation naam`: **28 unieke KNMI-stations** voor alle 6.283 woningen samen.
- `00_Informatie document IM dataset - 20260820.pdf`: RVO's eigen gebruiksvoorwaarden +
  datadictionary (v1.0, 20-08-2026).
- 6.283 bestanden `IM_customer_<id>.csv`: één lange tabel per woning, kolommen
  `datetime,elec,interval,gas,wind,temp,sun`, alle vier granulariteiten (`q`/`h`/`d`/`m`) **door
  elkaar in dezelfde kolommen**, onderscheiden via de `interval`-kolom. Totale omvang: **~23,9 GB**
  ongecomprimeerde CSV (zip: 3,2 GB).

RVO's eigen intervalsemantiek (uit het informatiedocument, met een letterlijk voorbeeld erin) is
eenduidig en **klopt met wat er in de q/h/d-rijen staat**:

| interval | dekt | timestamp op regel | voorbeeld |
|---|---|---|---|
| `q` (kwartier) | 12:00–12:15 | **einde** van het interval | regel `12:15` |
| `h` (uur) | 12:00–13:00 | **einde** van het interval | regel `13:00` |
| `d` (dag) | 00:00–23:59 | **begin** van de dag zelf | regel `<dag> 00:00` |
| `m` (maand) | 1e t/m laatste dag | **laatste dag** van de maand, 00:00 | regel `<laatste dag> 00:00` |

**`d` en `m` zijn dus anders verankerd dan `q` en `h`**, niet allemaal "einde van interval". Een
naïeve resampler die overal dezelfde ankerregel aanneemt, zit er voor `d`/`m` naast. Dit moet
expliciet in de documentatie en bij voorkeur in code als een aparte functie per intervaltype, niet
als één generieke "shift by duration".

**Tweede, scherpere reden om `d`/`m` niet naïef te behandelen: het zijn kale lokale datums, geen
UTC-tijdstempels.** `datetime` bij `q`/`h` is een volwaardige UTC-tijdstempel (`2023-03-01
00:15:00+00:00`); `datetime` bij `d`/`m` is een kale datum zonder tijdzone (`2023-01-30`,
`2022-03-31`), en die datum hoort, gezien de herkomst (meterstanden/ODA, zie §2.3), bij de
**lokale kalenderdag** (Europe/Amsterdam), niet bij een UTC-etmaal. Dat raakt de zomertijd direct:
zie §2.4.

Zie §2.3 en §2.4 voor twee aanvullende, hieraan gerelateerde punten die pas zichtbaar worden zodra
je q/h tegen d/m legt.

Elektra is een **verschilstand** (niet cumulatief), inclusief teruglevering als negatieve waarde
("hoog/laag én levering gecombineerd"). Gas is eveneens een verschilstand; volgens de
brondocumentatie niet-negatief (niet zelf geverifieerd op uitzonderingen; zie §3, opnemen als
cleaning-check in plaats van als aanname). Weer (`wind`,`temp`,`sun`) is gekoppeld aan de tijdas en
staat in de steekproef **alleen gevuld op `h`-rijen**: 19,4% van alle rijen in een steekproef van
15 woningen (q 79,7% · h 19,4% · d 0,8% · m 0,04%).

## 2. Vier geverifieerde bevindingen (niet hypothetisch, maar gemeten in de echte dataset)

Dit zijn geen slides uit een generieke preprocessing-checklist; dit zijn concrete bevindingen,
gecontroleerd op 25-augustus-2026 door direct in de gedownloade bestanden te rekenen. De eerste
twee zijn datadefecten; de laatste twee (§2.3, §2.4) zijn geen fouten maar structurele
eigenschappen van de dataset die het ontwerp direct raken.

### 2.1 De `m`-rijen zijn géén maandtotaal, ondanks wat het informatiedocument zegt

RVO's eigen voorbeeld zegt: *"Maand: verbruik tussen 1e en laatste dag van de maand staat bij de
regel met de laatste dag"*. Dat suggereert een **som**, net als bij dag/uur/kwartier. De praktijk
is anders. Op een steekproef van 25 willekeurige klantbestanden, per maand waar zowel `d`- als
`m`-rijen aanwezig zijn (≥25 dagen met een `d`-waarde):

```
m_waarde / (Σ d_waarden die maand / aantal_dagen_met_d)  ≈ 1,00   (mediaan van 25 bestanden: 0,92–1,73, meeste rond 1,0)
```

met andere woorden: **de `m`-waarde is het gemiddelde dagverbruik van die maand, niet de
maandsom.** Voorbeeld, klant 1000, februari 2023: Σ dag-elektra = 578,1 kWh over 28 dagen →
gemiddelde 20,65 kWh/dag; de `m`-rij voor 2023-02 bevat **20,648**, tot op drie decimalen gelijk
aan het dagéémiddelde, een factor ~28 te laag om een maandtotaal te zijn.

**Consequentie voor deze preprocessing:** `m`-rijen niet zomaar meenemen als extra bron voor
maandtotalen (ze zouden de vroege periode, vóór de kwartier/uur-monitoring startte, ~30× te laag
laten meewegen). Voorstel: `m`-waarden intern taggen als `granulariteit=maand_gemiddeld_per_dag`
(niet als `..._totaal`) en dat expliciet in `docs/data-description.md` documenteren als afwijking
van de eigen RVO-datadictionary. Voor de vroege periode (vóór aanmelding, alleen `d`/`m`
beschikbaar) blijft dit de enige bron: dus niet weggooien, wel correct labelen en pas na
onafhankelijke bevestiging (bijvoorbeeld terug-optellen met een tweede klantbestand) als vaststaand
beschouwen. Dit hoort als quality-opmerking in het `docs/data-quality.md`-rapport, niet stilzwijgend
gecorrigeerd.

### 2.2 `Woningtype` is bij 29% van de woningen afgekapt

In de metadata-CSV komt `Woningtype` voor als `'Rijwoning (tussen'` (1.100×) en `'Rijwoning (hoek'`
(741×), samen 1.841 van de 6.283 rijen (29%), kennelijk bedoeld als `Rijwoning (tussenwoning)` en
`Rijwoning (hoekwoning)` maar afgekapt bij een haakje/leesteken in de bron-export. De overige drie
categorieën (`Vrijstaand`, `Twee-onder-een-kap`, `Appartement`) zijn niet aangetast.

**Consequentie:** dit is geen ontbrekende waarde en geen typfout van één record: het raakt bijna
een derde van de steekproef en moet als **bekende, gedocumenteerde brondefect** in
`docs/data-quality.md`, met de aanbeveling om vóór gebruik bij RVO/KITE na te vragen of de
oorspronkelijke, onverkorte waarde elders (bijv. het onderliggende systeem) is te achterhalen.
Voor preprocessing: de twee afgekapte waarden gewoon behouden als eigen categorieën (niet raden
welke van de twee volledige waarden bedoeld is, en dat kán met zekerheid, `(tussen` → tussenwoning en
`(hoek` → hoekwoning, dus dit is hier zonder risico op te lossen), maar wel met een
`woningtype_bron_afgekapt__bool`-vlag zodat herleidbaar blijft dat de brontekst onvolledig was.

### 2.3 `d`/`m` beginnen aantoonbaar eerder dan `h`/`q`, en weer staat daar nooit bij

Dit was een expliciete vraag vooraf (klopt het dat ODA-achtige bronnen een langere geschiedenis
hebben dan de fijnmazige intervalwaarden?) en het antwoord is: **ja, aantoonbaar.** Op een
steekproef van 12 willekeurige klantbestanden, per bestand het vroegste tijdstip per intervaltype:

| bestand (voorbeeld) | `m` start | `d` start | `h`/`q` start | verschil m→h/q |
|---|---|---|---|---|
| IM_customer_1136 | 2022-04-30 | 2023-03-14 | 2023-04-13 | **~1 jaar** |
| IM_customer_1633 | 2022-09-30 | 2023-04-18 | 2023-05-18 | **~8 maanden** |
| IM_customer_6382 | 2022-11-30 | 2023-09-14 | 2023-10-13 | **~11 maanden** |
| IM_customer_5326 | 2022-10-31 | 2023-08-29 | 2023-09-27 | **~11 maanden** |

(alle 12 bestanden uit de steekproef tonen hetzelfde patroon: `m` het vroegst, `d` ongeveer één
maand vóór `h`/`q`, en `h`/`q` altijd gelijk aan elkaar beginnend.) Dat klopt met de eigen
toelichting van RVO: bij aanmelding haalt BDH (met ODA-certificering) de **historische
meterstanden** op (dag- en maandinterval) en pas ván de aanmelddatum (= maand van
WP-installatie) loopt de kwartier-/uurmonitoring. `d`-rijen lopen overigens **door** na de start van
`h`/`q` (dezelfde eindddatum als `h`/`q` in alle 12 bestanden): het is dus niet alleen een
historische opvulling, `d` blijft een parallelle, grovere reeks gedurende de hele looptijd.

**En op diezelfde 12 bestanden: geen enkele `d`- of `m`-rij heeft ooit een gevulde
`wind`/`temp`/`sun`-waarde.** Weer staat in de brondata uitsluitend op `h`-rijen. Dat betekent
concreet: voor de **historische periode vóór aanmelding** (tot ~1 jaar, zie tabel) levert IM3 zelf
**geen weer**, terwijl er voor die periode wél verbruiksdata is (op dag-/maandniveau).

**Consequentie voor `weer.parquet` (§5.1/§7.3):** de eigen weer-acquisitie moet niet beperkt worden
tot de periode die IM3's `h`-rijen toevallig dekken. KNMI-archieven gaan voor vrijwel elk station
decennia terug, dus er is geen technische reden om de eigen ingest te laten beginnen bij de eerste
`h`-rij van een woning: laat hem starten bij de eerste `m`-rij (de vroegste beschikbare
verbruiksdatum voor die woning). Zo dekt de eigen, reproduceerbare weerreeks het **hele**
verbruiksbereik, inclusief precies het stuk waar IM3 zelf niets levert, en dat is dan ook de enige
plek waar er geen IM3-eigen reeks is om tegen te consistency-checken (§7.2); voor dat stuk is er
sowieso geen alternatief dan de eigen ingest vertrouwen.

**En dat vraagt een herkomst-/resolutielabel, niet alleen een aan/uit-vlag.** Omdat de eigen ingest
(KNMI-archief) vrijwel altijd uurresolutie is, maar de rij waaraan hij gekoppeld wordt niet (`q`:
fijner dan het weer zelf, `h`: exacte match, `d`/`m`: grover), verschilt de manier van koppelen per
rij. Voorstel: geen aparte resolutiekolom in `weer.parquet` zelf (dat blijft één homogene,
uurresolutie-reeks per station, zie §5.1), maar een `weerkoppeling_methode__cat` op de
**gekoppelde** tabel (`derived.parquet` of een aparte `weer_gekoppeld.parquet`), met waarden als:

| waarde | wanneer |
|---|---|
| `punt_interpolatie` | `q`-rij: weer geïnterpoleerd tussen omliggende uurwaarden |
| `punt_uur` | `h`-rij: exacte uurmatch |
| `gemiddelde_dag` | `d`-rij: gemiddelde van de eigen uurreeks over de lokale kalenderdag (zie §2.4 voor de lengte daarvan) |
| `gemiddelde_maand` | `m`-rij: gemiddelde van de eigen uurreeks over de kalendermaand |
| `ontbrekend_buiten_archief` | eigen KNMI-bron dekt de periode niet (stationsstart, archieflimiet) |

### 2.4 Zomertijdovergangen: `d` is niet altijd 24 uur, en dat raakt meer dan alleen `d`

`q`/`h` zijn UTC-tijdstempels (bevestigd door RVO's document én de data: `+00:00`-suffix). Daardoor
heeft **elke UTC-kalenderdag altijd exact 96 kwartier-/24 uur-rijen**: UTC kent geen zomertijd, dus
daar zit geen probleem. Het probleem zit in `d` en `m`: die zijn kale lokale datums (§2, tabel), en
een lokale kalenderdag (Europe/Amsterdam) is **niet altijd 24 uur**:

- de nacht van de voorjaarsovergang (laatste zondag van maart, 02:00 → 03:00) telt lokaal **23 uur**;
- de nacht van de najaarsovergang (laatste zondag van oktober, 03:00 → 02:00) telt lokaal **25 uur**.

Twee concrete gevolgen voor deze preprocessing, geen van beide triviaal:

1. **`interval_duur__s` voor `d`-rijen is niet altijd 86.400.** Op de twee overgangsdagen per jaar is
   dat 82.800 s (23 u) resp. 90.000 s (25 u). Een hardcoded `86400` geeft op precies die twee dagen
   per jaar een systematische fout van ±4% in elke `g_gebruik__W`/`e_net__W`-afleiding op dagniveau.
   Bereken `interval_duur__s` voor `d` dus altijd uit het echte lokale-dag-venster
   (`Europe/Amsterdam`-aware start/eind, niet een aangenomen vaste lengte), dezelfde soort logica
   als elders al bestaat voor een zomertijd-correcte tijdas (zie de kanttekening hieronder).
2. **De `q`-vs-`d`-consistencycheck (§7.1) moet het lokale-dagvenster gebruiken, niet een naïef
   UTC-etmaal.** Als je voor een `d`-rij van datum `X` de som van de `q`-rijen in het UTC-venster
   `[X 00:00, X+1 00:00)` neemt, tel je op de twee overgangsdagen per jaar een uur te weinig of te
   veel mee (het UTC-etmaal en het lokale etmaal vallen dan niet meer samen), en dat geeft een
   **valse** afwijking die niets met datakwaliteit te maken heeft, maar met een verkeerd tijdvenster.
   Neem voor elke `d`-rij het venster `[Europe/Amsterdam X 00:00, Europe/Amsterdam X+1 dag 00:00)`,
   omgerekend naar UTC voor de join met `q`/`h`; dat venster is vanzelf 23, 24 of 25 uur, precies
   passend.

**Geverifieerd, over de volle dataset (niet alleen een steekproef):** een uitputtende scan van alle
6.283 klantbestanden op de 8 zomertijddata tussen 2022 en 2025 vindt **geen enkele `d`-rij met een
ingevulde waarde op precies die datum**: nul van de 8×6.283 mogelijke combinaties. `d`-rijen hebben
sowieso gaten (gemiddeld ~53% dagdekking in de periode waarin ze voorkomen; RVO's eigen
"gecorrigeerd/gecontroleerd voor uitgevallen meetpunten"), maar een gat op **exact** de twee
overgangsdagen per jaar, bij alle woningen tegelijk, is geen toeval. Meest waarschijnlijke verklaring:
RVO's eigen dagconsistentiecheck (dagwaarde tegen de som van de uurwaarden) verwacht zelf een vaste
24-uursdag, faalt op de 23-/25-uursdag, en laat die dagrij dan liever weg dan hem verkeerd te
publiceren. **Praktisch gevolg voor deze preprocessing:** je hoeft dus vermoedelijk geen fout
berekende `d`-waarde op de overgangsdag te corrigeren (die komt simpelweg niet voor); wel moet
`quality.py` een ontbrekende `d`-rij op precies die datum kunnen onderscheiden van een gewoon
toevallig gat, want het eerste is een **voorspelbaar, jaarlijks terugkerend patroon** (interessant om
als aparte statistiek in `docs/data-quality.md` te laten zien) en het tweede is willekeurige
uitval. Dit is een hypothese over de oorzaak, geen bevestigd feit; bij twijfel bij RVO navragen
(kan gecombineerd met de vraag in §4.1).

**Verplichte testcases, niet "DST wordt wel meegenomen" als losse zin:** minimaal één
voorjaarsovergang en één najaarsovergang expliciet als unit test in `tests/test_intervals.py` en
`tests/test_quality.py`, met de exacte datum, het verwachte aantal kwartieren (92 resp. 100) en de
verwachte `interval_duur__s` (82.800 resp. 90.000). Niet als losse edge-case-opmerking in commentaar,
want dit raakt precies 2 van de 365 dagen per jaar en is dus makkelijk "toevallig" ongetest te
houden.

**Kanttekening: niet zomaar bestaande code overnemen.** Er bestaat elders al een
zomertijd-correcte tijdas-implementatie die hetzelfde probleem oplost, logisch om naar te kijken
voor de aanpak, maar **niet zomaar overkopiëren** als de licentie dat niet toestaat. Voor een
losstaande, mogelijk onder persoonlijke titel gepubliceerde preprocessing-repo betekent dat: zelf
een eigen (kleine) implementatie schrijven, of expliciet toestemming vragen om de aanpak/code te
hergebruiken, niet er stilzwijgend van uitgaan dat auteurschap door dezelfde persoon dat
automatisch toestaat.

## 3. Ontwerpprincipes

1. **Vier lagen, raw nooit overschrijven.** `raw` (letterlijk zoals aangeleverd) → `standardized`
   (namen/eenheden/types uniform, physiquant__unit) → `cleaned` (aantoonbaar foute waarden
   verwijderd/geflagd, niets verwijderd zonder vlag) → `derived` (afgeleide grootheden: vermogen uit
   energie/duur, e.d.). H/C/τ, COP-modellen, vakantiedetectie horen hier nog **niet** in; dat is een
   analysevraag, geen preprocessingvraag (zie §8).
2. **`physiquant__unit`-naamgeving** (`e_woning__W`, `H_transmissie__W_K_1`, zie
   [physiquant__unit](https://github.com/energietransitie/physiquant__unit)). Dat is geen
   esthetische keuze: het maakt de output van deze repo **direct joinbaar** met aansluitende
   analyseprojecten die dezelfde conventie volgen, zonder vertaallaag.
3. **Elke afgeleide kolom herleidbaar** (provenance): welke ruwe kolom(men), welke conversie, welke
   aannames, welke codeversie. Vanaf het begin, niet achteraf.
4. **Nul is een waarde, geen ontbrekende waarde**, vooral bij elektra (teruglevering,
   nul-verbruik bij vakantie) en niet automatisch imputeren.
5. **Geen harde cleaningregels zonder semantische onderbouwing per variabele.** Negatieve elektra is
   normaal (teruglevering); negatieve gas waarschijnlijk niet (te verifiëren, niet aan te nemen).
   Vermogen boven de ISDE-capaciteit is niet per definitie fout (bijverwarmingselement, tapwater,
   deellast/defrost): flaggen, niet wegfilteren.
6. **Geen data normaliseren die al genormaliseerd hoort te zijn.** Weer wordt in de brondata
   per-woning-per-uur meegeleverd, terwijl er maar 28 stations zijn; dat is denormalisatie, geen
   brongegeven. Zie §5.1.
7. **Ruwe IM3-data niet in git.** RVO's gebruiksvoorwaarden zijn geen open licentie (zie §7) en de
   dataset is met 6.283 bestanden en ~24 GB toch al te groot. `data/raw/` gitignored; de repo bevat
   het ophaal-/preprocessingscript, niet de data zelf.

## 4. Gebruiksvoorwaarden: dit is geen open data-licentie, en dat raakt de publicatiekeuze

Uit het informatiedocument (§ Gebruiksvoorwaarden, letterlijk):

> *"De dataset ... is beschikbaar voor **onderzoek en analyses met een maatschappelijk doel**.
> Gebruik van de data moet **gemeld bij KITE** (kite@rvo.nl) en de uitkomsten, resultaten en/of
> analyses moeten **onder dezelfde gebruiksvoorwaarden gedeeld worden met de KITE-community**."*

Dit is dus **geen** CC0/MIT/open-data-vrijbrief. Drie dingen die dat raakt voor dit project, en die
niet door mij te beslissen zijn:

1. **Deze preprocessing-repo telt vermoedelijk als "analyse"** in de zin van de voorwaarden: een
   herbruikbare, gepubliceerde preprocessingpijplijn is precies het soort resultaat dat de
   voorwaarden lijken te bedoelen met "delen met de KITE-community". Onduidelijk is of dat betekent:
   (a) alleen de *resultaten* van een analyse delen, of (b) ook code die zelf geen analyse-uitkomst
   bevat maar wel op de data draait. **Overleg met RVO/KITE gevoerd op 01-09-2026.** Uitkomst:
   bevindingen uit deze preprocessing worden alvast gedeeld met RVO/KITE, dat leestoegang tot deze
   repo heeft gekregen. Wat "delen met de KITE-community" precies betekent voor de code zelf is
   daarmee nog niet uitgesproken. **De repo blijft niet-publiek zolang Kenniscentrum Duurzaam Leven intern op de
   licentie studeert**, zie `LICENSE`. *Beantwoord: besloten 19-10-2026: EUPL-1.2, onder de naam
   Kenniscentrum Duurzaam Leven. Openbaar maken is een aparte stap.*
2. **Melden bij KITE is sowieso verplicht**, los van wat er gepubliceerd wordt, zodra deze
   preprocessing daadwerkelijk tegen de dataset draait.
3. **Publicatie onder een persoonlijke titel** (zoals overwogen) is qua *code* waarschijnlijk geen
   probleem (de preprocessingcode zelf bevat geen IM3-data), maar de repository moet dan wel
   glashelder maken dat de dataset zelf niet vrij herbruikbaar is en onder welke voorwaarden ze wél
   te verkrijgen is (verwijzing naar KITE, geen doorlink naar een kopie).

Voorstel: een `GEBRUIKSVOORWAARDEN.md` in deze repo die dit letterlijk citeert (met bronvermelding
en datum van het informatiedocument, want dat kan wijzigen) plus een link naar
`kennisdelen.rvo.nl/kite`, vóór er ook maar één regel preprocessingcode gepubliceerd wordt.

## 5. Voorgesteld datamodel

```
homes.parquet          : één rij per woning (metadata; de 18 kenmerken uit 00_IM_meta_data)
measurements.parquet   : home_id, tijdstip, interval_type__cat, interval_duur__s, e_net__kWh, g_gebruik__m3
weer.parquet           : weerstation_nr, tijdstip (uur), temp_buiten__degC, wind__m_s_1, ghi__kWh_m_2, bron__cat
quality.parquet        : home_id, tijdstip, <veld>__flag  (zie §5.2)
derived.parquet        : home_id, tijdstip, e_net__W, g_gebruik__W, weerkoppeling_methode__cat (zie §2.3)
```

Kolomvoorstel `measurements` (physiquant__unit; Nederlandstalig):

| ruwe kolom (IM3) | nieuwe kolom | opmerking |
|---|---|---|
| `Customer_id` (bestandsnaam) | `home_id__str` | ongewijzigd overnemen, dit ís al het anonieme sleutel |
| `datetime` | `tijdstip` (UTC, tz-aware) | RVO levert al UTC |
| `interval` | `interval_type__cat` | `q`/`h`/`d`/`m`, **behouden**, niet meteen omzetten |
| (afgeleid) | `interval_duur__s` | 900/3600/86400/variabel (28–31 dagen bij `m`) |
| `elec` | `e_net__kWh` | verschilstand, negatief = teruglevering; **geen** `_cum` |
| `gas` | `g_gebruik__m3` | verschilstand; niet-negatief-aanname nog te verifiëren |

`homes`: analoge vertaling van de 18 metadata-kolommen. Let op drie categorieën die per ontwerp
**geen** enkelvoudige categorie zijn maar een vrije multi-select, komma-gescheiden in één veld
(`Verwarmingssysteem`: 200 unieke combinaties in de steekproef, `Afgiftesysteem`: 82), en die horen
**niet** naar één binaire kolom te worden platgeslagen. Voorstel: bewaar het ruwe multi-select-veld
as-is (`verwarmingssysteem_ruw__cat`) én splits naar losse boolean-indicatoren
(`heeft_hybride_wp__bool`, `heeft_all_electric_wp__bool`, `heeft_hr_ketel__bool`, `heeft_pvt__bool`, …) op basis
van een expliciete, gedocumenteerde tag-lijst: dat is standaardisatie, geen analysebeslissing, dus
hoort hier wel thuis (in tegenstelling tot bijvoorbeeld het indelen in "warmtepomptype-groepen" voor
een specifieke analyse).

### 5.1 Weer hoort niet in `measurements`: het is per-woning gedenormaliseerd brongegeven

**Geverifieerd:** twee willekeurige woningen op hetzelfde weerstation (station 240, 614 woningen)
hebben over 9.191 gemeenschappelijke uren **exact dezelfde** `temp`-waarde: 0 verschillen. Dat is
verwacht (het is hetzelfde KNMI-station) maar bevestigt dat de brondata het weer **per woning
dupliceert** terwijl er maar 28 stations voor alle 6.283 woningen zijn. Dat hoort niet in
`measurements.parquet` als per-woning-kolom; het hoort in een eigen `weer.parquet`, genormaliseerd
op `(weerstation_nr, tijdstip)`, met `homes.weerstation_nr` als foreign key. Dat is puur een
datamodel-keuze (geen cleaning, geen aanname) en scheelt op zichzelf al fors in opslag; zie §6 voor
de cijfers.

Dit maakt meteen ruimte voor een **tweede bron in dezelfde tabel** (kolom `bron__cat`): naast de
IM3-geleverde reeks (`bron="im3"`, alleen aanwezig vanaf de eerste `h`-rij per woning) een **zelf
opgehaalde, reproduceerbare** KNMI-reeks (`bron="eigen_ingest"`, terug te laten lopen tot de
vroegste `m`-rij per woning, zie §2.3); zie ook §7.3. `weer.parquet` blijft zelf altijd op uurresolutie;
hoe een `q`/`h`/`d`/`m`-meetrij eraan gekoppeld wordt (punt, interpolatie of aggregatie) staat niet
hier maar als `weerkoppeling_methode__cat` op de gekoppelde tabel, zie §2.3.

## 6. Compactheid na preprocessing (mechanisch, niet inhoudelijk)

Concrete vraag: hoeveel compacter wordt de dataset door **alleen** structurele/mechanische
preprocessing (typering, compressie, het weer normaliseren zoals in §5.1), dus vóór er ook maar één
cleaning-regel, quality-flag of afgeleide grootheid bij komt? Gemeten op een steekproef van 15
willekeurige woningen (1.388.237 rijen), geschaald naar de volledige dataset (~23,9 GB):

| variant | omvang (geschat, volledige dataset) | t.o.v. ruwe CSV |
|---|---|---|
| **ruwe CSV** (zoals aangeleverd) | 23,9 GB | 1× |
| **zip** (zoals gedownload) | 3,2 GB | 7,5× |
| **getypeerd Parquet, alle kolommen/rijen** (alleen float64→float32, categorieën, snappy-compressie, géén weer-dedup) | ~3,2 GB | 7,4× |
| **+ weer genormaliseerd naar `weer.parquet`** (§5.1) i.p.v. per woning gedupliceerd | ~2,7 GB (measurements) + **~5-15 MB** (weer.parquet, 28 stations × ~4 jaar uurdata) | ~8,7× |

Twee dingen die opvallen:

- **Getypeerd Parquet alleen (zonder weer-dedup) wint niet meer dan de zip al deed** (7,4× om 7,5×).
  Dat komt doordat de CSV's vooral floating-point-ruis bevatten (`26.721999999999753` in plaats van `26.72`) die
  zip's generieke compressie al grotendeels wegcomprimeert. De **echte** winst zit 'm dus niet in
  het bestandsformaat op zich, maar in...
- **...het weer normaliseren.** Dat is de enige stap hierboven die significant meer wint dan generieke
  compressie kán winnen, want het is geen compressie maar het **weghalen van 224× gedupliceerde
  data** (6.283 woningen / 28 stations), precies het soort winst die een zip-algoritme per bestand
  niet kan zien omdat elk `IM_customer_*.csv`-bestand apart wordt gecomprimeerd.

**Niet meegenomen in bovenstaande tabel, bewust:** het (gedeeltelijk) laten vervallen van
overlappende `d`/`m`-rijen waar `q`/`h` dezelfde periode al dekken. Dat scheelt in een ruwe test nog
eens ~4% (rijen zijn maar 0,9% van het totaal, maar relatief zwaar door de aparte
`interval_type`-categorie-overhead), maar vereist per-periode logica (welke `d`/`m`-rij wordt al
gedekt door `q`/`h`-rijen in dezelfde periode, zie §2.1; je mag nooit blind alle `d`/`m`-rijen
droppen, want dat is voor de vroege periode de **enige** bron) en is daarmee eigenlijk al
inhoudelijke preprocessing, geen mechanische stap. Hier dus bewust buiten deze schatting gehouden.

**Conclusie:** van ~24 GB ruwe CSV naar ~2,7 GB aan echt bruikbare, getypeerde, herleidbare Parquet
door uitsluitend structurele stappen (typering + weer-normalisatie): een factor **~9**, vóór er één
regel cleaning bij komt.

## 7. Concrete controles die deze steekproef al bruikbaar maakt

Naast de generieke checklist (stuck sensors, extreme waarden, dubbele records; zie de
oorspronkelijke AI-analyse voor een volledige lijst) zijn er controles die dankzij de structuur van
déze dataset zonder aanvullende bronnen te doen zijn, en die als eerste zouden moeten draaien omdat
ze de rest van de preprocessing valideren:

### 7.1 `q`-som versus `h`/`d`-waarde, per dag

Voorbeeld klant 1000, 1 maart 2023: Σ kwartier = 18,129 kWh, dagwaarde = 18,746 kWh, een verschil
van 3,4%. Dat is klein genoeg om als afrondings-/randeffect te zien, maar groot genoeg om dit als
structurele controle in te bouwen (`e_dagcheck__kWh = e_dag__kWh − Σe_kwartier__kWh`) en per woning
te rapporteren; grote afwijkingen wijzen op ontbrekende kwartieren of een tijdzoneprobleem.

### 7.2 IM3-geleverde weer versus onafhankelijk opgehaalde weer

Dit hoeft geen nieuwe bron: `Weerstation_nr` in de metadata is al een KNMI-stationscode, en
Een onafhankelijke KNMI-uurdata-ophaal is dus al mogelijk zonder nieuwe bron. Voor eenzelfde
station en tijdstip zou `temp_buiten__degC` uit IM3 nagenoeg gelijk moeten zijn aan wat zo'n
onafhankelijke ophaal oplevert. Dit is de **goedkoopste** controle van de hele preprocessing: geen
IM3-specifieke logica nodig, alleen een join op stationcode+tijdstip. Zie §7.3 voor het vervolg
hierop: bij een geslaagde check kan deze controle direct de basis worden van een volledige
vervanging van de IM3-weerreeks.

### 7.3 Weer zelf opnieuw ophalen i.p.v. de meegeleverde reeks overnemen

**Het idee, en waarom het de moeite waard is:** de meegeleverde `temp`/`wind`/`sun` in IM3 zijn een
**black box**: RVO's document zegt alleen "dichtstbijzijnde KNMI-station", niet welke
interpolatiemethode, welk KNMI-product (uurwaarnemingen? een ander afgeleid product?), of hoe
`sun`/`ghi__kWh_m_2` precies is gedefinieerd. `needforheat-dutch-weather-software` (Apache 2.0)
doet dit al **reproduceerbaar en gedocumenteerd**:
geospatiale + temporele interpolatie van KNMI-uurdata, met een vaste, citeerbare methode. Zelf
dezelfde weer opnieuw ophalen i.p.v. de IM3-kopie te vertrouwen levert dus een reeks op die je over
vijf jaar nog kunt reproduceren en verantwoorden; de IM3-kopie kun je alleen navertellen.

**Praktisch: geen nieuwe implementatie, hergebruik.** Er is een kant-en-klare library:
`pip install git+https://github.com/energietransitie/needforheat-dutch-weather-software.git`
(Apache 2.0, door @henriterhofte en bijdragers, dus met een schoon attributiepad). Voor deze
preprocessing-repo: die library als dependency opnemen (met bronvermelding in
`docs/data-description.md` en de `README.md`), niet de KNMI-download zelf herimplementeren. Één
kanttekening: `needforheat-dutch-weather-software` interpoleert naar een **GPS-locatie**; IM3 geeft
alleen het **dichtstbijzijnde station** (geen coördinaat van de woning zelf). Voor een eerlijke
vergelijking dus interpoleren naar de **coördinaat van hetzelfde KNMI-station** (niet naar een
GPS-punt), zodat je exact hetzelfde vergelijkt als wat IM3 zegt te doen; pas als een latere stap
zou de eigen ingest naar de werkelijke woninglocatie kunnen interpoleren (fijnmaziger dan IM3, maar
dan is het geen appels-met-appels-vergelijking meer met de meegeleverde reeks).

**Volgorde, niet-omkeerbaar:**

1. **Eerst** de consistentiecheck uit §7.2 uitvoeren, per station, over een representatieve
   steekproef in de tijd (niet één dag).
2. **Bij een goede match** (te definiëren: bijv. mediane absolute afwijking < 0,5 °C voor
   temperatuur, vast te leggen vóór de check draait en niet achteraf gekozen): `weer.parquet` vullen
   met `bron="eigen_ingest"` als primaire reeks voor alle verdere derived/analysewerk, en de
   IM3-geleverde reeks **behouden** als `bron="im3"` in dezelfde tabel, nooit overschrijven (§3.1).
   Dat is ook meteen de vervanging waar de vraag naar compactheid (§6) baat bij heeft: één
   gedeelde, herberekenbare reeks in plaats van 6.283 kopieën van een ondoorzichtige bron.
3. **Bij een slechte match:** niet corrigeren of kiezen welke "juist" is vóór is uitgezocht wát het
   verschil verklaart (ander station, ander KNMI-product, interpolatiemethode, tijdzone-offset). Dat
   is zelf een bevinding voor `docs/data-quality.md`, geen cleaning-beslissing.
4. **Daarna pas de eigen ingest terugtrekken tot de vroegste `m`-rij per woning** (§2.3): de check
   in stap 1 kan alleen over de `h`-periode lopen (IM3 levert daarbuiten geen weer om tegen te
   toetsen), dus het stuk vóór de eerste `h`-rij steunt volledig op vertrouwen in de eigen ingest,
   niet op een eigen consistentiecheck. Vermeld dat verschil expliciet in
   `docs/data-quality.md` (welk deel van `weer.parquet` wél en welk deel niet tegen IM3 gevalideerd
   kon worden) in plaats van het stilzwijgend gelijk te behandelen.
5. **Bij het koppelen aan `d`/`m`-rijen: het lokale-dagvenster gebruiken, niet een vaste 24 uur**
   (§2.4); anders krijgt `gemiddelde_dag` op de twee jaarlijkse overgangsdagen een verkeerd aantal
   brondatapunten mee.

**`ghi`/zoninstraling verdient een aparte, kritischer blik** dan temperatuur/wind: RVO's
documentatie zegt alleen "gesommeerde zoninstraling, kWh/m²" zonder brontype. KNMI's eigen
uurproduct voor globale straling heeft een specifieke definitie (`Q` in J/cm² per uur, om te
rekenen naar kWh/m²), vóór IM3's `sun`-kolom te vervangen door een zelf berekende `ghi__W_m_2`,
eerst expliciet vaststellen dat `needforheat-dutch-weather-software` hetzelfde brongrootheid
gebruikt, anders vergelijk je twee verschillende dingen die toevallig beide "zoninstraling" heten.
Zie §12.19: `sun` blijkt KNMI's `Q` als uursom in kWh/m² te zijn, en werd tot die fix zonder
omrekening als W/m² vergeleken.

## 8. Wat hier bewust niet gebeurt

- Geen H/C/τ-schatting, geen COP-model, geen warmtepomp-disaggregatie uit het totale
  elektrasignaal. Dat is fysische modellering, geen preprocessing, en hoort thuis in
  een aparte analysemodule met een warmtepompmodel.
- Geen representativiteitsanalyse (IM3 vs. CBS/WoON/BAG): nuttig, maar een analysestap op de
  *output* van deze preprocessing, niet een preprocessingstap zelf.
  Ook dat hoort in een aansluitend analyseproject, waar de vraag "voor welke uitspraken is dit
  anker representatief" thuishoort.
- Geen vakantie-/thuisdagdetectie, geen bins voor analysevariabelen.

## 9. Repo-structuur (licht, geen volledige scaffold; dat is aan de implementatie)

```
installatiemonitor-dataset-preprocessing/
├── README.md
├── GEBRUIKSVOORWAARDEN.md      # letterlijke KITE-voorwaarden + overlegstatus (§4)
├── LICENSE                     # licentie van de CODE, apart van de dataset-voorwaarden
├── ontwerp-preprocessing.md    # dit document
├── docs/
│   ├── data-description.md     # RVO-datadictionary + de twee geverifieerde afwijkingen (§2)
│   ├── data-quality.md         # per-veld rapport, gegenereerd, niet handmatig bijgehouden
│   └── variable-dictionary.md  # ruw → standardized mapping (§5)
├── src/im3_preprocessing/
│   ├── bron.py                 # ruwe data uit de zip streamen of uit een map lezen (§12.11)
│   ├── io.py                   # per-bestand inlezen, schema-validatie
│   ├── timestamps.py           # de q/h vs d/m ankerregel-asymmetrie (§1) + lokale-dagvenster-
│   │                            #   berekening voor d/m, zomertijd-aware (§2.4)
│   ├── intervals.py            # interval_duur__s afleiden, NIET hardcoded 86400 voor `d` (§2.4)
│   ├── weer.py                 # weer.parquet opbouwen: IM3-kolommen + eigen ingest via
│   │                            #   needforheat-dutch-weather-software (§7.3), consistentiecheck (§7.2)
│   ├── cleaning.py             # flags produceren, §5.2
│   └── quality.py              # q-vs-d/h-consistency (§7.1), stuck-sensor-detectie
├── data/
│   ├── raw/                    # NIET committen; alleen dataset_openbaar.zip, niet uitgepakt (§12.11)
│   ├── interim/                # alleen caches (o.a. het tijdbereik per woning, §12.11)
│   └── processed/               # homes.parquet, measurements.parquet, weer.parquet, quality.parquet, derived.parquet
└── tests/
```

`data/raw/` bevat alleen `dataset_openbaar.zip` zoals gedownload; uitpakken gebeurt sinds
26-aug-2026 tijdens de run, in geheugen (§12.11). `data/raw/`, `data/interim/` en `data/processed/`
staan vanaf commit 1 in `.gitignore`, niet achteraf toegevoegd.

## 10. Openstaande vragen (aan jou, niet aan de implementatie)

1. Wat "delen met de KITE-community" precies inhoudt voor een preprocessing-repo (§4.1). Het
   overleg met RVO/KITE van 01-09-2026 heeft dat niet uitgesproken; wel is afgesproken dat
   bevindingen gedeeld worden, en RVO/KITE heeft leestoegang tot deze repo. Of de repo publiek kan
   hangt nu op het interne licentiebesluit van Kenniscentrum Duurzaam Leven (punt 2), niet meer op een
   uitstaande vraag aan RVO/KITE. *Beantwoord via punt 2: het licentiebesluit is genomen; openbaar
   maken is een aparte stap.*
2. Onder welke licentie de **code** (niet de data) van deze repo verschijnt, en onder welke naam
   (persoonlijk vs. Kenniscentrum Duurzaam Leven), onafhankelijk van punt 1, maar wel met punt 1 als
   randvoorwaarde. *Beantwoord: besloten 19-10-2026: EUPL-1.2, onder de naam Kenniscentrum Duurzaam
   Leven.*
3. Of gas werkelijk nooit negatief is (RVO's documentatie zegt niets expliciets hierover, alleen dat
   elektra dat wél kan zijn): vóór dit als cleaning-regel vast te leggen, over de hele dataset
   verifiëren, niet aannemen.
4. Welke matchdrempel voor de weer-consistentiecheck (§7.3, stap 2) acceptabel is, vooraf vast te
   leggen, niet achteraf gekozen op basis van de uitkomst.
5. Of RVO/KITE/BDH's prepublicatiepijplijn meterwissels/-resets filtert vóór het
   verschillen/aggregeren naar de gepubliceerde kwartier-/uur-/dag-/maandwaarden (§12.6): de
   hypothese en de aanbeveling (met een concrete, citeerbare implementatie uit
   `needforheat-diagnosis-software`) horen meegenomen te worden in een volgend inhoudelijk overleg
   met RVO/KITE (op 01-09-2026 nog niet aan de orde geweest), niet als losse technische bug-report
   gestuurd te worden.
6. Of RVO/KITE/BDH bevestigen dat gas op exact `0` vóór daadwerkelijke koppeling/meting eigenlijk
   `NaN` had moeten zijn (§12.7), net als punt 5 hierboven mee te nemen in dat inhoudelijke
   overleg met RVO/KITE, niet zelf als aanname in deze preprocessing te verwerken.
7. Of RVO/KITE bevestigen dat **alle** woningen in de dataset in Europees Nederland staan, zodat
   `Europe/Amsterdam` als lokale tijdzone klopt (§12.10). De dataset zelf en de ISDE-voorwaarden
   wijzen daar allebei op, maar RVO's documentatie bevestigt het niet met zoveel woorden; een
   korte bevestiging bij datzelfde overleg maakt van een goed onderbouwde aanname een vaststaand
   gegeven.
8. Of het kwaliteitsrapport zelf moet waarschuwen wanneer een "geen data"-categorie een
   onwaarschijnlijk groot aandeel krijgt (§12.14). `ontbrekend_buiten_archief` op 99,1% terwijl er
   wel degelijk een weerreeks was opgehaald, had een alarm moeten zijn in plaats van een regel in
   een tabel. Dit is een ontwerpkeuze voor de rapportage, geen datavraag aan RVO/KITE.

## 11. Eerste concrete stappen, in volgorde

1. `GEBRUIKSVOORWAARDEN.md` + navraag bij KITE (§4), vóór er iets gepubliceerd wordt, niet erna.
2. `data/raw/` + `.gitignore`, git-repo initialiseren.
3. `io.py` + schema-validatie op alle 6.283 bestanden (bevestigt dat het patroon uit §1/§2 overal
   geldt, niet alleen in de steekproef van 25).
4. `weer.py`: eerst de consistentiecheck (§7.2), pas daarna (bij een goede match) de eigen ingest
   als primaire bron in `weer.parquet` (§7.3). Kleinste, snelste, meest overtuigende eerste
   resultaat, en direct ook de grootste compactheidswinst (§6).
5. `timestamps.py` + `intervals.py`, met de q-vs-d/h-consistency-check uit §7.1 **en** de twee
   zomertijd-testcases uit §2.4 (één voorjaars-, één najaarsovergang, met het verwachte aantal
   kwartieren en de verwachte `interval_duur__s`) als ingebouwde tests, niet later toevoegen.
6. Pas daarna cleaning/flags en de overige parquet-output.

## 12. Aanvullende bevinding tijdens implementatie (26-aug-2026)

Tijdens het bouwen van `src/im3_preprocessing/io.py` bleek een vijfde structurele eigenschap die
niet in de steekproef van 25 bestanden (§1) naar boven kwam, maar wel bij de eerste run over een
grotere steekproef:

### 12.1 707 van de 6.283 woningen (11,3%) hebben géén `gas`-kolom in de bron

Niet elk `IM_customer_<id>.csv`-bestand heeft de kolommen `datetime,elec,interval,gas,wind,temp,sun`:
bij een all-electric woning (geen gasaansluiting) ontbreekt de `gas`-kolom volledig, in plaats
van aanwezig te zijn met louter `NaN`- of `0`-waarden. Geverifieerd over de **volle dataset** (niet
een steekproef) door alleen de headerregel van alle 6.283 bestanden te lezen: 707 bestanden missen
`gas` in de header, o.a. `IM_customer_1011` (`Verwarmingssysteem = "All-electric warmtepomp,
Warmtepompboiler"`, `Koken_op_gas = 0` in de metadata, consistent met "geen gasaansluiting").

**Consequentie voor deze preprocessing:** dit is geen schemadefect en geen ontbrekende meting:
het is een woning zonder de betreffende aansluiting. `io.read_customer_stream` behandelt `gas` daarom
als optionele kolom: ontbreekt hij, dan wordt hij aangevuld met `NaN` (nooit met `0`, want dat zou
principe 4 schenden, want `0 gebruikt` en `geen aansluiting` zijn niet dezelfde uitspraak) plus een
informationele issue, geen `SchemaError`. Voor `quality.parquet` betekent dit dat
`g_gebruik_ontbrekend__flag` voor deze 707 woningen structureel 100% zal zijn, en dat is correct
gedrag, geen datakwaliteitsprobleem, en hoort als zodanig toegelicht te worden in
`docs/data-quality.md`, niet als een aparte "slechte woning" te worden gerapporteerd.

### 12.2 Dtype-beleid: `__bool` i.p.v. `__0` voor booleans, en zuinige pandas/Parquet-types

Op verzoek (26-aug-2026) is de naamgeving en de dtype-toewijzing aangescherpt, ná te hebben
gekeken hoe `needforheat-diagnosis-software` dit zelf doet (`property_types`-tabel in
`REDUCEDHEATCARB_sanity_check.ipynb`):

- **`__bool` voor echte booleans, `__0` blijft gereserveerd voor een dimensieloos getal** (een
  telling, ratio of COP is ook `__0` in de physiquant__unit-conventie, maar geen boolean); alle
  `heeft_<x>__0`-namen zijn hernoemd naar `heeft_<x>__bool`.
- **Kleinste passende integer-breedte, geverifieerd tegen de volle dataset**: `int8` voor de
  ingestelde temperaturen, `int16` voor `weerstation_nr`, `int32` voor `interval_duur__s`,
  nullable `Int8` voor `isde_vermogen__kW` (moet `-1`-sentinel én ontbrekende waarden als NaN
  kunnen dragen).
- **`float32` in plaats van `float64`** voor alle continue meetwaarden, zelfde keuze als
  `needforheat-diagnosis-software` zelf al maakt. float ondersteunt NaN
  al native, dus geen nullable extensietype nodig voor `g_gebruik__m3` (§12.1).
- **`category` voor laag-cardinale, herhaalde strings** (`interval_type__cat`, `bron__cat`,
  `weerkoppeling_methode__cat`, de categorische `homes`-velden), bewust **niet** voor
  `home_id__str` (join-sleutel, Parquet comprimeert herhaalde strings toch al met dictionary-
  encoding).

Volledige rationale en tabel per kolom: `docs/variable-dictionary.md` (§"Dtype-beleid").

### 12.3 Werkelijke calorische gaswaarde i.p.v. een vaste constante

`derived.g_gebruik__W` gebruikte een vaste Groningen-gas-constante (35,17 MJ/m³). Op verzoek is
dit vervangen door een automatische ingest van de **daadwerkelijke**, per-uur gepubliceerde
calorische waarde, geïnspireerd op
`needforheat-diagnosis-software/examples/RHC_gas_quality.ipynb`, maar met een automatische
API-aanroep i.p.v. de handmatige CSV-downloads die dat notebook noodgedwongen gebruikte. De
bron (`mijnenergiedata.nl/calorische-gaswaarden`) is een **niet publiek gedocumenteerde** API,
ontdekt door de website's eigen JS-bundel te inspecteren, en kan zonder aankondiging wijzigen. IM3
levert geen netbeheerder/netgebied per woning, dus dit is een NL-gemiddelde over alle netgebieden
per uur, geen exacte per-woning-waarde. De vaste constante blijft bestaan als terugvaloptie voor
rijen buiten het opgehaalde venster (`gas_hhv_bron__cat`). Zie `src/im3_preprocessing/gaskwaliteit.py`.

### 12.4 Weer-consistentiecheck: interpolatiestap isoleren van andere oorzaken

De consistentiecheck (§7.2/§7.3) liet twee stations (210, 240) buiten de matchdrempel vallen. Op
verzoek (26-aug-2026) is uitgezocht of dat aan de RBF-geospatiale-interpolatiestap zelf ligt:
naast de geïnterpoleerde eigen ingest (`bron="eigen_ingest"`) haalt `weer.py` nu ook de rauwe,
niet-geïnterpoleerde waarde van het dichtstbijzijnde station rechtstreeks op
(`bron="eigen_ingest_direct"`, hergebruikt bewust alleen
`dutch_weather.knmi.fetch_hourly_dutch_weather_data`, niet `geo_interpolate_weather_data`). Op de
steekproef van 25 woningen bleek de "direct"-variant nagenoeg dezelfde afwijking te geven als de
geïnterpoleerde variant: de interpolatiestap lijkt dus **niet** de (enige) oorzaak; iets anders
(stationskeuze, KNMI-product, tijdzone) is waarschijnlijker. Zie `docs/data-quality.md` voor de
concrete cijfers van de laatste run.

Deze bevinding heeft later een tweede, zwaardere consequentie gekregen dan alleen "de oorzaak ligt
elders": als interpoleren en niet-interpoleren hetzelfde antwoord geven, is de dure interpolatiestap
in het standaardpad overbodig. Zie §12.13.

### 12.5 "Stuck sensor"-heuristiek herzien: van lokale runs naar hele-reeks-variantie

De oorspronkelijke stuck-sensor-vlag (>= 8 opeenvolgende identieke waarden, met exacte nullen
uitgesloten) bleek op nader inzien (feedback 26-aug-2026) niet houdbaar: een tijdelijke reeks
identieke, ook niet-nul, waarden is op zichzelf geen bewijs van een kapotte sensor. Bijvoorbeeld
een warmtepomp die een tijd op een vast minimum-modulatieniveau draait geeft een reëel, tijdelijk
constant vermogen. Vervangen door de aanpak die `needforheat-diagnosis-software` zelf gebruikt
(`Preprocessor.filter_id_prop_with_std_zero`): vlag een (woning, interval_type)-reeks alleen als
hij over de **hele** looptijd nooit varieert (std==0), een veel zeldzamer en sterker signaal.
Als flag, niet als verwijdering (ontwerp §3 principe 3, anders dan het origineel in
needforheat-diagnosis-software). Daarnaast toegevoegd: een z-score-uitschieterdetectie
(`Preprocessor.filter_static_outliers`, voorlopige drempel 3σ), als aanvullende, wél
beproefde sanity-check. Zie `quality.constante_reeks_flags` / `quality.uitschieter_flags`.

### 12.6 Hypothese: meterwissel + ontbrekend filter in de prepublicatiefase

De nieuwe z-score-uitschieterdetectie (§12.5) legde op de steekproef van 25 woningen twee
extreme `m`-rijen bloot die de moeite van uitpluizen waard waren:

- `IM_customer_1018`, `m`-rij mei 2023: `elec = -2117,47` (gemiddeld daggebruik), een factor
  ~70 groter dan enige andere maand van deze woning (bereik ruwweg -3 .. +48). **Tegelijkertijd**
  `gas = -740,68`, ook een factor ~300 buiten bereik. De `d`-rijen binnen mei 2023 zelf zien er
  wél normaal uit (dagwaarden tussen -12 en +65), met een rapportagegat van 18 t/m 24 mei; de
  anomalie zit dus specifiek in RVO's eigen maandaggregatie, niet zichtbaar in de losse dagwaarden.
- `IM_customer_1027`, `m`-rij oktober 2023: `elec = -227,32`, direct na een rapportagegat van
  april t/m september 2023 (geen enkele `m`-rij in die periode) en gevolgd door de eerste keer dat
  `gas` niet meer structureel 0 is (consistent met een aanmeld-/installatiemoment rond die datum).

**Hypothese** (nog niet bevestigd door RVO/KITE): dit patroon (een extreme, geïsoleerde
negatieve waarde in precies één periode, bij één woning, soms gelijktijdig in zowel elektra als
gas) past bij een meterwissel (in Nederland vaak elektra én gas in één huisbezoek) waarbij de
knik tussen de oude en de nieuwe cumulatieve meterstand niet is opgevangen vóórdat RVO's eigen
pijplijn de gepubliceerde verschilwaarden berekent.

**Hoe `needforheat-diagnosis-software` dit deel** (`data/preprocessor.py`,
`Preprocessor.property_filter`, argument `process_meter_reading=True`): die functie werkt op de
**cumulatieve** meterstand zelf (niet op een al-verschilde reeks), in twee stappen:

1. `df['diff'] = df[prop].diff(); df = df[df['diff'] >= 0]`: verwijder rijen waar de cumulatieve
   stand *daalt* t.o.v. de vorige rij (een enkele corrupte/nulmeting).
2. Daarna, expliciet voor meterwissels: neem het verschil opnieuw, zet elk **negatief** verschil
   op `0` (`df.loc[df[prop] < 0, prop] = 0`), cumuleer de reeks opnieuw op (`cumsum()`), en
   differentieer dan pas een laatste keer om het uiteindelijke gebruikstempo te krijgen. Een
   cumulatieve meterstand kan nooit dalen bij normaal gebruik, en een negatief verschil is dus per
   definitie een meterwissel/-reset, nooit teruglevering (dat wordt in hun datamodel apart
   bijgehouden als losse teruglevering-kolom, niet als negatieve `e_use`).
3. Pas **daarna** volgt `filter_static_outliers` (de z-score-check, §12.5), bij hen dus een extra
   vangnet, niet de eerste verdedigingslijn.

**Waarom deze preprocessing dat zelf niet kan repareren:** IM3 publiceert uitsluitend de
al-verschilde reeks (`elec`/`gas`), niet de onderliggende cumulatieve meterstanden. De correctie
die needforheat-diagnosis-software toepast (stap 1-2 hierboven) is dus alleen mogelijk **vóór**
publicatie, in RVO/KITE/BDH's eigen pijplijn. Deze preprocessing kan het symptoom alleen
signaleren (`e_net_uitschieter__flag`/`g_gebruik_uitschieter__flag`, evt. met
`beide_uitschieter__bool` als extra aanwijzing bij gelijktijdige elektra+gas-uitschieters, zie
`quality.extreme_uitschieters_rapport`), niet de oorzaak zelf wegnemen; een cleaning-correctie
zou hier gokken naar de werkelijke cumulatieve meterstand, wat ontwerp §3 principe 5 uitsluit.

**Aanbeveling voor RVO/KITE/BDH (mee te nemen in een volgend overleg, §4/§10.1):** vóór het
verschillen/aggregeren naar kwartier-/uur-/dag-/maandwaarden, controleer of de onderliggende
cumulatieve meterstand ooit *daalt* tussen twee opeenvolgende aflezingen (elektra én gas apart).
dat kan alleen bij een meterwissel/-reset. Zet dat specifieke interval op 0 (of vlag het
expliciet) in plaats van het als een geldig, extreem negatief verbruik te publiceren. Dat
`needforheat-diagnosis-software`'s `Preprocessor.property_filter` hiervoor al een werkende,
citeerbare implementatie heeft (Apache 2.0) maakt dit een concrete, overdraagbare aanbeveling,
geen abstracte suggestie.

### 12.7 Gas op exact 0 vóór koppeling: waarschijnlijk "nog niet gemeten", geen genuine nul

**Dit is een ANDER punt dan §2.3/§12.6, niet te verwarren mee.** Dat `d`/`m`-rijen verder
teruggaan dan `h`/`q` is zelf verwacht, gedocumenteerd gedrag (§2.3): een ODA kan via de
netbeheerder historische dagstanden opvragen (P4-portaal), en netbeheerders houden die
historische dagstanden zelf al bij, onafhankelijk van of er al een lokale P1-uitlezer
(kwartier-/uurdata) aangesloten is. Zie [dsmr-info](https://github.com/energietransitie/dsmr-info)
voor de achtergrond van het DSMR/P1-ecosysteem (webonderzoek 26-aug-2026, o.a. bevestigd dat het
lokale P1-poort-signaal zelf geen historie bewaart, maar dat ODA's via de netbeheerder wél
historische dagstanden kunnen opvragen, periodiek beperkt tot 6× per jaar zonder expliciete
toestemming van de aansluithouder voor vaker). Dat verbruik vóór het live-monitoring-moment
alsnog uit dag-/maandstanden gevuld wordt, is dus op zichzelf niet verkeerd.

**Dit punt gaat specifiek over de waarde 0 die daarbij voor gas verschijnt waar dat niet
aannemelijk is.** Geverifieerd op de steekproef van 25 woningen (`quality.gas_voor_koppeling_verdacht_rapport`,
venster van 60 dagen): `IM_customer_1027` (`Koken_op_gas=True`, verwarmingssysteem "Hybride
warmtepomp, HR-ketel", dus zowel een gasfornuis als een gasgestookte cv-ketel) heeft de eerste 60
dagen met een `d`-gasrij stuk voor stuk **exact 0**, om daarna over te gaan op een reeks met
normale variatie (~39% nul-dagen, plausibel voor een hybride warmtepomp die zelden de ketel
nodig heeft, maar wel op gas gekookt wordt). Permanent nul gasverbruik gedurende twee maanden is
voor een huishouden dat op gas kookt niet aannemelijk. **Belangrijk detail:** dit huishouden had
al wél `h`-data (elektra, weer) vanaf maart 2023; de gas-nul-periode is dus geen algemeen "nog
niet aangemeld"-verschijnsel, maar specifiek een gas-eigen koppeling die kennelijk later volgde
dan de elektra-koppeling.

Ter contrast: `IM_customer_1001` (`Koken_op_gas=False`, "All-electric warmtepomp") staat de
**hele** reeks op exact 0, niet alleen de eerste periode, en dat is zelf-consistent (een woning
zonder relevant gasgebruik) en wordt door `gas_voor_koppeling_verdacht_rapport` terecht niet als
verdacht gemarkeerd. Zulke woningen zijn ook niet hetzelfde als de 707 woningen uit §12.1: die
missen de `gas`-kolom helemaal; deze hebben een letterlijk aanwezige kolom vol nullen.

**Hypothese** (nog niet bevestigd door RVO/KITE, gebaseerd op één duidelijk voorbeeld in een
steekproef van 25): waar gas nog niet daadwerkelijk gekoppeld/gemeten is, schrijft RVO/KITE's
prepublicatiepijplijn `0` weg in plaats van `NaN`: hetzelfde soort fout (nul en "niet gemeten"
verward, ontwerp §3 principe 4) als bij de 707 woningen zonder gaskolom (§12.1), maar dan
subtieler: de kolom is aanwezig, dus minder makkelijk op te merken dan een hele ontbrekende
kolom.

**Wat deze preprocessing hier wél en niet doet:** `gas_voor_koppeling_verdacht_rapport` signaleert
en rapporteert dit patroon (per woning: eerste N dagen altijd 0 + verwacht gasgebruik volgens de
metadata), maar zet de waarden zelf niet om naar NaN; dat zou zonder externe bevestiging een
aanname zijn die ontwerp §3 principe 5 uitsluit. Net als §12.6 hoort dit meegenomen te worden in
een volgend overleg met RVO/KITE (§10.5 hieronder, uitgebreid), niet stilzwijgend gecorrigeerd.

### 12.8 De IM3-geleverde weerreeks staat niet meer in de output

`weer.parquet` bevatte tot 26-aug-2026 drie bronnen, waaronder `bron="im3"`: de door RVO
meegeleverde weerreeks, genormaliseerd van per-woning-gedupliceerd naar
`(weerstation_nr, tijdstip)`. Die is er op verzoek (26-aug-2026) uit gehaald.

**Reden:** het is afgeleide, herleidbare invoerdata, geen preprocessing-resultaat. Wie hem nodig
heeft kan hem altijd opnieuw uit de bronbestanden halen, precies zoals deze pipeline dat zelf
doet. Hem meeleveren maakt de output groter en suggereert bovendien dat het een gelijkwaardige,
zelfstandig bruikbare reeks is, terwijl §7.3 juist zegt dat de eigen, reproduceerbare ingest de
primaire bron hoort te zijn en de IM3-kopie alleen "na te vertellen" valt.

**Wat blijft:** de reeks wordt tijdens de run nog steeds ingelezen (`extract_im3_weather`) en
gebruikt voor de consistentiecheck van §7.2/§7.3; die vergelijking is immers de hele reden dat we
hem nodig hebben. Alleen belandt hij niet meer in `weer.parquet`. Op de steekproef van 25 woningen
kromp die tabel daardoor van 1,84 MB naar 0,10 MB.

### 12.9 Chunked verwerking: van "past niet in geheugen" naar constant geheugengebruik

Op de vraag hoe lang een volledige run zou duren, bleek het antwoord eerst te zijn: **hij zou niet
afmaken.** Gemeten (26-aug-2026):

- De volledige dataset is ~536 M measurement-rijen (geschat via bytes-per-rij over 23,9 GB CSV,
  betrouwbaarder dan naïef per-woning schalen vanaf de steekproef, dat gaf 599 M).
- `measurements` + `quality` + `derived` samen in geheugen zou daarvoor ~63 GB vragen. De
  ontwikkelmachine heeft 7,8 GB.

Twee ingrepen:

1. **Chunked verwerken + incrementeel wegschrijven.** De woningen worden in blokken verwerkt
   (`--chunk-grootte`) en met één `pyarrow.ParquetWriter` per tabel weggeschreven. Het piekgeheugen
   wordt daarmee bepaald door de chunkgrootte, niet door de datasetomvang. De standaardwaarde stond
   hier aanvankelijk op 250; die is later doorgemeten en op 25 gezet; zie §12.12.

   Dit **mag** alleen omdat elke kwaliteitscontrole per woning groepeert: `constante_reeks_flags`,
   `uitschieter_flags`, `q_h_vs_dag_consistency`, `dst_dag_rij_aanwezig` en
   `gas_voor_koppeling_verdacht_rapport` kijken nooit over woninggrenzen heen. Een chunk-grens
   tussen twee woningen verandert dus geen enkele uitkomst; een grens dwars dóór een woning zou dat
   wél doen, en daarom wordt uitsluitend op woningniveau gesplitst. De rapportcijfers worden in een
   `RapportAccumulator` verzameld die O(aantal woningen) groot is, niet O(aantal rijen).

   Om het Parquet-schema over chunks heen identiek te houden liggen de categorieënlijsten van alle
   `__cat`-kolommen vast in `src/im3_preprocessing/dtypes.py`; anders zou een chunk waarin
   toevallig geen `d`-rijen zitten een ander categorie-dtype krijgen dan de vorige.

2. **De d/m-koppeling gevectoriseerd.** `couple_weather_to_measurements` en
   `couple_gas_hhv_to_measurements` deden een Python-loop per `d`/`m`-rij, met per iteratie een
   boolean mask over de hele weer-/gasreeks. Nu wordt het weer/gas éénmalig per lokale
   kalenderdag/-maand voorgeaggregeerd en met een merge gekoppeld.

   Dat geeft **exact hetzelfde resultaat**: het lokale-dagvenster `[dag 00:00, dag+1 00:00)` bevat
   per definitie precies de uren waarvan de lokale kalenderdatum die dag is, dus de
   zomertijd-correctheid van §2.4 blijft behouden zonder het venster expliciet uit te rekenen: een
   23-uursdag levert 23 uren in die groep, een 25-uursdag 25. Geverifieerd tegen de oude
   implementatie op de steekproef: identiek op float32-afrondverschil na (max 9,5·10⁻⁷ °C), geen
   enkele NaN-mismatch, methode-labels identiek.

   Gemeten op de steekproef: weerkoppeling 37 s → 2,1 s (17×), gaskoppeling 37 s → 1,7 s (21×).

Zie `README.md` voor de resulterende capaciteitseisen en verwachte looptijd.

### 12.10 Tijdstempels in de output: tz-aware Europe/Amsterdam

Op verzoek (26-aug-2026) is elke tijdkolom in de output tz-aware **Europe/Amsterdam** in plaats van
UTC. Intern rekent de pipeline nog steeds in UTC (eenduidig voor joins en interpolatie); de
omzetting gebeurt vlak vóór het wegschrijven, met `timestamps.naar_lokale_tijdzone`.

**Waarom lokale tijd en niet UTC:** menselijk gedrag (douchen, koken, thermostaat lager zetten)
hangt aan de lokale klok, niet aan UTC. Een tz-aware lokale tijdstempel maakt dat direct afleesbaar
bij visuele inspectie én voor algoritmes, **zonder** de absolute tijd te verliezen: `tz_convert`
verandert alleen de weergave, niet het instant, dus UTC blijft één `.dt.tz_convert("UTC")`
verderop. Dat is strikt meer informatie dan een kale UTC-kolom, niet minder.

**Is Europe/Amsterdam terecht?** Dit was een expliciete vraag, want Caribisch Nederland (Bonaire,
Sint Eustatius, Saba) hanteert AST (UTC−4) zonder zomertijd; een woning daar zou met
Europe/Amsterdam structureel fout gelabeld worden. Nagezocht, en het antwoord is onderbouwd ja:

1. **Uit de data zelf:** alle 6.283 woningen hangen aan één van 28 KNMI-stations, en die hebben
   allemaal een Europees-Nederlandse 3-cijferige stationscode (210 Valkenburg t/m 391 Arcen).
   KNMI's Caribische stations vallen buiten dat bereik. Geen enkele woning wijst dus naar het
   Caribisch deel.
2. **Uit de regeling:** de ISDE-subsidie, waar deze dataset op leunt (`ISDE vermogen` is een van de
   18 metadata-kenmerken), geldt uitsluitend voor Europees Nederland; Caribisch Nederland is
   ervan uitgesloten. Woningen daar kúnnen dus niet in deze dataset zitten.
3. **Uit RVO's eigen documentatie:** die zegt over `datetime` alleen "UTC" en noemt geen tijdzone,
   geen zomertijd en Caribisch Nederland nergens. Het document spreekt de aanname dus niet tegen,
   maar bevestigt hem ook niet expliciet; vandaar punt 7 in §10 hieronder.

Praktisch gevolg voor `d`/`m`-rijen: die waren al verankerd op lokale middernacht (§1), en zijn in
de output nu ook als zodanig zichtbaar (`2023-01-30 00:00:00+01:00`) in plaats van als het
UTC-equivalent (`2023-01-29 23:00:00+00:00`) dat dezelfde middernacht op een verwarrende datum liet
zien.

### 12.11 Uitpakken is onderdeel van de preprocessing, niet een handmatige stap vooraf

De dataset komt binnen als één `dataset_openbaar.zip` van **3,20 GB**, die uitgepakt **23,91 GB**
beslaat (6.286 leden, plat, deflate). Tot 26-aug-2026 was uitpakken een handmatige stap vooraf en
stonden die 23,91 GB aan losse CSV's permanent op schijf. Dat is nu weg: `src/im3_preprocessing/bron.py`
leest de klantbestanden rechtstreeks als stream uit het archief, en `--raw-dir` mag naar de zip
wijzen (of naar een map waar de zip in staat).

**Waarom dit mag.** Elk klantbestand wordt precies één keer, sequentieel, van begin tot eind
gelezen. Deflate is een stream-formaat: `zipfile.ZipFile.open()` geeft een file-object dat blok voor
blok decomprimeert, en `pandas.read_csv` leest daar direct uit. Het piekgeheugen is daarmee dat van
één klantbestand als DataFrame (precies zoals bij losse CSV's) plus een decompressiebuffer van
enkele tientallen kB. Er is dus geen geheugen-nadeel, alleen een schijf-voordeel.

**Twee bronnen, één interface.** `MapBron` (een map met losse CSV's) blijft bestaan: wie de dataset
al uitgepakt heeft hoeft niets te veranderen, en de tests draaien erop. `ZipBron` leest hetzelfde uit
het archief. Staan ze allebei in dezelfde map, dan wint de zip: dat is het artefact zoals het
gedownload is en dus de canonieke `raw` (§3, principe 7); de losse CSV's zijn dan een overbodige
kopie die weg mag. Met `--raw-bron csv` is dat af te dwingen, bijvoorbeeld om beide paden tegen
elkaar te meten.

**Geverifieerd, niet aangenomen.** Dat de bron niets aan de uitkomst verandert is niet "logisch" maar
getest, op twee niveaus:

- `tests/test_bron.py` bouwt dezelfde inhoud als map én als zip en vergelijkt klantbestand,
  metadata, `home_ids` en tijdbereik, plus een end-to-end test die de héle pipeline over allebei
  draait en de vier Parquet-tabellen met `assert_frame_equal` naast elkaar legt, en een test die
  controleert dat er na een zip-run niets uitgepakt op schijf achterblijft.
- Op de echte dataset (8 woningen, zonder netwerk-ingest): `measurements`, `quality`, `derived` en
  `homes` zijn identiek, en de gegenereerde `data-quality.md` heeft dezelfde SHA-256.

**Kosten en baten, gemeten (26-aug-2026, 8 cores).**

| | uit de map | uit de zip |
|---|---|---|
| schijfbeslag ruwe data | 23,91 GB + 3,20 GB zip | 3,20 GB |
| 100 woningen verwerken | 143 s | 161 s |
| piek-RSS daarbij | 1,67 GB | 1,71 GB |

Streamen kost dus ~13% rekentijd en scheelt 23,91 GB schijf. Op een machine die krap zit (de
ontwikkelmachine heeft 7,8 GB RAM) is dat een gunstige ruil, en het is bovendien de enige variant
waarbij `data/raw/` na afloop nog steeds precies bevat wat er gedownload is.

**Eén echte kostenpost: het tijdbereik.** De weer- en gaskwaliteit-ingest gebeuren éénmalig vóór de
chunk-loop en hebben daarvoor het globale `[start, eind]` nodig. Bij losse CSV's is dat spotgoedkoop:
een `seek()` naar het einde levert de laatste regel in één blok I/O. Een deflate-stream is niet
seekbaar: de laatste regel opvragen betekent het hele lid decomprimeren. Drie maatregelen houden dat
klein:

1. **Streamend, niet inlezend.** Er wordt in blokken van 1 MB doorheen gelopen en alleen de laatste
   4 kB vastgehouden. Constant geheugen, ook bij een klantbestand van tientallen MB.
2. **Parallel.** `zlib` laat de GIL los, dus acht threads (elk met een eigen `ZipFile`, want die is
   niet thread-safe) brengen de volle scan van ~105 s naar ~63 s.
3. **Gecachet.** De gevonden eerste/laatste tijdstempel per woning gaat naar een klein JSON-bestand
   in `data/interim`, geldig zolang naam, grootte en wijzigingstijd van de zip gelijk blijven. Een
   vervolgrun leest dat in milliseconden terug, ook met een andere selectie woningen. Gemeten op
   40 woningen: 0,72 s koud, 0,03 s uit cache.

Bovendien wordt de scan helemaal overgeslagen als zowel `--skip-weer` als `--skip-gaskwaliteit`
aanstaan: dan is het tijdbereik nergens voor nodig.

De scan leunt erop dat elk klantbestand op tijd gesorteerd is (geverifieerd op een steekproef van 8
bestanden). Mocht dat ergens tóch niet gelden, dan valt dat later op doordat rijen buiten het
opgehaalde weervenster `ontbrekend_buiten_archief` krijgen, dus geen stilzwijgend verkeerde waarde.

### 12.12 De standaard-chunkgrootte was te groot: 250 → 25

Bij §12.9 is `--chunk-grootte` op 250 gezet zonder het door te meten. Dat is nu wel gedaan (100
woningen, zip-bron, piek-RSS via `psutil`):

| `--chunk-grootte` | tijd | piek-RSS | output |
|---|---|---|---|
| 5 | 134 s | 0,43 GB | 152,8 MB |
| 10 | 129 s | 0,60 GB | 136,2 MB |
| 20 | 178 s | 0,87 GB | 132,7 MB |
| 25 | 159 s | 1,07 GB | 136,8 MB |
| 50 | 161 s | 1,71 GB | 132,8 MB |
| 100 | 237 s | 2,03 GB | 132,8 MB |

Het piekgeheugen is ruwweg **0,35 GB vast + 17 MB per woning in de chunk**, en een grotere chunk
levert *geen* snelheidswinst op, eerder verlies. De oude standaard van 250 zou dus ~4 GB vragen
zonder er iets voor terug te geven, op een machine met 7,8 GB totaal. De standaard is daarom 25
(~1,1 GB piek); bij weinig vrij geheugen is 10 een betere keuze. Onder de ~10 gaat de Parquet-output
merkbaar groeien doordat de row groups te klein worden.

Los daarvan is de row-group-grootte losgekoppeld van de chunkgrootte (`ROW_GROUP_MAX = 1.000.000`
rijen). Zonder die bovengrens schrijft een chunk van 250 woningen ~21 M rijen in één row group,
waarmee iedere lézer van het bestand gedwongen wordt datzelfde blok in één keer in geheugen te
nemen. Het geheugenprobleem verplaatst zich dan simpelweg naar de gebruiker van de output.

### 12.13 Geospatiale interpolatie uit het standaardpad: reproduceren i.p.v. herberekenen

**Aanleiding (feedback 26-08-2026):** tijdens de eerste volledige run viel op dat er na het ophalen
van de KNMI-data veel tijd naar geospatiale en temporele interpolatie ging. Terechte vraag: die
geospatiale stap is voor déze preprocessing helemaal niet nodig. IM3 geeft per woning een
`Weerstation_nr`, dus er wordt altijd weer opgevraagd **op de coördinaat van een KNMI-station dat
zelf al in de brondata zit**, nooit op een willekeurig GPS-punt. Het doel is de stationsreeks
reproduceren, niet interpoleren naar een plek waar geen station staat.

**Waarom de interpolatie er oorspronkelijk in zat:** §7.3 redeneerde vanuit
`needforheat-dutch-weather-software`, dat is gebouwd om naar een GPS-locatie te interpoleren, en
koos ervoor om dan maar naar de stationscoördinaat te interpoleren zodat de vergelijking met IM3
"appels met appels" bleef. Dat is een verdedigbare, maar duurdere route naar hetzelfde getal: een
RBF-interpolant is per constructie (vrijwel) exact op zijn eigen datapunten.

**Bewijs dat het hetzelfde getal is,** en niet alleen theorie:

| station | mediane afw. t.o.v. IM3, RBF-geïnterpoleerd | idem, rauwe stationswaarde |
|---|---|---|
| 210 | 0,885 °C | 0,800 °C |
| 240 | 0,600 °C | 0,600 °C |

Die cijfers stonden al in `docs/data-quality.md`: ze zijn precies de §12.4-diagnose, die destijds is
gebouwd om een ándere vraag te beantwoorden. Aanvullend legt
`tests/test_weer.py::test_geospatiale_interpolatie_geeft_op_een_station_hetzelfde_antwoord` (een
netwerktest) vast dat de mediane afwijking tussen beide varianten op hetzelfde station < 0,5 °C is.

**Wat de interpolatie kostte:** `geo_interpolate_weather_data` bouwt intern per tijdstip én per
metric een nieuwe `RBFInterpolator` op. De kosten schalen dus met
`n_stations × n_tijdstippen × n_metrics`, niet met de hoeveelheid data. Op een steekproefvenster
van 30 dagen valt dat niet op; op de volledige run (28 stations × ~34.000 uren × 3 metrics, §2.3
terug tot de vroegste `m`-rij) is het precies de stap die de weer-ingest onwerkbaar traag maakte.
Deze kanttekening stond al als waarschuwing in de docstring van `fetch_own_weather`; de conclusie
is nu dat het probleem niet opgelost hoeft te worden, maar vermeden.

**Wat er verandert:**

- `bron="eigen_ingest"` (de primaire bron in `weer.parquet`) is nu de **rauwe, niet-geïnterpoleerde
  uurwaarde van het station zelf**, geleverd door `fetch_own_weather_direct`. Dat is nog steeds een
  eigen, reproduceerbare ophaal via `needforheat-dutch-weather-software`; alleen zonder de
  RBF-stap. De reproduceerbaarheidsredenering van §7.3 blijft dus volledig overeind: het gaat erom
  dat wij de reeks zelf kunnen herhalen, niet dat we hem herberekenen.
- `fetch_own_weather` (mét RBF) blijft bestaan, maar is opt-in via
  `--weer-geointerpoleerd-diagnose` en schrijft dan `bron="eigen_ingest_geointerpoleerd"`. De oude
  categorie `eigen_ingest_direct` vervalt: de twee bronnen hebben van rol gewisseld.
- Temporele interpolatie blijft in beide paden staan. Die is wél nodig en wél goedkoop: `q`-rijen
  liggen op kwartieren, de KNMI-reeks op hele uren.

**Wanneer je de RBF-variant wél wilt:** zodra er naar een echte woningcoördinaat geïnterpoleerd zou
worden in plaats van naar een station (§7.3 noemt dat expliciet als mogelijke latere stap). Dán
bestaat er geen rauwe stationswaarde om tegen te vergelijken en doet de interpolatie wél
inhoudelijk werk. Dat is een andere vraag dan deze preprocessing beantwoordt, en dus terecht een
aparte, expliciete keuze.

### 12.14 Tijdresolutie-mismatch brak de h/q-koppeling van weer en gas

**Gevonden door de eerste volledige run (26-08-2026), niet door een test.** Het
kwaliteitsrapport over alle 6.283 woningen liet dit zien:

```
weerkoppeling_methode__cat over de volledige run:
  ontbrekend_buiten_archief     532.788.909  (99,1%)
  gemiddelde_dag                  4.461.970  ( 0,8%)
  gemiddelde_maand                  220.043  ( 0,0%)
```

`punt_uur` en `punt_interpolatie` kwamen **helemaal niet voor**. Alle `h`- en `q`-rijen, samen
99,1% van de dataset, misten hun weerwaarden. De calorische gaswaarde vertoonde exact hetzelfde
patroon: 532,8 M rijen op de vaste fallback-constante, en precies de 4.694.267 `d`+`m`-rijen met
een echte waarde.

**Oorzaak.** `measurements.tijdstip` is `datetime64[ns]`, maar de KNMI-reeks kwam als
`datetime64[us]` uit `needforheat-dutch-weather-software`. De koppeling vergeleek beide via
`.astype("int64")`, en dat geeft het getal in de **eigen** resolutie van de reeks: nanoseconden
tegenover microseconden, een factor 1000. Daardoor kon de exacte match voor `h` nooit slagen, en
legde `np.interp` alle `q`-rijen rechts buiten het bereik, wat met `right=np.nan` overal NaN gaf.
De `d`/`m`-tak bleef wél werken, want die koppelt op een lokale dag-/maandsleutel in plaats van op
epoch-integers. Dat verklaart het patroon exact.

**Waarom niets alarm sloeg.** De getroffen rijen kregen keurig
`weerkoppeling_methode__cat = "ontbrekend_buiten_archief"` mee. Dat is een geldige, bestaande
uitkomst (bedoeld voor rijen buiten het opgehaalde venster), dus er was geen foutmelding, geen
NaN-explosie en geen gefaalde assert. Een stille degradatie die zich voordeed als normaal gedrag.

**Waarom de bestaande test hem niet ving.** `tests/test_weer.py` bouwde de weerreeks met
`pd.date_range()`, en dat geeft altijd `ns`. De fixture kón het probleem per constructie niet
reproduceren. Bovendien geeft `pd.DataFrame([{... "tijdstip": <Timestamp> ...}])` in pandas 2.x
juist `us`, dus ook de meetkant van de fixture stond niet op de resolutie die de pipeline
werkelijk produceert. Beide kanten stonden toevallig gelijk.

**De ingreep, op drie plekken:**

1. `timestamps.naar_epoch_ns()` dwingt nanoseconden af via `.dt.as_unit("ns")`, ongeacht wat de
   bron levert, en weigert een niet-tz-aware reeks. `weer.py` en `gaskwaliteit.py` gebruiken die
   in plaats van een kale `.astype("int64")`.
2. `weer._naar_weer_kolommen()` zet de opgehaalde reeks meteen op `ns`, zodat ook `weer.parquet`
   dezelfde resolutie krijgt als de andere tabellen. Dat was al een inconsistentie in de output:
   `weer.parquet` was `timestamp[us]` terwijl de rest `timestamp[ns]` was.
3. `tests/test_weer.py::test_koppeling_werkt_ongeacht_tijdresolutie_van_de_weerreeks`
   parametriseert over `ns`/`us`/`ms`/`s` en zet de meetkant expliciet op `ns`. Geverifieerd dat
   die test met het oude gedrag faalt op `us`, `ms` en `s`, en slaagt met de fix.

**Les die breder geldt dan deze bug.** Een vlagwaarde die "geen data" betekent, is een slechte
plek om een defect te laten landen: hij is niet te onderscheiden van de legitieme situatie. Het
loont om bij zo'n categorie een plausibiliteitsgrens te hebben, bijvoorbeeld een waarschuwing in
het rapport zodra `ontbrekend_buiten_archief` een onwaarschijnlijk groot aandeel krijgt terwijl er
wél een weerreeks is opgehaald. Dat staat nog open, zie §10.8.

### 12.15 De tijdbereik-scan las kale datums als UTC, dus begon het weervenster te laat

**Gevonden vanuit de afnemende repo**, door de output van de volledige run
tegen zijn eigen contractcheck te leggen. Dat is een ander soort vondst dan §12.14: niet uit ons
eigen rapport, maar doordat een consument van het artefact iets naast elkaar legde wat wij niet
naast elkaar hadden gelegd.

Gemeten op de run van 26-08-2026:

| tabel | eerste tijdstip (UTC) |
|---|---|
| `measurements.parquet` | `2021-06-29 22:00:00+00:00` |
| `weer.parquet` | `2021-06-30 00:00:00+00:00` |

Het weer begon dus **2 uur later** dan de metingen, precies de UTC-offset van CEST.

**Oorzaak.** `bron._parse_datetime_veld()` las het eerste CSV-veld met
`pd.to_datetime(..., utc=True)`. Voor `q`/`h`-rijen klopt dat, want die zijn al tz-aware UTC. Maar
voor `d`/`m`-rijen is dat veld een **kale lokale datum**, en die werd zo als `D 00:00 UTC` gelezen
terwijl `timestamps.resolve_timestamps()` diezelfde datum terecht als `D 00:00 lokaal` resolved.
Omdat de eerste regel van een klantbestand vrijwel altijd een `m`-rij is, viel de ondergrens van
het opgehaalde venster daardoor structureel te laat.

De oude docstring anticipeerde hierop en zat er twee keer naast: het is niet "hooguit één uur" maar
de volle UTC-offset, dus 2 uur in de zomertijd, en het venster werd nergens "sowieso afgerond".
Beide beweringen zijn nu weg in plaats van bijgesteld.

**Alleen de startkant is fout.** Voor een `d`/`m`-rij is de naïef-als-UTC-waarde altijd *later* dan
de correcte. Bij de `min()` geeft dat een venster dat te laat begint, wat schaadt; bij de `max()`
een venster dat iets te ruim is, wat niets kost.

**De praktische impact was klein maar de vorm is verraderlijk.** Het ging om de eerste uren van de
vroegste dag, en dat zijn `m`-rijen die via maandgemiddelden koppelen. Maar net als bij §12.14
landde het defect in `ontbrekend_buiten_archief`, een geldige categorie, dus er was geen enkel
signaal. Twee onafhankelijke bugs die allebei in diezelfde vlag verdwijnen, is een sterk argument
voor de open vraag in §10.8.

**De fix, en waarom niet met een marge.** De voor de hand liggende ingreep is een dag speling op
het resultaat van `tijdbereik()`. Dat werkt, maar het maskeert de oorzaak en laat de foute waarden
in de cache staan. In plaats daarvan leest `_parse_datetime_veld()` nu dezelfde semantiek als
`resolve_timestamps()`: een veld mét tijdzone als UTC, een kale datum als lokale middernacht.

**Let op de cache, en dat is het echte addertje.** `data/interim/tijdbereik-<zip>.json` bewaart de
al geparste min/max per woning en werd alleen ongeldig bij een andere naam, grootte of mtime van de
zip. Die veranderen niet. Een fix in de parser zou dus **stil niets doen** op een machine die de
oude waarden al gecachet had, en dat pas na uren rekenen laten merken. Daarom heeft de cachesleutel
nu een `versie`-veld (`ZipBron.CACHE_VERSIE`): een cache van een oudere versie wordt genegeerd en
opnieuw opgebouwd. Dat is robuuster dan een instructie om een bestand weg te gooien.

**Vastgelegd in tests, niet in een aanname.** `tests/test_bron.py` toetst nu per intervaltype dat
`_parse_datetime_veld()` exact hetzelfde tijdstip geeft als `resolve_timestamps()`, inclusief beide
zomertijd-overgangsdagen, plus een integratiecheck dat de venster-ondergrens nooit ná de vroegste
geresolveerde meting ligt. Twee bestaande tests legden juist het foute gedrag vast en zijn
bijgesteld, met de reden erbij in plaats van een aangepaste magische waarde.

Geverifieerd op de echte dataset na de fix: `start = 2021-06-29 22:00:00+00:00`, exact gelijk aan
de vroegste meting.

### 12.16 Intervalsemantiek: begin-labeling, alleen vermogens, en de m-rij-fout

Uitgewerkt in een apart document: [`ontwerp-intervalsemantiek.md`](ontwerp-intervalsemantiek.md).
Kort samengevat, drie samenhangende punten.

**Het probleem.** `tijdstip` betekende drie verschillende dingen tegelijk: het **einde** van het
interval bij `q`/`h`, het **begin** bij `d`, en bij `m` het begin van de *laatste dag* terwijl
`interval_duur__s` de hele maand beschrijft. Die laatste combinatie levert bij elke uitleg onzin op.

**De keuze.** `tijdstip` wordt overal het **begin** van het interval, en heet daarom voortaan
`tijdstip_start`. Dat sluit aan bij pandas (`resample(label="left")` is de default voor
uur/kwartier/dag), bij ENTSO-E/IEC 62325, en bij de afnemende simulatie, die met kale `.resample()`
al impliciet van begin-labeling uitgaat. KNMI en IM3 zijn hier juist de uitzondering met
einde-labeling; die afwijking wordt expliciet gedocumenteerd inclusief de omrekening terug.

**Afgevallen alternatieven, op gemeten gronden.** `pd.IntervalDtype` kan niet naar Parquet
(`TypeError: Conversion to arrow with subtype 'datetime64[us, Europe/Amsterdam]' is not supported`).
Een aparte `tijdstip_eind`-kolom kost 1,57× op schijf, dus richting 10 GB extra over drie tabellen,
voor informatie die al afleidbaar is uit het bestaande `interval_duur__s`. Begin plus duur is
precies de ISO 8601-vorm `start/duur` en kost niets extra.

**Dit repareert meteen de weerkoppeling.** Een `h`-rij stond op het einde (01:00) en de weerwaarde
op het begin (00:00), dus kreeg de meting over 00:00-01:00 het weer van 01:00-02:00. Structureel een
uur te laat, en dat verklaart ook de "0,500 °C afwijking" die bij 21 van de 28 stations in de
consistentiecheck stond: na correctie matchen 24 van de 27 stations exact 0,000 tegen de IM3-reeks.
`weer.parquet` hoeft daarvoor niet te veranderen, want de KNMI-reeks is al begin-gelabeld.

**Twee correctiepaden die elkaar controleren:** een eenmalige migratie van de bestaande output
(zodat de run van 7 uur niet over hoeft) en de fix in de pipeline zelf. De uitkomst van de fix op
een steekproef van 20 woningen moet exact gelijk zijn aan diezelfde 20 woningen uit de gemigreerde
volledige output. Zie het aparte document voor de omzetregels per intervaltype en voor de twee
manieren waarop die test kan falen zonder dat er iets mis is.

**Twee bevindingen die er tijdens het uitwerken bij kwamen.**

*De vermogens van `m`-rijen zijn een factor ~30 te laag.* `derived` deelt energie door
`interval_duur__s`, maar een `m`-waarde is volgens §2.1 het gemiddelde **dagverbruik**, geen
maandtotaal. Er wordt dus een dagwaarde door een maandduur gedeeld. Gemeten op woning 1000:
`e_net__W` van 30,7 waar het daggemiddelde 860,3 is, precies een factor 28 in februari en 31 in
maart. Raakt 220.279 rijen in `e_net__W`, `g_gebruik__m3_s_1` en `g_gebruik__W`. §2.1 waarschuwde
hier letterlijk voor; de waarschuwing is opgevolgd in de labeling maar niet in de berekening.

*De output bevat voortaan alleen vermogens.* Op verzoek (27-08-2026) vervallen `e_net__kWh` en
`g_gebruik__m3` uit `measurements` ten gunste van `e_net__W` en `g_gebruik__m3_s_1`. Een flow is
intervalonafhankelijk, dus `q`/`h`/`d`/`m` worden direct vergelijkbaar, en de vraagstukken in de
energietransitie gaan over vermogen. Gemeten dat dit verliesvrij is: energie terugrekenen via
`interval_duur__s` geeft een mediane fout van exact 0 en een maximum van 1,2e-07, de
float32-afrondgrens. Bij dezelfde slag gaat `ghi__kWh_m_2` naar `ghi__W_m_2`: die waarde bleek al
een instraling in kW/m2 te zijn (piek 0,975, en het gemiddelde is over alle vier de intervaltypen
gelijk, wat een flow verraadt) en droeg dus een verkeerde eenheidsnaam.

**Status (27-aug-2026): pad 2 geïmplementeerd en geverifieerd, pad 1 (migratie) gedeeltelijk
gedraaid.** Alle code-wijzigingen uit dit hoofdstuk zitten in `timestamps.py`, `intervals.py`
(nieuw: `compute_energie_deler_s`), `pipeline.py` (`e_net__W` verhuisd naar
`build_measurements()`), `derived.py`, `cleaning.py`, `quality.py`, `weer.py`, `gaskwaliteit.py`,
`bron.py` (`_parse_datetime_veld` conservatief herzien, zie hieronder) en `report.py`, met bijgewerkte
tests (100 offline tests groen) en een smoke-test op de echte dataset:

- m-rijen en d-rijen `e_net__W` zitten na de fix in dezelfde ordegrootte (voorheen ~30x uiteen).
- De weerkoppeling matcht na de fix **exact 0,000** op temperatuur en ghi (was structureel een uur
  verschoven), precies zoals hierboven voorspeld.

**Neveneffect op `bron._parse_datetime_veld()` (de tijdbereik-scan, §12.15).** Die functie kende tot
nu toe dezelfde semantiek als `resolve_timestamps()`, wat kon omdat beide voor `q`/`h` "gewoon UTC"
deden en voor `d`/`m` "gewoon lokale middernacht". Na deze wijziging is dat niet meer waar: `q` en
`h` trekken een verschillende vaste duur af, en `d`/`m` verschillen juist WEL. Omdat de scan alleen
het eerste CSV-veld leest (geen `interval_type`-kolom erbij), kan hij dat onderscheid niet meer
maken. Oplossing: de scan is nu bewust CONSERVATIEF (altijd de duurste aftrek, altijd de vroegste
maandinterpretatie), zodat de venstergrens gegarandeerd niet later ligt dan de werkelijke
`tijdstip_start` -- consistent met de veiligheidsrichting van de §12.15-fix zelf, alleen nu
structureel geborgd in plaats van toevallig kloppend.

**Pad 1 (migratie) is afgerond en de gelijkwaardigheidstest is geslaagd (29-aug-2026).** Fase A en
fase B zijn volledig gedraaid op de volledige 537.470.922-rijen-output (in hervatbare batches, zie
hieronder). Onderweg drie bevindingen, alle drie gevonden en gefixt vóór of tijdens de migratie,
niet erna:

1. **Een woning kan een fysieke Parquet-rijgroepgrens overschrijden** (11 van de eerste 31 grenzen
   deden dat), wat de vlag-herberekening in `quality` zonder correctie fout zou laten lopen op zulke
   grenzen. `migreer_intervalsemantiek.py` buffert daarom tot en met de laatste volledige woning.
2. **`shutil.move()` faalde op Windows (`WinError 32`)** doordat `pq.ParquetFile`-objecten hun
   bestandshandle niet loslieten vóór het hernoemen van datzelfde bestand -- in zowel
   `migreer_intervalsemantiek.py` als `migreer_fase_b_weer.py`. Fix: expliciet `.close()` vóór elke
   `shutil.move()` op een pad dat net gelezen is.
3. **`weer.parquet` had de fix niet vanzelf meegekregen**: het bestand was geschreven door de OUDE
   code en had dus nog `ghi__kWh_m_2` (÷1000), terwijl de nieuwe `weer.couple_weather_to_measurements()`
   `ghi__W_m_2` verwacht. Apart, eenmalig gerepareerd (`migreer_weer_ghi.py`, hernoemen + x1000; het
   bestand zelf hoefde niet te worden herkoppeld, alleen de kolom).

Deze sessie-omgeving bleek lange, onbewaakte achtergrondprocessen bijna volledig te throttlen
(soms nul voortgang over tientallen minuten), terwijl dezelfde code in kortere, actief bijgehouden
batches (~30-40 rijgroepen, ruim binnen een timeout) betrouwbaar snel liep. Beide migratiescripts
zijn daarom hervatbaar gemaakt (`--vanaf`/`--tot`/`--samenvoegen`).

**Gelijkwaardigheidstest (§7): geslaagd.** Op de 20-woningen-steekproef (geen venster-beperkingen)
zijn `measurements` en `quality` **bit-voor-bit gelijk** tussen pad 1 (migratie) en pad 2
(pipeline-fix). In `derived` zijn ook `tijdstip_start`, `g_gebruik__m3_s_1`, `gas_hhv_bron__cat`,
`weerkoppeling_methode__cat`, `temp_buiten__degC` en `wind__m_s_1` bit-voor-bit gelijk. Twee kolommen
wijken heel licht af, allebei precies zoals §7 vooraf voorspelde als mogelijke valse-negatievebron:

- `actual_gas_std_hhv__J_m_3` / `g_gebruik__W`: de niet-gedocumenteerde `mijnenergiedata.nl`-API gaf
  tussen de twee ophaalmomenten enigszins herziene waarden (max. 0,5% relatief verschil) -- exact
  het scenario dat §7 als "geen bug" bestempelt.
- `ghi__W_m_2`: float32-afrondruis van het ongedaan maken van de oude ÷1000-schaling in het
  bestaande `weer.parquet` (max. relatief verschil 2,3e-07 -- de float32-precisiegrens zelf).

### 12.18 De extreme uitschieters zijn geen meterwissels maar een tellersoverloop van 10.000 kWh

De volledige run maakte iets zichtbaar wat op de steekproef van 25 woningen niet opviel: de tien
extreemste `e_net__W`-waarden liggen allemaal rond ±40.000.000 W, en die getallen lijken te veel op
elkaar om ruis te zijn. 40 MW over een kwartier is precies 10.000 kWh. Dat is nagerekend over de
hele dataset.

**Wat de scan oplevert** (filter `|e_net__W| > 1 MW` over alle 537.470.922 rijen):

| | |
|---|---|
| rijen | **410** (0,00008 % van alle rijen) |
| woningen | **112** van 6.283 (1,8 %) |
| intervaltypen | `q` 209 · `h` 201 — dezelfde gebeurtenis in beide aggregaties |
| impliciete sprong | **minimaal 9.988,1 en maximaal 10.001,7 kWh** |
| binnen 9.990–10.000 | 397 van 410 |
| teken | 257 negatief, 153 positief; 53 woningen hebben beide |

**Elke van de 410 rijen is een sprong van 10.000 kWh, met een marge van 13 kWh.** Niet één ligt
daarbuiten. Dat is geen uitschieterverdeling maar een **modulus**: een register met vier cijfers
vóór de komma slaat om bij 9999,9.

Twee details bevestigen het mechanisme:

- **De sprong ligt net *onder* 10.000, niet erop.** Bij een omslag is de gemeten verschilwaarde
  10.000 min het verbruik in dat interval, dus systematisch iets lager. Een sentinelwaarde of een
  afkapping zou exact 10.000 geven; ruis zou spreiden. Wat we zien is precies wat een omslag doet.
- **De acht waarden bóven 10.000 zijn geen tegenvoorbeeld maar een bevestiging.** Was het verbruik
  in dat interval negatief — een woning die op dat moment terugleverde — dan wordt de sprong juist
  iets groter dan 10.000. Maximaal 10.001,7, dus 1,7 kWh teruglevering in een kwartier: een
  plausibele PV-opbrengst.

**Wat dit betekent voor de aanbeveling in §10.1.** Die stond er al — controleer vóór het verschillen
of de cumulatieve meterstand ooit daalt — maar als hypothese, met een meterwissel als vermoedelijke
oorzaak. Dat vermoeden is nu te preciseren: een meterwissel geeft een **willekeurige** knik, en dit
is een **vaste** van 10.000 kWh. Het gaat dus niet (alleen) om vervangen meters maar om een register
dat overloopt, en dat is een gerichter en makkelijker op te lossen probleem: het is met één modulo
te herstellen, vóór het verschillen, zonder naar de werkelijke stand te hoeven gokken.

**Wij kunnen dat hier niet repareren** en dat blijft zo: IM3 publiceert alleen de al-verschilde
reeks, dus de onderliggende standen ontbreken (§3 principe 5). De vlaggen
`e_net_uitschieter__flag` blijven het signaal. Maar de melding richting RVO/KITE/BDH wordt hiermee
concreet genoeg om iets mee te kunnen: 410 rijen, 112 woningen, sprong 10.000 kWh, en de vindplaats
staat in het kwaliteitsrapport.

### 12.17 Twee lopende-nacht-risico's weggenomen: rapport herbouwbaar, run hervatbaar

Vóór deze wijziging waren er twee redenen waarom een onbewaakte nachtrun over de volledige dataset
(~7 uur, zie README) onverantwoord was: een wijziging in alleen de rapporttekst kostte de hele run
opnieuw, en een afgebroken run begon weer bij chunk 0. Patroon overgenomen van de zusterrepo
demoprojecthybride-dataset-preprocessing, waar dit een week eerder is opgelost; zie die repo's
`chunking.py`/`opmaak.py` voor het origineel.

**Rapport herbouwbaar zonder de pijplijn opnieuw te draaien.** `pipeline.run` schrijft aan het eind
van elke run `<out-dir>/rapport_accumulator.json` (`report.schrijf_accumulator`): een volledige-
getrouwe JSON-serialisatie van `RapportAccumulator` plus de paar kleine, verder nergens bewaarde
stukjes rapportinvoer (`is_steekproef`, `weer_venster_dagen`, de weer-consistentietabellen, en de
verzameling stationsnummers uit het IM3-weer). JSON boven pickle: leesbaar (`git diff` toont
letterlijk welke cijfers veranderden), taal-onafhankelijk, en hier versiebestendig omdat
`naar_json_dict`/`uit_json_dict` een expliciet schema zijn, geen automatische object-dump.
`python -m im3_preprocessing.report --out-dir data/processed --docs-dir docs` herbouwt
`docs/data-quality.md` daaruit (plus `homes.parquet`/`weer.parquet`, die toch al bewaard worden).

**Hervatten na een afbreking.** De chunk-loop schrijft niet langer rechtstreeks naar de
eindtabellen, maar per chunk een atomisch (`.tmp` + hernoeming) deelbestand naar `<out-dir>/parts/`
(`im3_preprocessing.chunking`, drie contracttabellen + een verplicht JSON-rapportdeel, zie die
module-docstring voor waarom dat rapportdeel bestaat en waarom het verplicht is). Pas ná de hele
loop worden de deelbestanden streamend samengevoegd tot `measurements.parquet`/`quality.parquet`/
`derived.parquet` (`pyarrow.parquet.ParquetWriter`, nooit een volledige tabel in pandas). Bij een
herstart wordt een chunk waarvan alle deelbestanden al compleet zijn overgeslagen; `--opnieuw` gooit
`parts/` weg en begint schoon.

**De vingerafdruk-check is niet optioneel.** Een chunkplan (welke woningen in welke chunk, in welke
volgorde) krijgt een sha256-vingerafdruk, vastgelegd in `parts/plan.json`. Zonder die check zou een
hervatting alleen op bestandsnaam controleren of een chunk "compleet" is, en dan een `chunk_000` uit
een eerdere proefrun met een andere `--chunk-grootte`/woningselectie stilzwijgend hergebruiken -- de
uitvoer zou dan woningen missen zonder foutmelding. Dat is in de zusterrepo ook echt gebeurd
(05-09-2026); vandaar dat `chunking.plan_vingerafdruk`/`herstel_run` hier hetzelfde patroon volgen.

**Waarom de rapportbijdrage een eigen deelbestand is, niet herleid uit de drie Parquet-delen.** Twee
stukken brondata die `RapportAccumulator.voeg_chunk_toe` nodig heeft, staan NERGENS in
`measurements`/`quality`/`derived`: `g_gebruik__m3_s_1` (een interne werkkolom, vóór het afknippen
naar `MEASUREMENTS_OUTPUT_KOLOMMEN`, nodig voor `quality.gas_negatief_rapport` e.a.) en het door IM3
meegeleverde weer (`im3_weer`, met opzet niet in `weer.parquet`, §12.8). Een hervatte run zou de
rapportbijdrage van een overgeslagen chunk dus stilzwijgend missen als die alleen uit de drie
contracttabellen herleid zou worden -- geen foutmelding, een VERKEERD rapport. Daarom wordt de
rapportbijdrage per chunk apart als JSON weggeschreven (`chunking.rapport_pad`), terwijl de
brontabellen nog vers in geheugen staan, en telt `pipeline.run` de uiteindelijke accumulator altijd
op uit de rapportdelen van ALLE chunks (ongeacht vers verwerkt of hervat) -- één codepad, geen aparte
"vers"/"hervat"-varianten. Dat mag zonder risico op dubbeltelling omdat elke woning in precies één
chunk zit (§12.9): alle tellingen zijn dus veilig te sommeren (`RapportAccumulator.
voeg_accumulator_toe`), op de dagconsistentie-steekproeven na (`dagcheck_kwartier`/`_uur`), waarvan
de RUWE waarden bewaard blijven -- een mediaan is niet opnieuw te berekenen uit alleen een eerder
uitgerekende mediaan.

**Nederlandse getalopmaak in het rapport.** `report.py` gebruikte `{:,}` (`1.974.078` werd
`1,974,078`, wat een Nederlandse lezer als een getal met decimalen leest). `im3_preprocessing.opmaak`
(ongewijzigd overgenomen uit de zusterrepo: bewust locale-logica zonder repo-specifieke aannames)
lost dat op: komma als decimaalteken, punt per duizendtal vanaf 10.000 (zodat een jaartal als 2022
niet "2.022" wordt), vaste spatie vóór het procentteken. Bij het doorvoeren bleek `percentage()` een
FRACTIE te verwachten terwijl een deel van `report.py` al met 100 vermenigvuldigd had (zelfde
valkuil als in de zusterrepo) -- per plek nagegaan wat de berekening al opleverde vóór
`opmaak.percentage`/`opmaak.getal` erover heen ging.

**Twee bevindingen tijdens die validatie, allebei vóór de hierboven beschreven versie al gefixt.**

1. *`uit_json_dict` maakte van meerdere dagcheck-buffers ten onrechte één array.* `naar_json_dict` bewaart per samengevoegde chunk een EIGEN (mogelijk ongelijk lange) steekproef; de eerste versie van `uit_json_dict` deed `np.array(lijst_van_lijsten)` in plaats van per buffer een eigen array te maken. Bij één chunk (de meeste unit tests) viel dat niet op; pas de echte 4-chunks-steekproef liet `dagcheck_statistiek`'s `np.concatenate` crashen ("array at index 0 has size 4274 and the array at index 1 has size 3602"). Gefixt en afgedekt met een regressietest die bewust twee ongelijk lange buffers samenvoegt (`tests/test_report.py`).
2. *`rapport_accumulator.json` was 65 MB, niet klein.* De eerste aanname ('op deze steekproefschaal toch al klein') bleek fout: `im3_weer` (het door IM3 meegeleverde weer, nodig om na een hervatting `weer_consistentie` correct opnieuw te kunnen berekenen) is O(stations x uren), niet O(woningen), en bevatte op deze 20-woningen-steekproef al 274.793 rijen. `build_report` gebruikt uit `acc` zelf nooit die rijen (alleen de al-gereduceerde stationslijst, apart bewaard), dus `RapportAccumulator.naar_json_dict` kreeg een `inclusief_im3_weer_ruw`-vlag: `False` voor het bestand dat `report.schrijf_accumulator` wegschrijft, `True` (standaard) voor het per-chunk rapportdeel, dat de ruwe rijen wél nodig heeft om na een hervatting correct te kunnen samenvoegen. Resultaat: 65 MB -> 990 kB, exact dezelfde rapporttekst.

**Gevalideerd op een steekproef van 20 woningen** (incl. eigen KNMI-ingest, dus met netwerk):
hervatten na het verwijderen van één chunk-deelbestand liet de overige chunks overslaan en gaf
bit-voor-bit dezelfde eindtabellen (`pandas.testing.assert_frame_equal` na sorteren), en de
rapport-CLI leverde exact hetzelfde rapport op als de run zelf al geschreven had. Zie de
sessieverslaglegging bij deze wijziging voor de gemeten looptijd (niet hier herhaald om niet te
laten verouderen als de proefrun ooit opnieuw gedraaid wordt).

### 12.19 RVO's `sun` is een uursom in kWh/m², geen instraling in W/m²

**Bevinding.** De instralingsvergelijking in de weer-consistentiecheck (§7.2/§7.3) vergeleek twee
verschillende eenheden. `weer.extract_im3_weather` hernoemde RVO's `sun` zonder omrekening naar
`ghi__W_m_2`, terwijl de eigen KNMI-reeks sinds ontwerp-intervalsemantiek §3 echt in W/m² staat.
RVO definieert `sun` als "gesommeerde zoninstraling" in kWh/m² (informatiedocument, variabelentabel),
en de brondata bevestigen dat: `sun` staat alleen op `h`-rijen, de waarden zijn veelvouden van
1/360 kWh/m² (1 J/cm² = 10 kJ/m², precies de resolutie van KNMI's `Q`) en lopen tot ongeveer 0,99.
Een uursom in kWh/m² is numeriek de gemiddelde instraling in kW/m², dus een factor 1000 te klein
naast W/m². De eerdere redenering "sun is dezelfde grootheid als Q, dus hernoemen zonder schaling"
klopte voor de grootheid maar niet voor de eenheid: §3 van ontwerp-intervalsemantiek ging over de
eigen KNMI-reeks (die door 1000 gedeeld werd), niet over RVO's kolom.

De gerapporteerde mediane afwijking van 2,8 tot 8,3 W/m² was daardoor in feite de mediane KNMI-waarde
zelf (1, 2 of 3 J/cm² x 2,78), en de conclusie "binnen de drempel" bewees niets.

**Fix.** `weer.sun_kWh_m2_naar_W_m2`: `sun x 1000 / (interval_duur__s / 3600)`, aangeroepen in
`extract_im3_weather`. De duur komt uit `interval_duur__s` van dezelfde rij (bij `h` altijd 3600 s),
zodat de omrekening ook klopt als er ooit weer op een ander intervaltype staat. Tests in
`tests/test_weer.py`: 1/360 kWh/m² in een uur moet exact KNMI's factor 10.000/3.600 W/m² opleveren,
en een echte bronrij (0,533333 op 1 maart 2023 12:00 UTC) wordt 533,3 W/m² met `tijdstip` = begin
van het uur.

**Herberekend zonder nieuwe run.** De per-chunk rapportdelen (`parts/rapport/chunk_*.json`, §12.17)
bevatten de ruwe IM3-weerreeks nog. Daaruit, met `weer.parquet` van dezelfde run, is de
consistentiecheck opnieuw uitgerekend. Zonder omrekening reproduceert dat het oude resultaat exact
(zelfde `n_overlap` en afwijking per station); met omrekening vervangt het `weer_consistentie` in
`rapport_accumulator.json`, waarna `python -m im3_preprocessing.report` het rapport herbouwde.
Alleen de weersectie van `docs/data-quality.md` veranderde.

**Uitkomst.** Alle 28 stations vallen binnen de drempel van 50 W/m² mediane absolute afwijking. Bij
25 stations is de mediaan 0,0 W/m², is 85 tot 91% van de uren exact gelijk en is het 99e percentiel
1,3 W/m² (bij 391: 36,9 W/m²). Bij 210, 240 en 340 is de mediaan 0,0, 0,8 en 0,2 W/m², maar dat komt
door de nachturen, waar beide reeksen 0 zijn:

| station | mediane afw. overdag (W/m²) | uren > 50 W/m² afwijking | 99e percentiel (W/m²) |
|---|---|---|---|
| 210 | 13,9 | 12,0% | 236 |
| 240 | 22,2 | 15,4% | 285 |
| 340 | 19,4 | 15,1% | 272 |

(overdag: KNMI-waarde > 0; de grootste afwijking is 761 W/m², station 210 op 11 mei 2023.) Dit zijn
dezelfde drie stations die op temperatuur en wind buiten de drempel vallen (§12.4). Bij alle drie
lijkt RVO voor een deel van de uren een andere reeks te hebben gebruikt dan die van het gekoppelde
station; dat is niet verder uitgezocht. De mediaan over alle uren is als maat voor instraling zwak:
hij verbergt verschillen die overdag honderden W/m² groot zijn. Een drempel op alleen daguren, of
op een hoger percentiel, zou dat wel laten zien; dat is een keuze voor §10.4, niet hier gemaakt.

De uitvoertabellen veranderen niet: de RVO-weerreeks staat niet in de uitvoer (§12.8), en
`derived.ghi__W_m_2` komt uit de eigen KNMI-ingest.
