# SPDX-License-Identifier: EUPL-1.2
"""De vijf uitvoertabellen als expliciete ``pyarrow``-schema's: de bron van waarheid voor de
machineleesbare beschrijving (``datapackage.py``) en voor ``docs/datacatalogus.md``.

**Waarom deze module er is.** De pipeline bouwt haar tabellen als pandas-DataFrames en laat
``pyarrow`` het Parquet-schema daaruit afleiden (``to_parquet``/``ParquetWriter``); een expliciet
schema stond tot nu toe nergens. Om ``datapackage.json`` uit de code te kunnen genereren in plaats
van het met de hand bij te houden, staat hier per tabel precies welke kolommen er in welke volgorde
en met welk type uitkomen. Waar de code al een lijst of constante heeft, wordt die hergebruikt
(``io.VERWARMINGSSYSTEEM_TAGS``, ``weer.WEER_KOLOMMEN``, ``weer.WEERVELDEN``, ``gaskwaliteit.KOLOM``,
``dtypes.VASTE_CATEGORIEEN``), zodat een wijziging daar hier vanzelf doorwerkt.

**Borging dat dit niet uit de pas loopt met wat de pipeline werkelijk schrijft.**
``tests/test_datapackage.py`` draait de echte pipeline (``pipeline.run``, met een nagebootste
KNMI-reeks in plaats van de netwerkophaal) op een kleine synthetische dataset en vergelijkt de
schema's van de geschreven Parquet-bestanden met ``SCHEMAS``: kolomnamen, volgorde en logisch type.
Daarnaast vergelijkt een tweede test ``SCHEMAS`` met de footers van de echte volledige-run-uitvoer
in ``data/processed/``, als die op de machine staat.

**Types.** Zoals de pipeline ze schrijft, met twee kanttekeningen die de vergelijking in de test
bewust negeert: een ``__cat``-kolom is een Parquet-dictionary waarvan pandas de breedte van de index
zelf kiest (``int8`` of ``int16``, afhankelijk van het aantal categorieën), en een tekstkolom is
``string`` of ``large_string`` afhankelijk van de pandas-versie. Beide zijn voor een lezer
hetzelfde.

**Nullability.** ``nullable=False`` staat alleen bij een kolom die volgens de code nooit leeg kan
zijn (een sleutel, een plain ``bool``/``int`` die met ``astype`` is gemaakt, een kolom die de code
exhaustief vult). Parquet-bestanden uit pandas markeren elke kolom als nullable, dus dit is
documentatie van de code, geen eigenschap die uit de footer te lezen is.
"""

from __future__ import annotations

import pyarrow as pa

from . import gaskwaliteit, weer
from .dtypes import VASTE_CATEGORIEEN
from .io import AFGIFTESYSTEEM_TAGS, VERWARMINGSSYSTEEM_TAGS
from .timestamps import TZ_LOKAAL

#: Tijdkolom van de meet-, kwaliteits-, afgeleide en weertabel: tz-aware, weergavezone
#: Europe/Amsterdam (ontwerp-preprocessing.md §12.10), nanosecondenresolutie (§12.14).
TIJDSTIP = pa.timestamp("ns", tz=TZ_LOKAAL)
#: ``homes.installatiedatum_wp``: microsecondenresolutie, zoals ``pd.to_datetime(format="%Y-%m")``
#: die onder pandas 3 levert. Dat komt goed uit, want de bron bevat installatiejaren buiten het
#: ns-bereik (1677-2262), zie docs/datacatalogus.md §8.
INSTALLATIEDATUM = pa.timestamp("us", tz=TZ_LOKAAL)
CATEGORIE = pa.dictionary(pa.int8(), pa.string())
TEKST = pa.string()


def _verplicht(naam: str, type_: pa.DataType) -> pa.Field:
    return pa.field(naam, type_, nullable=False)


def _optioneel(naam: str, type_: pa.DataType) -> pa.Field:
    return pa.field(naam, type_, nullable=True)


HOMES_SCHEMA = pa.schema(
    [
        _verplicht("home_id__str", TEKST),
        _optioneel("installatiedatum_wp", INSTALLATIEDATUM),
        _verplicht("heeft_thermostaat__bool", pa.bool_()),
        _verplicht("temp_dag_ingesteld__degC", pa.int8()),
        _verplicht("temp_nacht_ingesteld__degC", pa.int8()),
        _verplicht("kookt_op_gas__bool", pa.bool_()),
        _verplicht("weerstation_nr", pa.int16()),
        _optioneel("weerstation_naam__cat", CATEGORIE),
        _optioneel("vloeroppervlak_bin__cat", CATEGORIE),
        _verplicht("heeft_ev_opgegeven__bool", pa.bool_()),
        _optioneel("isde_vermogen__kW", pa.int8()),
        _verplicht("isde_vermogen_onbekend__bool", pa.bool_()),
        _optioneel("verwarmingssysteem_ruw__cat", CATEGORIE),
        *[_verplicht(kolom, pa.bool_()) for kolom in VERWARMINGSSYSTEEM_TAGS.values()],
        _optioneel("afgiftesysteem_ruw__cat", CATEGORIE),
        *[_verplicht(kolom, pa.bool_()) for kolom in AFGIFTESYSTEEM_TAGS.values()],
        _verplicht("woningtype_bron_afgekapt__bool", pa.bool_()),
        _optioneel("woningtype__cat", CATEGORIE),
        _optioneel("type_glas__cat", CATEGORIE),
        _optioneel("muurisolatie_type__cat", CATEGORIE),
        _optioneel("vloerisolatie__cat", CATEGORIE),
        _optioneel("dakisolatie_type__cat", CATEGORIE),
    ]
)

#: Kolomvolgorde gelijk aan ``pipeline.MEASUREMENTS_OUTPUT_KOLOMMEN`` (test borgt dat).
MEASUREMENTS_SCHEMA = pa.schema(
    [
        _verplicht("home_id__str", TEKST),
        _verplicht("tijdstip_start", TIJDSTIP),
        _verplicht("interval_type__cat", CATEGORIE),
        _verplicht("interval_duur__s", pa.int32()),
        _verplicht("granulariteit__cat", CATEGORIE),
        _optioneel("e_net__W", pa.float32()),
    ]
)

_WEER_TYPES: dict[str, pa.Field] = {
    "weerstation_nr": _verplicht("weerstation_nr", pa.int16()),
    "tijdstip": _verplicht("tijdstip", TIJDSTIP),
    **{veld: _optioneel(veld, pa.float32()) for veld in weer.WEERVELDEN},
    "bron__cat": _verplicht("bron__cat", CATEGORIE),
}
#: Kolomvolgorde volgt ``weer.WEER_KOLOMMEN``; een kolom die daar bijkomt zonder hier een type te
#: krijgen, geeft bij het importeren een ``KeyError`` in plaats van een stil ontbrekend veld.
WEER_SCHEMA = pa.schema([_WEER_TYPES[kolom] for kolom in weer.WEER_KOLOMMEN])

#: De zeven vlagkolommen, in de volgorde waarin ``cleaning.build_quality_table`` ze aanmaakt. De
#: twee ``*_ontbrekend__flag``-vlaggen zijn plain ``bool`` (nooit onbepaald), de overige nullable
#: ``boolean``; zie docs/datacatalogus.md §6.1 voor de exacte regel per vlag.
QUALITY_VLAGGEN: tuple[str, ...] = (
    "e_net_ontbrekend__flag",
    "g_gebruik_ontbrekend__flag",
    "g_gebruik_negatief__flag",
    "e_net_constante_reeks__flag",
    "g_gebruik_constante_reeks__flag",
    "e_net_uitschieter__flag",
    "g_gebruik_uitschieter__flag",
)
_ALTIJD_BEPAALD = {"e_net_ontbrekend__flag", "g_gebruik_ontbrekend__flag"}

QUALITY_SCHEMA = pa.schema(
    [
        _verplicht("home_id__str", TEKST),
        _verplicht("tijdstip_start", TIJDSTIP),
        _verplicht("interval_type__cat", CATEGORIE),
        *[
            _verplicht(vlag, pa.bool_()) if vlag in _ALTIJD_BEPAALD else _optioneel(vlag, pa.bool_())
            for vlag in QUALITY_VLAGGEN
        ],
    ]
)

#: De derived-kolommen in de volgorde van ``pipeline._verwerk_chunk``. De laatste vier (koppelmethode
#: en de drie weervelden) ontbreken in een run met ``--skip-weer``; ``datapackage.json`` beschrijft de
#: volledige run, met eigen KNMI-ingest.
DERIVED_SCHEMA = pa.schema(
    [
        _verplicht("home_id__str", TEKST),
        _verplicht("tijdstip_start", TIJDSTIP),
        _verplicht("interval_type__cat", CATEGORIE),
        _optioneel("g_gebruik__m3_s_1", pa.float32()),
        _optioneel("g_gebruik__W", pa.float32()),
        _verplicht(gaskwaliteit.KOLOM, pa.float32()),
        _verplicht("gas_hhv_bron__cat", CATEGORIE),
        _verplicht("weerkoppeling_methode__cat", CATEGORIE),
        *[_optioneel(veld, pa.float32()) for veld in weer.WEERVELDEN],
    ]
)

#: Alle uitvoertabellen, in de volgorde van de datacatalogus. De sleutel is de bestandsnaam zonder
#: ``.parquet`` in de uitvoermap (standaard ``data/processed/``).
SCHEMAS: dict[str, pa.Schema] = {
    "homes": HOMES_SCHEMA,
    "measurements": MEASUREMENTS_SCHEMA,
    "weer": WEER_SCHEMA,
    "quality": QUALITY_SCHEMA,
    "derived": DERIVED_SCHEMA,
}

#: Vaste categorieënlijst per ``__cat``-kolom, rechtstreeks uit ``dtypes.py``; kolommen die daar
#: niet in staan (de ``homes``-categorieën) hebben een open waardenverzameling uit de bron.
VASTE_WAARDEN: dict[str, list[str]] = {
    kolom: [str(c) for c in dtype.categories] for kolom, dtype in VASTE_CATEGORIEEN.items()
}
