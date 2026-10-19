# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.io: schema-validatie en homes-standaardisatie."""

from pathlib import Path

import pandas as pd
import pytest

from im3_preprocessing import io as im3io


def test_home_id_from_path():
    assert im3io.home_id_from_path(Path("IM_customer_1000.csv")) == "1000"


def test_home_id_from_path_onverwacht_formaat():
    with pytest.raises(im3io.SchemaError):
        im3io.home_id_from_path(Path("iets_anders.csv"))


def test_read_customer_file_ontbrekende_kolom(tmp_path):
    pad = tmp_path / "IM_customer_1.csv"
    pad.write_text("datetime,elec,interval,gas,wind,temp\n2023-01-01,1.0,d,1.0,,\n")
    with pytest.raises(im3io.SchemaError, match="ontbrekende kolommen"):
        im3io.read_customer_file(pad)


def test_read_customer_file_onbekend_interval(tmp_path):
    pad = tmp_path / "IM_customer_1.csv"
    pad.write_text(
        "datetime,elec,interval,gas,wind,temp,sun\n2023-01-01,1.0,x,1.0,,,\n"
    )
    with pytest.raises(im3io.SchemaError, match="onbekende interval-waarden"):
        im3io.read_customer_file(pad)


def test_read_customer_file_ok(tmp_path):
    pad = tmp_path / "IM_customer_42.csv"
    pad.write_text(
        "datetime,elec,interval,gas,wind,temp,sun\n"
        "2023-03-01 00:15:00+00:00,0.4,q,,,,\n"
        "2023-03-01 01:00:00+00:00,1.5,h,0.01,1.0,-4.3,0.0\n"
    )
    cf = im3io.read_customer_file(pad)
    assert cf.home_id__str == "42"
    assert (cf.df["home_id__str"] == "42").all()
    assert cf.issues == []


def test_read_customer_file_zonder_gaskolom_all_electric(tmp_path):
    # All-electric woningen hebben in de bron geen `gas`-kolom (geen gasaansluiting) i.p.v. een
    # kolom met NaN/0. Geen schemadefect, wel signaleren en met NaN aanvullen (niet met 0).
    pad = tmp_path / "IM_customer_1011.csv"
    pad.write_text(
        "datetime,elec,interval,wind,temp,sun\n"
        "2023-01-30,21.0,d,,,\n"
    )
    cf = im3io.read_customer_file(pad)
    assert "gas" in cf.df.columns
    assert cf.df["gas"].isna().all()
    assert any("gas" in issue for issue in cf.issues)


def test_read_customer_file_signaleert_weer_buiten_h(tmp_path):
    pad = tmp_path / "IM_customer_42.csv"
    pad.write_text(
        "datetime,elec,interval,gas,wind,temp,sun\n"
        "2023-01-01,1.0,d,1.0,3.0,,\n"  # weer op een d-rij: informationeel, geen harde fout
    )
    cf = im3io.read_customer_file(pad)
    assert any("niet-h-rijen" in issue for issue in cf.issues)


def test_read_homes_metadata_woningtype_herstel(tmp_path):
    meta = tmp_path / "meta.csv"
    kolommen = (
        "Customer_id,Installatiedatum_hp,Heeft_thermosstaat,Dag_temperatuur,Nacht_temperatuur,"
        "Koken_op_gas,Weerstation_nr,Weerstation naam,Vloer_oppervlak,EV_opgegeven,"
        "ISDE vermogen,Verwarmingssysteem,Afgiftesysteem,Woningtype,Type_glas,Isolatie_type,"
        "Vloer_isolatie_type,Dak_isolatie_type\n"
    )
    eenheden = ",jaar - maand,1=ja; 0=nee,deg C,deg C,1=ja; 0=nee,KNMI code,-,bin m2,1=ja; 0=nee,kW (-1=onbekend),-,-,-,-,-,-,-\n"
    rij_tussen = '1,2022-01,1,20,18,0,290,Twenthe,100-109,0,-1,"Hybride warmtepomp","Radiatoren","Rijwoning (tussen","Dubbel glas","Weet niet","Ja","Weet niet"\n'
    rij_hoek = '2,2022-01,1,20,18,0,290,Twenthe,100-109,0,5,"HR-ketel","Radiatoren","Rijwoning (hoek","Dubbel glas","Weet niet","Ja","Weet niet"\n'
    meta.write_text(kolommen + eenheden + rij_tussen + rij_hoek)

    homes = im3io.read_homes_metadata(meta)

    assert homes.loc[0, "woningtype__cat"] == "Rijwoning (tussenwoning)"
    assert homes.loc[1, "woningtype__cat"] == "Rijwoning (hoekwoning)"
    assert homes["woningtype_bron_afgekapt__bool"].all()
    # ISDE-sentinel -1 -> NaN + vlag
    assert pd.isna(homes.loc[0, "isde_vermogen__kW"])
    assert homes.loc[0, "isde_vermogen_onbekend__bool"]
    assert homes.loc[1, "isde_vermogen__kW"] == 5.0
    assert not homes.loc[1, "isde_vermogen_onbekend__bool"]
    # multi-select -> booleans
    assert homes.loc[0, "heeft_hybride_wp__bool"]
    assert not homes.loc[0, "heeft_hr_ketel__bool"]
    assert homes.loc[1, "heeft_hr_ketel__bool"]


def test_read_homes_metadata_onbekend_token_geeft_fout(tmp_path):
    meta = tmp_path / "meta.csv"
    kolommen = (
        "Customer_id,Installatiedatum_hp,Heeft_thermosstaat,Dag_temperatuur,Nacht_temperatuur,"
        "Koken_op_gas,Weerstation_nr,Weerstation naam,Vloer_oppervlak,EV_opgegeven,"
        "ISDE vermogen,Verwarmingssysteem,Afgiftesysteem,Woningtype,Type_glas,Isolatie_type,"
        "Vloer_isolatie_type,Dak_isolatie_type\n"
    )
    eenheden = ",jaar - maand,1=ja; 0=nee,deg C,deg C,1=ja; 0=nee,KNMI code,-,bin m2,1=ja; 0=nee,kW (-1=onbekend),-,-,-,-,-,-,-\n"
    rij = '1,2022-01,1,20,18,0,290,Twenthe,100-109,0,5,"Iets nieuws","Radiatoren","Vrijstaand","Dubbel glas","Weet niet","Ja","Weet niet"\n'
    meta.write_text(kolommen + eenheden + rij)

    with pytest.raises(im3io.SchemaError, match="Onbekend token"):
        im3io.read_homes_metadata(meta)
