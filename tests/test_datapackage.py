# SPDX-License-Identifier: EUPL-1.2
"""datapackage.json wordt UIT DE CODE gebouwd (datapackage.py, uit tabellen.SCHEMAS); deze tests
bewaken dat het op drie plekken niet uit de pas kan lopen:

1. schema en datapackage: elk veld in een schema staat in het bijbehorende datapackage-resource, en
   omgekeerd (dezelfde aanpak als de WarmingUP- en DACS-HW-preprocessing);
2. schema en werkelijkheid: de echte pipeline (``pipeline.run``) schrijft op een kleine synthetische
   dataset precies de kolommen van ``tabellen.SCHEMAS``, en, als de volledige-run-uitvoer op deze
   machine staat, hebben ook die Parquet-footers precies die kolommen;
3. code en het gecommitte bestand: ``datapackage.json`` in de repo-root is gelijk aan wat
   ``bouw_datapackage()`` nu oplevert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from im3_preprocessing import bron as bron_mod
from im3_preprocessing import datapackage, tabellen
from im3_preprocessing import weer as weer_mod
from im3_preprocessing.dtypes import pas_vaste_categorieen_toe
from tests.test_bron import META_CSV

REPO_ROOT = Path(__file__).resolve().parents[1]
VOLLEDIGE_UITVOER = REPO_ROOT / "data" / "processed"

# Woning 1 met gas, woning 2 zonder gaskolom (all-electric, ontwerp §12.1); samen alle vier de
# intervaltypen, zodat elke vlag en elke koppelmethode minstens één keer langskomt.
KLANT_CSV_MET_GAS = (
    "datetime,elec,interval,gas,wind,temp,sun\n"
    "2023-01-31,20.5,m,3.0,,,\n"
    "2023-02-27,12.5,d,3.1,,,\n"
    "2023-02-28,11.0,d,2.9,,,\n"
    "2023-03-01 00:15:00+00:00,0.4,q,,,,\n"
    "2023-03-01 00:30:00+00:00,0.5,q,,,,\n"
    "2023-03-01 01:00:00+00:00,1.6,h,0.2,4.0,7.5,0.1\n"
    "2023-03-01 02:00:00+00:00,1.2,h,0.1,3.0,7.0,0.0\n"
)
KLANT_CSV_ZONDER_GAS = (
    "datetime,elec,interval,wind,temp,sun\n"
    "2023-01-31,8.0,m,,,\n"
    "2023-02-28,7.5,d,,,\n"
    "2023-03-01 00:15:00+00:00,-0.2,q,,,\n"
    "2023-03-01 01:00:00+00:00,0.3,h,4.0,7.5,0.1\n"
)


def _logisch_type(arrow_type: pa.DataType) -> tuple:
    """Vergelijkingsvorm van een Arrow-type, ongevoelig voor wat voor een lezer niet uitmaakt: de
    indexbreedte van een dictionary, ``string`` tegenover ``large_string`` (pandas-versie), en de
    tijdresolutie; wel gevoelig voor het Table Schema-type, de bitbreedte van getallen en de tijdzone.
    """
    if pa.types.is_dictionary(arrow_type):
        return ("categorie", datapackage.table_schema_type(arrow_type.value_type))
    if pa.types.is_timestamp(arrow_type):
        return ("tijdstip", arrow_type.tz)
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return ("tekst",)
    return (str(arrow_type),)


def _vergelijk_met_schema(naam: str, geschreven: pa.Schema) -> None:
    verwacht = tabellen.SCHEMAS[naam]
    assert geschreven.names == verwacht.names, (
        f"{naam}: kolommen wijken af van tabellen.SCHEMAS.\n"
        f"alleen geschreven: {set(geschreven.names) - set(verwacht.names)}\n"
        f"alleen in schema: {set(verwacht.names) - set(geschreven.names)}"
    )
    for veld in verwacht:
        assert _logisch_type(geschreven.field(veld.name).type) == _logisch_type(veld.type), (
            f"{naam}.{veld.name}: geschreven als {geschreven.field(veld.name).type}, "
            f"tabellen.SCHEMAS zegt {veld.type}"
        )


# --- 1. schema en datapackage ---------------------------------------------------------------


def test_datapackage_bouwt_zonder_fouten():
    pakket = datapackage.bouw_datapackage()
    assert pakket["resources"]
    json.dumps(pakket)  # moet JSON-serialiseerbaar zijn


def test_elke_resource_heeft_precies_de_velden_van_zijn_schema():
    pakket = datapackage.bouw_datapackage()
    resources = {r["name"]: r for r in pakket["resources"]}
    assert set(resources) == set(tabellen.SCHEMAS)

    for naam, schema in tabellen.SCHEMAS.items():
        schema_velden = schema.names
        package_velden = [v["name"] for v in resources[naam]["schema"]["fields"]]
        assert schema_velden == package_velden, (
            f"{naam}: schema en datapackage lopen uit de pas.\n"
            f"alleen in schema: {set(schema_velden) - set(package_velden)}\n"
            f"alleen in datapackage: {set(package_velden) - set(schema_velden)}"
        )


def test_elk_veld_heeft_een_eigen_beschrijving():
    """Geen enkel veld mag op de generieke terugvaltekst uitkomen: dan ontbreekt er een beschrijving
    in datapackage.VELD_BESCHRIJVINGEN."""
    pakket = datapackage.bouw_datapackage()
    for resource in pakket["resources"]:
        for veld in resource["schema"]["fields"]:
            assert veld.get("description"), f"{resource['name']}.{veld['name']} heeft geen description"
            assert not veld["description"].startswith("Zie docs/datacatalogus.md"), (
                f"{resource['name']}.{veld['name']} heeft alleen de generieke beschrijving"
            )


def test_geen_beschrijving_voor_een_veld_dat_niet_bestaat():
    for naam, beschrijvingen in datapackage.VELD_BESCHRIJVINGEN.items():
        onbekend = set(beschrijvingen) - set(tabellen.SCHEMAS[naam].names)
        assert not onbekend, f"{naam}: beschrijving voor niet-bestaande kolom(men) {onbekend}"


def test_primaire_en_vreemde_sleutels_verwijzen_naar_bestaande_velden():
    pakket = datapackage.bouw_datapackage()
    resources = {r["name"]: r for r in pakket["resources"]}
    for naam, resource in resources.items():
        velden = {v["name"] for v in resource["schema"]["fields"]}
        assert resource["schema"]["primaryKey"], f"{naam} heeft geen primaryKey"
        assert set(resource["schema"]["primaryKey"]) <= velden
        for fk in resource["schema"].get("foreignKeys", []):
            assert set(fk["fields"]) <= velden
            doel = resources[fk["reference"]["resource"]]
            assert fk["reference"]["fields"] == doel["schema"]["primaryKey"]


def test_vaste_categorieen_komen_als_enum_in_het_datapackage():
    pakket = datapackage.bouw_datapackage()
    for resource in pakket["resources"]:
        for veld in resource["schema"]["fields"]:
            if veld["name"] in tabellen.VASTE_WAARDEN:
                assert veld["constraints"]["enum"] == tabellen.VASTE_WAARDEN[veld["name"]]


def test_measurements_schema_volgt_de_kolomlijst_van_de_pipeline():
    from im3_preprocessing.pipeline import MEASUREMENTS_OUTPUT_KOLOMMEN

    assert tabellen.SCHEMAS["measurements"].names == MEASUREMENTS_OUTPUT_KOLOMMEN


def test_licentie_verwijst_naar_gebruiksvoorwaarden_geen_open_licentienaam():
    pakket = datapackage.bouw_datapackage()
    licentie = pakket["licenses"][0]
    assert licentie["path"] == "GEBRUIKSVOORWAARDEN.md"
    assert (REPO_ROOT / licentie["path"]).is_file()
    # Geen standaard open-licentie-identifier als 'name': dat zou een licentie suggereren die er niet is.
    assert licentie["name"] not in ("cc-by-4.0", "cc0-1.0", "odbl-1.0", "mit", "pddl")


def test_version_is_de_pakketversie():
    from im3_preprocessing import __version__

    assert datapackage.bouw_datapackage()["version"] == __version__


def test_frictionless_structurele_validatie():
    """Structurele validatie (het JSON Schema-profiel van Data Package v1), zonder de Parquet-data
    zelf te lezen. Slaat zichzelf over als frictionless niet geïnstalleerd is (optionele
    dev-afhankelijkheid, zie pyproject.toml)."""
    frictionless = pytest.importorskip("frictionless")
    fouten = list(frictionless.Package.metadata_validate(datapackage.bouw_datapackage()))
    assert fouten == []


# --- 2. schema en werkelijkheid -------------------------------------------------------------


def _nagebootst_knmi(start, eind, stations, *args, **kwargs) -> pd.DataFrame:
    """Vervangt ``pipeline.build_weer_tables`` zonder netwerk, maar via dezelfde omzetting naar
    ``weer.WEER_KOLOMMEN`` als de echte ingest (``weer._naar_weer_kolommen``)."""
    uren = pd.date_range(
        start.floor("h") - pd.Timedelta(days=1), eind.ceil("h") + pd.Timedelta(days=1),
        freq="h", tz="UTC", name="timestamp",
    )
    frames = []
    for stn in stations:
        breed = pd.DataFrame(
            {"temp_buiten__degC": 5.0, "wind__m_s_1": 3.0, "ghi__W_m_2": 0.0}, index=uren
        )
        frames.append(weer_mod._naar_weer_kolommen(breed, stn, "eigen_ingest"))
    return pas_vaste_categorieen_toe(pd.concat(frames, ignore_index=True)[weer_mod.WEER_KOLOMMEN])


@pytest.fixture(scope="module")
def run_uitvoer(tmp_path_factory):
    """Eén pipeline-run voor alle tests in deze module; een run kost enkele seconden."""
    from im3_preprocessing import pipeline

    tmp_path = tmp_path_factory.mktemp("run")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / bron_mod.METADATA_BESTANDSNAAM).write_text(META_CSV, encoding="utf-8")
    (raw / "IM_customer_1.csv").write_text(KLANT_CSV_MET_GAS, encoding="utf-8")
    (raw / "IM_customer_2.csv").write_text(KLANT_CSV_ZONDER_GAS, encoding="utf-8")

    uit = tmp_path / "processed"
    pakket_pad = tmp_path / "datapackage.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "build_weer_tables", _nagebootst_knmi)
        pipeline.run(
            raw, uit, raw_bron="csv", interim_dir=tmp_path / "interim",
            fetch_eigen_weer=True, fetch_gaskwaliteit=False,
            docs_dir=None, datapackage_pad=pakket_pad,
        )
    return uit, pakket_pad


@pytest.mark.parametrize("naam", list(tabellen.SCHEMAS))
def test_pipeline_schrijft_precies_de_schemas_uit_tabellen(run_uitvoer, naam):
    uit, _ = run_uitvoer
    _vergelijk_met_schema(naam, pq.read_schema(uit / f"{naam}.parquet"))


def test_pipeline_schrijft_het_datapackage_uit_de_code(run_uitvoer):
    _, pakket_pad = run_uitvoer
    assert json.loads(pakket_pad.read_text(encoding="utf-8")) == datapackage.bouw_datapackage()


@pytest.mark.parametrize("naam", list(tabellen.SCHEMAS))
def test_schemas_kloppen_met_de_volledige_run_als_die_er_is(naam):
    """Leest alleen de Parquet-footer, niet de data. Slaat zichzelf over op een machine zonder de
    volledige-run-uitvoer (die staat nooit in git, zie GEBRUIKSVOORWAARDEN.md)."""
    pad = VOLLEDIGE_UITVOER / f"{naam}.parquet"
    if not pad.is_file():
        pytest.skip(f"{pad} niet aanwezig")
    _vergelijk_met_schema(naam, pq.read_schema(pad))


# --- 3. code en het gecommitte bestand ------------------------------------------------------


def test_datapackage_in_de_repo_root_is_actueel():
    pad = REPO_ROOT / datapackage.DATAPACKAGE_BESTANDSNAAM
    assert pad.is_file(), "datapackage.json ontbreekt in de repo-root"
    assert json.loads(pad.read_text(encoding="utf-8")) == datapackage.bouw_datapackage(), (
        "datapackage.json in de repo-root loopt achter op de code; regenereer met "
        "`python -m im3_preprocessing.datapackage`"
    )
