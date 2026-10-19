# SPDX-License-Identifier: EUPL-1.2
"""Bouwt ``datapackage.json`` (Frictionless Data Package v1, met een Table Schema per resource) UIT
DE CODE, niet met de hand bijgehouden.

**Bron van waarheid.** De velden per resource komen uit de ``pyarrow.Schema``-objecten in
``tabellen.SCHEMAS``. Twee tests borgen dat die niet uit de pas lopen: ``tests/test_datapackage.py``
vergelijkt elk schema met het datapackage (elk veld in het schema staat in het datapackage en
omgekeerd), en met de Parquet-bestanden die de echte pipeline op een synthetische dataset schrijft.
Een vaste categorieënlijst uit ``dtypes.py`` komt als ``constraints.enum`` in het datapackage, een
kolom met ``nullable=False`` in ``tabellen.py`` als ``constraints.required``.

**`primaryKey`: alleen waar geverifieerd uniek.** Op de volledige run van 06/07-09-2026 (6.283
woningen, 537.470.922 measurement-rijen): ``home_id__str`` is uniek binnen ``homes``;
``(weerstation_nr, tijdstip, bron__cat)`` is uniek binnen ``weer``; ``(home_id__str,
tijdstip_start, interval_type__cat)`` is uniek binnen ``measurements`` (gecontroleerd over alle 252
chunk-deelbestanden, die elk complete woningen bevatten). ``quality`` en ``derived`` nemen die drie
sleutelkolommen rij voor rij over uit ``measurements`` (``cleaning.build_quality_table``,
``derived.build_derived``: een ``.copy()`` van dezelfde kolommen, dezelfde rijvolgorde), dus daar
geldt dezelfde sleutel. ``tijdstip_start`` alleen is geen sleutel: een ``d``-rij en de eerste
``q``/``h``-rij van dezelfde dag beginnen op hetzelfde moment.

**Paden.** Relatief aan de uitvoermap van de pipeline (standaard ``data/processed/``), net als in de
WarmingUP- en DACS-HW-preprocessing. ``datapackage.json`` zelf staat in de repo-root.

**Geen runafhankelijke inhoud.** Rijaantallen en dekking staan in docs/datacatalogus.md en
docs/data-quality.md, niet hier. Daardoor is de kopie die ``pipeline.run`` aan het eind van een run
schrijft identiek aan wat ``python -m im3_preprocessing.datapackage`` los genereert.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow as pa

from . import __version__, tabellen

DATAPACKAGE_BESTANDSNAAM = "datapackage.json"

KITE_PAGINA_URL = "https://kennisdelen.rvo.nl/kite"
EINDRAPPORT_URL = "https://kennisdelen.rvo.nl/kite/installatiemonitor"
DATASET_BESTANDSNAAM = "dataset_openbaar.zip"
INFORMATIEDOCUMENT_BESTANDSNAAM = "00_Informatie document IM dataset - 20260820.pdf"

_ARROW_NAAR_TYPE = (
    (pa.types.is_dictionary, "string"),  # __cat: pandas category, als Parquet-dictionary opgeslagen
    (pa.types.is_string, "string"),
    (pa.types.is_large_string, "string"),
    (pa.types.is_boolean, "boolean"),
    (pa.types.is_integer, "integer"),
    (pa.types.is_floating, "number"),
    (pa.types.is_timestamp, "datetime"),
)


def table_schema_type(arrow_type: pa.DataType) -> str:
    """Het Table Schema-type bij een Arrow-type; ook gebruikt door de test die de echte
    Parquet-footers met ``tabellen.SCHEMAS`` vergelijkt."""
    for test, naam in _ARROW_NAAR_TYPE:
        if test(arrow_type):
            return naam
    raise ValueError(f"Geen Table Schema-type bekend voor Arrow-type {arrow_type!r}")


_HOMES_TAG_BESCHRIJVING = (
    "True als dit systeem in het multi-selectveld {bron} van de woning is aangevinkt (vaste taglijst "
    "in io.py, geverifieerd tegen alle voorkomende tokens)."
)

#: Beschrijving per (resourcenaam, veldnaam), in lijn met docs/datacatalogus.md §5. Een tagkolom van
#: ``homes`` die hier niet apart staat, krijgt de generieke tagbeschrijving hierboven.
VELD_BESCHRIJVINGEN: dict[str, dict[str, str]] = {
    "homes": {
        "home_id__str": "Geanonimiseerde woningsleutel (bron: Customer_id), ook het getal in "
        "IM_customer_<id>.csv; joinsleutel naar measurements, quality en derived.",
        "installatiedatum_wp": "Maand van installatie van de warmtepomp (bron: Installatiedatum_hp, "
        "'YYYY-MM'), als de eerste dag van die maand om 00:00 Europe/Amsterdam. Volgens RVO ook de "
        "aanmelddatum voor het project. Bevat onwaarschijnlijke jaartallen, zie datacatalogus §8.",
        "heeft_thermostaat__bool": "Programmeerbare thermostaat aanwezig (bron: Heeft_thermosstaat, 1/0).",
        "temp_dag_ingesteld__degC": "Daginstelling van de thermostaat, opgegeven door de bewoner "
        "(bron: Dag_temperatuur).",
        "temp_nacht_ingesteld__degC": "Nachtinstelling van de thermostaat, opgegeven door de bewoner "
        "(bron: Nacht_temperatuur).",
        "kookt_op_gas__bool": "Koken op gas (bron: Koken_op_gas, 1/0).",
        "weerstation_nr": "KNMI-stationscode van het dichtstbijzijnde weerstation (bron: "
        "Weerstation_nr); koppelt de woning aan weer.weerstation_nr.",
        "weerstation_naam__cat": "Naam van dat weerstation (bron: Weerstation naam).",
        "vloeroppervlak_bin__cat": "Vloeroppervlak als bin in m2, bijvoorbeeld '115-124' (bron: "
        "Vloer_oppervlak); bewust geen getal.",
        "heeft_ev_opgegeven__bool": "Bewoner gaf een elektrische auto of laadpaal op (bron: EV_opgegeven, 1/0).",
        "isde_vermogen__kW": "Bivalent vermogen van de warmtepomp uit het ISDE-register (bron: ISDE "
        "vermogen); leeg als de bron -1 (onbekend) of niets bevat.",
        "isde_vermogen_onbekend__bool": "True als de bron voor ISDE vermogen de sentinel -1 (onbekend) had.",
        "verwarmingssysteem_ruw__cat": "Het multi-selectveld Verwarmingssysteem letterlijk, "
        "komma-gescheiden; uitgesplitst in de heeft_*__bool-kolommen.",
        "afgiftesysteem_ruw__cat": "Het multi-selectveld Afgiftesysteem letterlijk, komma-gescheiden; "
        "uitgesplitst in de heeft_*__bool-kolommen.",
        "woningtype_bron_afgekapt__bool": "True als Woningtype in de bron afgekapt was ('Rijwoning "
        "(tussen' of 'Rijwoning (hoek') en hier is hersteld.",
        "woningtype__cat": "Woningtype (bron: Woningtype), met de twee afgekapte bronwaarden hersteld "
        "naar 'Rijwoning (tussenwoning)' en 'Rijwoning (hoekwoning)'.",
        "type_glas__cat": "Type beglazing, opgegeven door de bewoner (bron: Type_glas).",
        "muurisolatie_type__cat": "Type muurisolatie, opgegeven door de bewoner (bron: Isolatie_type).",
        "vloerisolatie__cat": "Vloerisolatie ja/nee/weet ik niet, opgegeven door de bewoner (bron: "
        "Vloer_isolatie_type).",
        "dakisolatie_type__cat": "Kwaliteit dakisolatie, opgegeven door de bewoner (bron: Dak_isolatie_type).",
    },
    "measurements": {
        "home_id__str": "Woningsleutel, zie homes.home_id__str.",
        "tijdstip_start": "Begin van het interval waar de rij over gaat, tz-aware Europe/Amsterdam, "
        "voor alle vier de intervaltypen (wijkt af van de bronconventie, zie datacatalogus §4).",
        "interval_type__cat": "Intervaltype uit de bronkolom interval: q (kwartier), h (uur), d (dag), m (maand).",
        "interval_duur__s": "Lengte van het interval in seconden: 900 (q), 3600 (h), de werkelijke "
        "lokale kalenderdag (82.800, 86.400 of 90.000) voor d, de werkelijke lokale kalendermaand voor m.",
        "granulariteit__cat": "Wat de bronwaarde was: kwartier_totaal, uur_totaal, dag_totaal of "
        "maand_gemiddeld_per_dag (een m-rij is het gemiddelde dagverbruik van die maand, geen maandtotaal).",
        "e_net__W": "Gemiddeld netto elektrisch vermogen over het interval (bron: elec in kWh, maal "
        "3.600.000 en gedeeld door interval_duur__s, voor m-rijen door 86.400). Negatief is teruglevering.",
    },
    "weer": {
        "weerstation_nr": "KNMI-stationscode; koppelt aan homes.weerstation_nr.",
        "tijdstip": "Begin van het uur waarover de KNMI-waarde gaat, tz-aware Europe/Amsterdam.",
        "temp_buiten__degC": "Buitentemperatuur (KNMI-uurwaarde T, maal 0,1).",
        "wind__m_s_1": "Windsnelheid (KNMI-uurwaarde FH, maal 0,1).",
        "ghi__W_m_2": "Globale horizontale instraling, gemiddeld over het uur (KNMI-uurwaarde Q in "
        "J/cm2, omgerekend naar W/m2).",
        "bron__cat": "Herkomst: eigen_ingest (rauwe stationswaarde, standaard) of "
        "eigen_ingest_geointerpoleerd (alleen bij --weer-geointerpoleerd-diagnose). De door RVO "
        "meegeleverde reeks staat hier bewust niet in.",
    },
    "quality": {
        "home_id__str": "Woningsleutel, zie homes.home_id__str.",
        "tijdstip_start": "Zelfde waarde als in de bijbehorende measurements-rij.",
        "interval_type__cat": "Zelfde waarde als in de bijbehorende measurements-rij.",
        "e_net_ontbrekend__flag": "True als e_net__W leeg (NaN) is. Een 0 telt als waarde, niet als ontbrekend.",
        "g_gebruik_ontbrekend__flag": "True als g_gebruik__m3_s_1 leeg (NaN) is: geen gasmeting op "
        "deze rij (q-rijen hebben in de bron nooit gas) of een woning zonder gaskolom.",
        "g_gebruik_negatief__flag": "True als g_gebruik__m3_s_1 < 0, False als >= 0, leeg als "
        "g_gebruik__m3_s_1 leeg is. Informatief, geen filter.",
        "e_net_constante_reeks__flag": "True als e_net__W over de HELE reeks van deze (woning, "
        "interval_type) nooit varieert (standaarddeviatie exact 0, minstens 2 niet-lege waarden); "
        "leeg waar e_net__W leeg is.",
        "g_gebruik_constante_reeks__flag": "Zelfde regel als e_net_constante_reeks__flag, op "
        "g_gebruik__m3_s_1.",
        "e_net_uitschieter__flag": "True als |e_net__W - gemiddelde| > 3 x standaarddeviatie, beide "
        "over dezelfde (woning, interval_type); leeg als e_net__W leeg is of die standaarddeviatie "
        "0 of onbepaald is. Voorlopige drempel, informatief.",
        "g_gebruik_uitschieter__flag": "Zelfde regel als e_net_uitschieter__flag, op g_gebruik__m3_s_1.",
    },
    "derived": {
        "home_id__str": "Woningsleutel, zie homes.home_id__str.",
        "tijdstip_start": "Zelfde waarde als in de bijbehorende measurements-rij.",
        "interval_type__cat": "Zelfde waarde als in de bijbehorende measurements-rij.",
        "g_gebruik__m3_s_1": "Gemiddelde gasvolumestroom over het interval (bron: gas in m3, gedeeld "
        "door interval_duur__s, voor m-rijen door 86.400). Leeg waar de bron geen gaswaarde heeft.",
        "g_gebruik__W": "Gasvermogen op basis van de bovenwaarde: g_gebruik__m3_s_1 x "
        "actual_gas_std_hhv__J_m_3.",
        "actual_gas_std_hhv__J_m_3": "Toegepaste calorische bovenwaarde van gas: landelijk gemiddelde "
        "per uur van mijnenergiedata.nl, gekoppeld zoals het weer; anders de vaste 35,17 MJ/m3.",
        "gas_hhv_bron__cat": "Herkomst van actual_gas_std_hhv__J_m_3: mijnenergiedata_actueel of "
        "vast_gemiddelde_fallback.",
        "weerkoppeling_methode__cat": "Hoe het weer aan deze rij is gekoppeld: punt_interpolatie (q, "
        "lineair tussen de omliggende uren), punt_uur (h, exacte match), gemiddelde_dag (d), "
        "gemiddelde_maand (m), of ontbrekend_buiten_archief als er geen weerwaarde was.",
        "temp_buiten__degC": "Buitentemperatuur uit weer.parquet (bron eigen_ingest), gekoppeld volgens "
        "weerkoppeling_methode__cat.",
        "wind__m_s_1": "Windsnelheid uit weer.parquet (bron eigen_ingest), gekoppeld volgens "
        "weerkoppeling_methode__cat.",
        "ghi__W_m_2": "Instraling uit weer.parquet (bron eigen_ingest), gekoppeld volgens "
        "weerkoppeling_methode__cat.",
    },
}

_TAG_BRON = {
    **{kolom: "Verwarmingssysteem" for kolom in tabellen.VERWARMINGSSYSTEEM_TAGS.values()},
    **{kolom: "Afgiftesysteem" for kolom in tabellen.AFGIFTESYSTEEM_TAGS.values()},
}

_SLEUTEL_MEETRIJ = ["home_id__str", "tijdstip_start", "interval_type__cat"]

_PRIMARY_KEYS: dict[str, list[str]] = {
    "homes": ["home_id__str"],
    "measurements": _SLEUTEL_MEETRIJ,
    "weer": ["weerstation_nr", "tijdstip", "bron__cat"],
    "quality": _SLEUTEL_MEETRIJ,
    "derived": _SLEUTEL_MEETRIJ,
}

_FOREIGN_KEYS: dict[str, list[dict]] = {
    "measurements": [
        {"fields": ["home_id__str"], "reference": {"resource": "homes", "fields": ["home_id__str"]}},
    ],
    "quality": [
        {"fields": _SLEUTEL_MEETRIJ, "reference": {"resource": "measurements", "fields": _SLEUTEL_MEETRIJ}},
    ],
    "derived": [
        {"fields": _SLEUTEL_MEETRIJ, "reference": {"resource": "measurements", "fields": _SLEUTEL_MEETRIJ}},
    ],
}

_RESOURCE_TITELS: dict[str, str] = {
    "homes": "Eén rij per woning: de 18 statische kenmerken uit de metadata, gestandaardiseerd",
    "measurements": "Elektriciteit per woning en interval (q/h/d/m), als gemiddeld vermogen",
    "weer": "Eigen KNMI-uurreeks per weerstation",
    "quality": "Kwaliteitsvlaggen per measurements-rij",
    "derived": "Gas (volumestroom, vermogen, calorische waarde) en gekoppeld weer per measurements-rij",
}


def _veld(schema_veld: pa.Field, resourcenaam: str) -> dict:
    veld: dict = {"name": schema_veld.name, "type": table_schema_type(schema_veld.type)}
    if veld["type"] == "datetime":
        veld["format"] = "default"  # ISO 8601; tz-aware Europe/Amsterdam, zie tabellen.TIJDSTIP
    beschrijving = VELD_BESCHRIJVINGEN.get(resourcenaam, {}).get(schema_veld.name)
    if beschrijving is None and schema_veld.name in _TAG_BRON:
        beschrijving = _HOMES_TAG_BESCHRIJVING.format(bron=_TAG_BRON[schema_veld.name])
    veld["description"] = beschrijving or "Zie docs/datacatalogus.md voor de beschrijving van dit veld."

    constraints: dict = {}
    if not schema_veld.nullable:
        constraints["required"] = True
    if schema_veld.name in tabellen.VASTE_WAARDEN:
        constraints["enum"] = tabellen.VASTE_WAARDEN[schema_veld.name]
    if constraints:
        veld["constraints"] = constraints
    return veld


def _resource(naam: str, schema: pa.Schema) -> dict:
    table_schema: dict = {
        "fields": [_veld(f, naam) for f in schema],
        "missingValues": [""],
        "primaryKey": _PRIMARY_KEYS[naam],
    }
    if naam in _FOREIGN_KEYS:
        table_schema["foreignKeys"] = _FOREIGN_KEYS[naam]
    return {
        "name": naam,
        "title": _RESOURCE_TITELS[naam],
        "format": "parquet",
        "mediatype": "application/vnd.apache.parquet",
        "path": f"{naam}.parquet",
        "schema": table_schema,
    }


def bouw_datapackage() -> dict:
    """Bouw het datapackage-object (een gewone ``dict``, direct naar JSON te schrijven)."""
    resources = [_resource(naam, schema) for naam, schema in tabellen.SCHEMAS.items()]

    return {
        "name": "installatiemonitor-3-processed",
        "title": "Installatiemonitor 3.0: voorbewerkte slimme-meterdata (getypeerde Parquet-tabellen)",
        "description": (
            "Voorbewerkte slimme-meterdata, woningkenmerken en weer van de 6.283 woningen met een "
            "warmtepomp in de RVO/KITE-dataset Installatiemonitor 3.0. Deze repo is niet de "
            "data-eigenaar; zie GEBRUIKSVOORWAARDEN.md voor de voorwaarden en voor hoe je de dataset "
            "zelf verkrijgt, en docs/datacatalogus.md voor de volledige beschrijving van elke tabel. "
            "Paden zijn relatief aan de uitvoermap van de pipeline (standaard data/processed/). "
            "Gegenereerd door im3_preprocessing.datapackage, niet met de hand bijgehouden."
        ),
        "version": __version__,
        "licenses": [
            {
                "name": "andere",
                "title": (
                    "Geen open licentie. RVO stelt de dataset beschikbaar voor onderzoek en analyses "
                    "met een maatschappelijk doel; gebruik moet gemeld worden bij KITE en uitkomsten "
                    "moeten onder dezelfde voorwaarden gedeeld worden met de KITE-community. De data "
                    "is niet vrij herverspreidbaar, ook niet in deze voorbewerkte vorm. Zie "
                    "GEBRUIKSVOORWAARDEN.md in deze repo."
                ),
                "path": "GEBRUIKSVOORWAARDEN.md",
            }
        ],
        "sources": [
            {
                "title": "Installatiemonitor (ledenversie), KITE (Kennis- en Dataplatform Individuele "
                f"Technieken), RVO: {DATASET_BESTANDSNAAM}; alleen voor ingelogde leden, zie "
                "GEBRUIKSVOORWAARDEN.md",
                "path": KITE_PAGINA_URL,
            },
            {
                "title": f"RVO, Installatiemonitor Dataset: omschrijving gebruiksvoorwaarden en "
                f"toelichting op dataset, versie 1.0, 20 augustus 2026 ({INFORMATIEDOCUMENT_BESTANDSNAAM}, "
                f"bijgeleverd in {DATASET_BESTANDSNAAM})",
            },
            {
                "title": "Poiesz, Janssen, Biemans, Wagener & Hommelberg, Installatiemonitor 3.0: de "
                "warmtepomp in de gebouwde omgeving, eindrapportage v1.02, 15 juni 2026",
                "path": EINDRAPPORT_URL,
            },
            {
                "title": "KNMI-uurgegevens van de 28 weerstations, opgehaald met "
                "needforheat-dutch-weather-software",
                "path": "https://github.com/energietransitie/needforheat-dutch-weather-software",
            },
            {
                "title": "Calorische gaswaarden per uur, mijnenergiedata.nl (niet publiek gedocumenteerde API)",
                "path": "https://www.mijnenergiedata.nl/calorische-gaswaarden/",
            },
        ],
        "contributors": [
            {"title": "Rijksdienst voor Ondernemend Nederland (RVO), KITE", "role": "publisher"},
            {
                "title": "BDH, haalde als ODA de slimme-meterdata op (RVO-informatiedocument p. 2; "
                "eindrapportage §2.1)",
                "role": "contributor",
            },
            {"title": "Kenniscentrum Duurzaam Leven (deze voorbewerking)", "role": "wrangler"},
        ],
        "resources": resources,
    }


def schrijf_datapackage(pad: Path) -> None:
    """Schrijf ``datapackage.json`` atomisch naar ``pad`` (``<pad>.tmp`` + hernoeming, zoals
    ``chunking.schrijf_json_atomisch``)."""
    pakket = bouw_datapackage()
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.write_text(json.dumps(pakket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pad)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--pad",
        type=Path,
        default=Path(DATAPACKAGE_BESTANDSNAAM),
        help="Waar datapackage.json geschreven wordt (standaard: datapackage.json in de huidige map, "
        "dus de repo-root als je het vanuit de repo-root draait).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    schrijf_datapackage(args.pad)
    print(f"Geschreven: {args.pad}")


if __name__ == "__main__":
    main()
