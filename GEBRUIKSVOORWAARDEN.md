# Gebruiksvoorwaarden van de Installatiemonitor 3.0-dataset

Deze repository verwerkt de RVO/KITE Installatiemonitor 3.0-dataset (`dataset_openbaar.zip`,
6.283 woningen). **Dit is geen open data-licentie.** De ruwe dataset staat niet in deze git-repo
(`data/raw/` is gitignored, zie `.gitignore` en ontwerp-preprocessing.md §3 principe 7) en mag niet
door deze repo of via deze repo gedeeld worden.

## Letterlijke voorwaarden

Uit `data/raw/00_Informatie document IM dataset - 20260820.pdf` (§ Gebruiksvoorwaarden, v1.0,
20-08-2026):

> *"De dataset ... is beschikbaar voor **onderzoek en analyses met een maatschappelijk doel**.
> Gebruik van de data moet **gemeld bij KITE** (kite@rvo.nl) en de uitkomsten, resultaten en/of
> analyses moeten **onder dezelfde gebruiksvoorwaarden gedeeld worden met de KITE-community**."*

## Wat dit betekent voor deze repo

1. **Overleg met RVO/KITE gevoerd** (01-09-2026) over de vraag of een herbruikbare
   preprocessingpijplijn zelf al telt als "analyse" die met de KITE-community gedeeld moet worden.
   Uitkomst: bevindingen uit deze preprocessing worden alvast met RVO/KITE gedeeld, en RVO/KITE
   is leestoegang tot deze repo aangeboden. Wat "delen met de KITE-community" precies betekent
   voor de code zelf is daarmee nog niet uitgesproken.
2. **De code valt onder `EUPL-1.2`** (besluit van Kenniscentrum Duurzaam Leven, 19-10-2026). Tot
   nu toe gebeurde delen gericht, met RVO/KITE; openbaar maken van de repo is een
   aparte stap. Zie [`LICENSE`](LICENSE) en ontwerp-preprocessing.md §4 en §10.1.
3. **Melden bij KITE is sowieso verplicht** zodra deze preprocessing daadwerkelijk tegen de
   dataset draait, onafhankelijk van punt 1. Afgedekt met het overleg van 01-09-2026; de volledige
   run over alle 6.283 woningen was toen al uitgevoerd.
4. De **code** in deze repo bevat geen IM3-data en valt onder een eigen licentie, `EUPL-1.2` (zie
   [`LICENSE`](LICENSE)). Die licentie geldt alleen voor de code: de dataset en alles wat per woning
   uit de data volgt, blijven onder de voorwaarden van RVO en KITE in dit document.
5. Wie de dataset zelf wil verkrijgen doet dat via KITE, niet via deze repo. Zie
   [Hoe je de dataset zelf verkrijgt](#hoe-je-de-dataset-zelf-verkrijgt) hieronder.

## Hoe je de dataset zelf verkrijgt

KITE (Kennis- en Dataplatform Individuele Technieken) is een **besloten community** op RVO's
Pleio-platform. De dataset is dus niet vrij te downloaden:

1. Maak een Pleio-account aan op [kennisdelen.rvo.nl](https://kennisdelen.rvo.nl/) en log in.
2. Word lid van de KITE-community: [kennisdelen.rvo.nl/kite](https://kennisdelen.rvo.nl/kite) (vanity-URL die
   doorverwijst naar de groep). Lidmaatschap aanvragen kan op de groepspagina of via
   <kite@rvo.nl>.
3. Download `dataset_openbaar.zip` (3,2 GB) van de pagina **Installatiemonitor (ledenversie)** in
   die groep:
   [directe link](https://kennisdelen.rvo.nl/groups/view/1434df6b-d9c4-4d87-8c73-36834399abeb/kennis-en-dataplatform-individuele-technieken-kite/page/view/90c302e3-40ab-4f0d-a54c-e70c8ce78e2c/installatiemonitor-ledenversie). Die link werkt alleen voor ingelogde leden.
4. Meld je gebruik bij <kite@rvo.nl>. Dat is geen formaliteit maar een voorwaarde, zie hierboven.

**Over die directe link:** de twee UUID's erin zijn Pleio-objectidentificatoren (groep-id en
pagina-id), geen toegangstoken. Nagegaan op 26-08-2026:

- dezelfde URL-vorm met UUID's komt voor bij publiek geïndexeerde KITE- en Helpdesk-pagina's, en
  de groep-UUID is via de publieke vanity-URL `kennisdelen.rvo.nl/kite` te bereiken;
- er zit geen querystring in, en dus geen `token=`, `key=` of `invite=`-parameter;
- een anonieme aanvraag op de directe link geeft **HTTP 404**. De UUID geeft dus uit zichzelf geen
  toegang; die wordt serverzijdig afgedwongen op inlog plus groepslidmaatschap. Bij een echte
  geheime-link-constructie zou het omgekeerde gebeuren: dan zou de link juist zónder inloggen
  werken.

De link publiceren lekt dus niets. Hij helpt alleen niemand die geen lid is.

## Status

| Punt | Status |
|---|---|
| Overleg RVO/KITE over publicatiescope | Gevoerd 01-09-2026; bevindingen gedeeld, leestoegang aangeboden aan RVO/KITE |
| Melding bij KITE van daadwerkelijk gebruik | Afgedekt met dat overleg |
| Inhoudelijke datavragen (ontwerp §10.5-10.7) | Nog niet aan de orde geweest, mee te nemen in een volgend overleg |
| Codelicentie | `EUPL-1.2`, besloten 19-10-2026; zie [`LICENSE`](LICENSE) |
| Publicatie van deze repo | Nog niet openbaar; openbaar maken is een aparte stap |
