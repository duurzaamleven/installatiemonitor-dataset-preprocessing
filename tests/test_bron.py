# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.bron: uitpakken als onderdeel van de preprocessing (§12.11).

De kern van deze module is een gelijkheidsbelofte: het maakt voor de uitkomst niet uit of de ruwe
data als losse CSV's op schijf staat of nog in de zip zit. Die belofte wordt hier expliciet
getest, niet alleen "de zip is leesbaar".
"""

from __future__ import annotations

import json
import zipfile

import pandas as pd
import pytest

from im3_preprocessing import bron as bron_mod
from im3_preprocessing import io as im3io
from im3_preprocessing.timestamps import TZ_LOKAAL, resolve_timestamps

KLANT_CSV = (
    "datetime,elec,interval,gas,wind,temp,sun\n"
    "2023-01-30,12.5,d,3.0,,,\n"
    "2023-03-01 00:15:00+00:00,0.4,q,,,,\n"
    "2023-03-01 01:00:00+00:00,1.6,h,0.2,4.0,7.5,0.1\n"
    "2023-06-30 12:00:00+00:00,1.1,h,0.1,3.0,18.0,0.5\n"
)

META_CSV = (
    "Customer_id,Installatiedatum_hp,Heeft_thermosstaat,Dag_temperatuur,Nacht_temperatuur,"
    "Koken_op_gas,Weerstation_nr,Weerstation naam,Vloer_oppervlak,EV_opgegeven,ISDE vermogen,"
    "Verwarmingssysteem,Afgiftesysteem,Woningtype,Type_glas,Isolatie_type,Vloer_isolatie_type,"
    "Dak_isolatie_type\n"
    "-,-,-,degC,degC,-,-,-,m2,-,kW,-,-,-,-,-,-,-\n"
    "1,2023-01,True,20,17,False,260,De Bilt,100-150,False,5,HR-ketel,Radiatoren,"
    "Rijwoning (tussen,HR++,Spouwmuur,Vloerisolatie,Dakisolatie\n"
    "2,2023-02,False,21,18,True,240,Schiphol,50-100,True,-1,Hybride warmtepomp,Vloerverwarming,"
    "Vrijstaand,Dubbel,Geen,Geen,Geen\n"
)


@pytest.fixture
def ruwe_map(tmp_path):
    """Een map met losse CSV's, zoals na handmatig uitpakken."""
    d = tmp_path / "raw_csv"
    d.mkdir()
    (d / bron_mod.METADATA_BESTANDSNAAM).write_text(META_CSV, encoding="utf-8")
    for home_id in ("1", "2"):
        (d / f"IM_customer_{home_id}.csv").write_text(KLANT_CSV, encoding="utf-8")
    return d


@pytest.fixture
def ruwe_zip(tmp_path, ruwe_map):
    """Dezelfde inhoud, maar als zip in een verder lege map."""
    d = tmp_path / "raw_zip"
    d.mkdir()
    with zipfile.ZipFile(d / "dataset_openbaar.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for pad in sorted(ruwe_map.iterdir()):
            z.write(pad, arcname=pad.name)
    return d


def test_bestandsnaam_heen_en_weer():
    assert bron_mod.home_id_van_bestandsnaam("IM_customer_1000.csv") == "1000"
    assert bron_mod.bestandsnaam_van_home_id("1000") == "IM_customer_1000.csv"


def test_home_id_van_onverwachte_bestandsnaam():
    with pytest.raises(bron_mod.BronError):
        bron_mod.home_id_van_bestandsnaam("iets_anders.csv")


def test_maak_bron_kiest_map_zonder_zip(ruwe_map):
    assert isinstance(bron_mod.maak_bron(ruwe_map), bron_mod.MapBron)


def test_maak_bron_kiest_zip_in_map(ruwe_zip):
    assert isinstance(bron_mod.maak_bron(ruwe_zip), bron_mod.ZipBron)


def test_maak_bron_accepteert_zippad_direct(ruwe_zip):
    bron = bron_mod.maak_bron(ruwe_zip / "dataset_openbaar.zip")
    assert isinstance(bron, bron_mod.ZipBron)
    bron.sluit()


def test_maak_bron_zip_wint_van_losse_csv(tmp_path, ruwe_map):
    """Staat allebei in dezelfde map, dan is de zip de canonieke ruwe data (ontwerp §3, principe 7)."""
    with zipfile.ZipFile(ruwe_map / "dataset_openbaar.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for pad in sorted(p for p in ruwe_map.iterdir() if p.suffix == ".csv"):
            z.write(pad, arcname=pad.name)

    assert isinstance(bron_mod.maak_bron(ruwe_map), bron_mod.ZipBron)
    # ...tenzij je het expliciet anders vraagt.
    assert isinstance(bron_mod.maak_bron(ruwe_map, voorkeur="csv"), bron_mod.MapBron)


def test_maak_bron_meerdere_zips_is_een_fout(ruwe_zip):
    (ruwe_zip / "nog_een.zip").write_bytes((ruwe_zip / "dataset_openbaar.zip").read_bytes())
    with pytest.raises(bron_mod.BronError, match="Meerdere zip-bestanden"):
        bron_mod.maak_bron(ruwe_zip)


def test_maak_bron_lege_map_is_een_fout(tmp_path):
    leeg = tmp_path / "leeg"
    leeg.mkdir()
    with pytest.raises(bron_mod.BronError):
        bron_mod.maak_bron(leeg)


def test_zip_zonder_metadata_is_een_fout(tmp_path):
    pad = tmp_path / "kaal.zip"
    with zipfile.ZipFile(pad, "w") as z:
        z.writestr("IM_customer_1.csv", KLANT_CSV)
    with pytest.raises(bron_mod.BronError, match="ontbreekt in het archief"):
        bron_mod.ZipBron(pad)


def test_zip_en_map_geven_dezelfde_home_ids(ruwe_map, ruwe_zip):
    zip_bron = bron_mod.maak_bron(ruwe_zip)
    assert bron_mod.MapBron(ruwe_map).home_ids() == zip_bron.home_ids() == ["1", "2"]
    assert zip_bron.bevat("1") and not zip_bron.bevat("99")
    zip_bron.sluit()


def test_zip_en_map_geven_hetzelfde_klantbestand(ruwe_map, ruwe_zip):
    """De hele belofte van §12.11 in één assert: streamen uit de zip == lezen van schijf."""
    map_bron = bron_mod.MapBron(ruwe_map)
    zip_bron = bron_mod.maak_bron(ruwe_zip)

    with map_bron.open_klantbestand("1") as stream:
        uit_map = im3io.read_customer_stream(stream, "1")
    with zip_bron.open_klantbestand("1") as stream:
        uit_zip = im3io.read_customer_stream(stream, "1")

    pd.testing.assert_frame_equal(uit_map.df, uit_zip.df)
    assert uit_map.home_id__str == uit_zip.home_id__str == "1"
    assert uit_map.issues == uit_zip.issues
    zip_bron.sluit()


def test_zip_en_map_geven_dezelfde_homes_metadata(ruwe_map, ruwe_zip):
    zip_bron = bron_mod.maak_bron(ruwe_zip)
    with bron_mod.MapBron(ruwe_map).open_metadata() as stream:
        uit_map = im3io.read_homes_metadata(stream)
    with zip_bron.open_metadata() as stream:
        uit_zip = im3io.read_homes_metadata(stream)
    pd.testing.assert_frame_equal(uit_map, uit_zip)
    zip_bron.sluit()


def test_zip_en_map_geven_hetzelfde_tijdbereik(ruwe_map, ruwe_zip, tmp_path):
    zip_bron = bron_mod.maak_bron(ruwe_zip, cache_map=tmp_path / "interim")
    # De eerste dataregel is een `d`-rij met de KALE datum 2023-01-30. Sinds
    # ontwerp-intervalsemantiek.md §4 is de scan bewust CONSERVATIEF (§12.15-klasse fout
    # voorkomen): een kale datum wordt gelezen als de EERSTE dag van diezelfde lokale maand
    # (2023-01-01), niet als die datum zelf. Lokale middernacht 1 januari = 2022-12-31 23:00 UTC
    # (januari, CET = UTC+1).
    #
    # De laatste dataregel is een tz-aware `h`-rij (2023-06-30 12:00:00 UTC); de scan trekt hier
    # altijd de grootste mogelijke duur (3600 s, de h-duur) van af, dus 11:00 UTC.
    verwacht = (
        pd.Timestamp("2023-01-01", tz=TZ_LOKAAL).tz_convert("UTC"),
        pd.Timestamp("2023-06-30 11:00:00", tz="UTC"),
    )
    assert verwacht[0] == pd.Timestamp("2022-12-31 23:00:00", tz="UTC")
    assert bron_mod.MapBron(ruwe_map).tijdbereik(["1", "2"]) == verwacht
    assert zip_bron.tijdbereik(["1", "2"]) == verwacht
    zip_bron.sluit()


def test_tijdbereik_zonder_afsluitende_newline(tmp_path):
    """De staart-heuristiek mag niet struikelen over een bestand zonder trailing newline."""
    d = tmp_path / "raw"
    d.mkdir()
    (d / bron_mod.METADATA_BESTANDSNAAM).write_text(META_CSV, encoding="utf-8")
    (d / "IM_customer_1.csv").write_text(KLANT_CSV.rstrip("\n"), encoding="utf-8")
    assert bron_mod.MapBron(d).tijdbereik(["1"])[1] == pd.Timestamp("2023-06-30 11:00:00", tz="UTC")


def test_zip_tijdbereik_cache_wordt_hergebruikt(ruwe_zip, tmp_path):
    cache_map = tmp_path / "interim"
    bron = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    eerste = bron.tijdbereik(["1", "2"])
    cache_pad = cache_map / "tijdbereik-dataset_openbaar.json"
    assert cache_pad.exists()

    # Zonder opnieuw te scannen: een nieuwe bron op dezelfde zip leest de cache terug.
    tweede = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    assert tweede._cache_lees().keys() == {"1", "2"}
    assert tweede.tijdbereik(["1"]) == eerste  # deelselectie, dezelfde reeks
    bron.sluit()
    tweede.sluit()


def test_zip_tijdbereik_cache_vervalt_bij_gewijzigde_zip(ruwe_zip, tmp_path):
    cache_map = tmp_path / "interim"
    bron_mod.maak_bron(ruwe_zip, cache_map=cache_map).tijdbereik(["1", "2"])

    zip_pad = ruwe_zip / "dataset_openbaar.zip"
    with zipfile.ZipFile(zip_pad, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("IM_customer_3.csv", KLANT_CSV)

    opnieuw = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    assert opnieuw._cache_lees() == {}  # andere grootte/mtime -> cache genegeerd
    assert opnieuw.home_ids() == ["1", "2", "3"]
    opnieuw.sluit()


def test_kapotte_cache_leidt_niet_tot_een_fout(ruwe_zip, tmp_path):
    cache_map = tmp_path / "interim"
    cache_map.mkdir()
    (cache_map / "tijdbereik-dataset_openbaar.json").write_text("{geen json", encoding="utf-8")
    bron = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    # Kale datum -> eerste dag van diezelfde maand, zie test_zip_en_map_geven_hetzelfde_tijdbereik.
    assert bron.tijdbereik(["1"])[0] == pd.Timestamp("2023-01-01", tz=TZ_LOKAAL).tz_convert("UTC")
    bron.sluit()


def test_iter_customer_files_werkt_op_beide_bronnen(ruwe_map, ruwe_zip):
    uit_map = {cf.home_id__str: len(cf.df) for cf in im3io.iter_customer_files(ruwe_map)}
    zip_bron = bron_mod.maak_bron(ruwe_zip)
    uit_zip = {cf.home_id__str: len(cf.df) for cf in im3io.iter_customer_files(zip_bron)}
    assert uit_map == uit_zip == {"1": 4, "2": 4}
    zip_bron.sluit()


def test_pipeline_levert_identieke_output_uit_map_en_uit_zip(ruwe_map, ruwe_zip, tmp_path):
    """End-to-end: de hele pipeline op de zip geeft bit-voor-bit dezelfde tabellen.

    Dit is de test die de belofte van §12.11 echt afdekt; de losse unit-tests hierboven dekken de
    bronlaag, maar niet dat de pipeline er ook overal doorheen gaat.
    """
    from im3_preprocessing import pipeline

    uit_map = tmp_path / "uit_map"
    uit_zip = tmp_path / "uit_zip"
    gemeen = dict(
        fetch_eigen_weer=False,
        fetch_gaskwaliteit=False,
        docs_dir=None,
        datapackage_pad=None,
        interim_dir=tmp_path / "interim",
    )
    pipeline.run(ruwe_map, uit_map, raw_bron="csv", **gemeen)
    pipeline.run(ruwe_zip, uit_zip, raw_bron="zip", **gemeen)

    for naam in ("measurements", "quality", "derived", "homes"):
        pd.testing.assert_frame_equal(
            pd.read_parquet(uit_map / f"{naam}.parquet"),
            pd.read_parquet(uit_zip / f"{naam}.parquet"),
        )


def test_pipeline_uit_zip_laat_niets_uitgepakt_achter(ruwe_zip, tmp_path):
    """De zip blijft het enige ruwe bestand: er wordt niets naar schijf uitgepakt (§12.11)."""
    from im3_preprocessing import pipeline

    pipeline.run(
        ruwe_zip,
        tmp_path / "uit",
        raw_bron="zip",
        fetch_eigen_weer=False,
        fetch_gaskwaliteit=False,
        docs_dir=None,
        datapackage_pad=None,
        interim_dir=tmp_path / "interim",
    )
    assert sorted(p.name for p in ruwe_zip.iterdir()) == ["dataset_openbaar.zip"]


@pytest.mark.parametrize(
    "veld, interval",
    [
        ("2021-06-30", "m"),                     # zomertijd: UTC+2
        ("2021-12-15", "d"),                     # wintertijd: UTC+1
        ("2023-03-26", "d"),                     # dag van de voorjaarsovergang
        ("2023-10-29", "d"),                     # dag van de najaarsovergang
        ("2026-02-04 23:00:00+00:00", "q"),      # al tz-aware
        ("2026-02-04 23:00:00+00:00", "h"),
    ],
)
def test_scan_is_nooit_later_dan_de_pipeline(veld, interval):
    """§12.15 + ontwerp-intervalsemantiek.md §4: de tijdbereik-scan moet minstens zo vroeg
    resolven als resolve_timestamps, nooit later.

    De scan bepaalt de ondergrens van het venster dat voor de weer- en gaskwaliteit-ingest wordt
    opgehaald. Resolved hij structureel LATER dan de pipeline, dan begint dat venster te laat en
    krijgen de rijen in dat gat stil `ontbrekend_buiten_archief` (§12.15, de oorspronkelijke bug).

    Sinds ontwerp-intervalsemantiek.md §4 is dit GEEN exacte-gelijkheidsbelofte meer: de scan kent
    de ``interval_type``-kolom niet (leest alleen het eerste CSV-veld) en kan dus, anders dan
    resolve_timestamps, geen onderscheid maken tussen `q`/`h` (verschillende vaste duur) of `d`/`m`
    (verschillende regel). In plaats daarvan is de scan bewust CONSERVATIEF: altijd de duurste
    aftrek (`h`: 3600s) resp. de vroegste datum (`m`: 1e van de maand), dus altijd <= de
    werkelijke pipeline-uitkomst. Zie `_parse_datetime_veld` voor de onderbouwing.
    """
    uit_scan = bron_mod._parse_datetime_veld(veld)
    uit_pipeline = resolve_timestamps(pd.Series([veld]), pd.Series([interval])).iloc[0]
    assert uit_scan <= uit_pipeline


def test_tijdbereik_start_niet_later_dan_de_geresolveerde_meting(ruwe_map):
    """Integratiecheck: de venster-ondergrens mag nooit ná de vroegste echte meting liggen."""
    bron = bron_mod.MapBron(ruwe_map)
    start, _ = bron.tijdbereik(["1", "2"])

    with bron.open_klantbestand("1") as stream:
        cf = im3io.read_customer_stream(stream, "1")
    vroegste = resolve_timestamps(cf.df["datetime"], cf.df["interval"]).min()

    assert start <= vroegste, (
        f"venster begint op {start}, ná de vroegste meting {vroegste}: "
        "de rijen ertussen zouden geen weer krijgen"
    )


def test_cacheversie_maakt_een_oude_cache_ongeldig(ruwe_zip, tmp_path):
    """Een fix in de parser moet de cache ongeldig maken, niet stil genegeerd worden (§12.15)."""
    cache_map = tmp_path / "interim"
    bron = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    bron.tijdbereik(["1", "2"])
    cache_pad = cache_map / "tijdbereik-dataset_openbaar.json"

    inhoud = json.loads(cache_pad.read_text(encoding="utf-8"))
    assert inhoud["zip"]["versie"] == bron_mod.ZipBron.CACHE_VERSIE

    # Simuleer een cache van vóór de fix: zelfde zip, oudere versie.
    inhoud["zip"]["versie"] = bron_mod.ZipBron.CACHE_VERSIE - 1
    cache_pad.write_text(json.dumps(inhoud), encoding="utf-8")

    opnieuw = bron_mod.maak_bron(ruwe_zip, cache_map=cache_map)
    assert opnieuw._cache_lees() == {}, "oude cacheversie had genegeerd moeten worden"
    bron.sluit()
    opnieuw.sluit()
