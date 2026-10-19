# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.quality."""

import pandas as pd
import pytest

from im3_preprocessing.cleaning import build_quality_table
from im3_preprocessing.quality import (
    DST_TRANSITIEDATA,
    constante_reeks_flags,
    dst_dag_rij_aanwezig,
    extreme_uitschieters_rapport,
    gas_negatief_rapport,
    gas_voor_koppeling_verdacht_rapport,
    q_h_vs_dag_consistency,
    uitschieter_flags,
)
from im3_preprocessing.timestamps import local_day_window

INTERVAL_DUUR_S = {"q": 900, "h": 3600, "d": 86400, "m": 30 * 86400}


def _rij(home_id, tijdstip_start, interval_type, e_W=0.0, g_m3_s_1=0.0):
    return {
        "home_id__str": home_id,
        "tijdstip_start": pd.Timestamp(tijdstip_start),
        "interval_type__cat": interval_type,
        "interval_duur__s": INTERVAL_DUUR_S[interval_type],
        "e_net__W": e_W,
        "g_gebruik__m3_s_1": g_m3_s_1,
    }


def test_q_vs_dag_consistency_gebruikt_lokale_dagvenster_niet_utc_etmaal():
    # Sinds ontwerp-intervalsemantiek.md §1/§4 is elke rij begin-gelabeld: een kwartier van
    # interval_duur__s=900 met e_net__W=P levert energie P*900/3.6e6 kWh op. Kies P zo dat elk
    # kwartier exact 1/2/3 kWh oplevert, voor leesbare getallen.
    start, eind = local_day_window(pd.Timestamp("2023-06-15").date())
    J_PER_KWH = 3_600_000
    rijen = [
        _rij("1", start, "q", e_W=1.0 * J_PER_KWH / 900),  # eerste kwartier van de dag
        _rij("1", start + pd.Timedelta(minutes=15), "q", e_W=2.0 * J_PER_KWH / 900),
        _rij("1", eind - pd.Timedelta(minutes=15), "q", e_W=3.0 * J_PER_KWH / 900),  # laatste kwartier
        _rij("1", eind, "q", e_W=99.0 * J_PER_KWH / 900),  # eerste kwartier van de VOLGENDE dag
        _rij("1", start, "d", e_W=6.0 * J_PER_KWH / 86400),  # d-rij: hele dag, 6 kWh totaal
    ]
    df = pd.DataFrame(rijen)
    result = q_h_vs_dag_consistency(df)

    assert len(result) == 1
    r = result.iloc[0]
    assert r["n_kwartier_in_venster"] == 3
    assert r["e_som_kwartier__kWh"] == pytest.approx(6.0, abs=1e-6)
    assert r["e_dagcheck_kwartier__kWh"] == pytest.approx(0.0, abs=1e-6)


def test_dst_dag_rij_aanwezig_onderscheidt_aanwezig_en_afwezig():
    aanwezige_datum = DST_TRANSITIEDATA[0]
    afwezige_datum = DST_TRANSITIEDATA[1]
    start, _ = local_day_window(aanwezige_datum)

    df = pd.DataFrame([_rij("1", start, "d", e_W=1.0)])
    result = dst_dag_rij_aanwezig(df)

    def aanwezig(datum):
        rij = result[(result["home_id__str"] == "1") & (result["transitiedatum"] == datum)]
        return bool(rij["d_rij_aanwezig"].iloc[0])

    assert aanwezig(aanwezige_datum) is True
    assert aanwezig(afwezige_datum) is False


def test_gas_negatief_rapport():
    df = pd.DataFrame(
        [
            _rij("1", "2023-01-01", "d", g_m3_s_1=1.0),
            _rij("1", "2023-01-02", "d", g_m3_s_1=-0.5),
            _rij("2", "2023-01-01", "d", g_m3_s_1=0.2),
        ]
    )
    rapport = gas_negatief_rapport(df)
    assert rapport["n_rijen_negatief"] == 1
    assert rapport["woningen_getroffen"] == ["1"]


def test_constante_reeks_flags_hele_reeks_nooit_gevarieerd():
    tijdstippen = pd.date_range("2023-01-01", periods=10, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "h",
            "tijdstip_start": tijdstippen,
            "e_net__W": [1.0] * 10,  # nooit één keer afwijkend, over de volle reeks
        }
    )
    flags = constante_reeks_flags(df, "e_net__W")
    assert flags.all()


def test_constante_reeks_flags_negeert_tijdelijke_reeks_identieke_waarden():
    # §3 principe 4 / gebruikersfeedback: een tijdelijke reeks identieke waarden (ook niet-nul,
    # ook lang) is geen bewijs van een kapotte sensor als de reeks ELDERS wél varieert, bv. een
    # warmtepomp die een tijd op een vast minimum-modulatieniveau draait, of gewoon geen
    # gasverbruik in de zomer.
    tijdstippen = pd.date_range("2023-01-01", periods=12, freq="h", tz="UTC")
    waarden = [1.0] * 10 + [2.0, 3.0]  # lange reeks identiek, maar de reeks varieert wél ooit
    df = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "h",
            "tijdstip_start": tijdstippen,
            "g_gebruik__m3_s_1": waarden,
        }
    )
    flags = constante_reeks_flags(df, "g_gebruik__m3_s_1")
    assert not flags.any()


def test_constante_reeks_flags_te_weinig_data_is_niet_beoordeelbaar():
    df = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "h",
            "tijdstip_start": pd.date_range("2023-01-01", periods=1, freq="h", tz="UTC"),
            "e_net__W": [1.0],
        }
    )
    flags = constante_reeks_flags(df, "e_net__W")
    assert not bool(flags.iloc[0])


def test_constante_reeks_flags_nan_blijft_na():
    df = pd.DataFrame(
        {
            "home_id__str": ["1", "1"],
            "interval_type__cat": ["d", "d"],
            "tijdstip_start": pd.date_range("2023-01-01", periods=2, freq="D", tz="UTC"),
            "g_gebruik__m3_s_1": [float("nan"), float("nan")],
        }
    )
    flags = constante_reeks_flags(df, "g_gebruik__m3_s_1")
    assert flags.isna().all()


def test_uitschieter_flags_vlagt_extreme_waarde():
    # Een enkele extreme waarde in een klein steekproefje jaagt zijn eigen std zo omhoog dat hij
    # zichzelf "verstopt" (klassiek probleem van een niet-robuuste z-score); daarom hier een
    # realistischere steekproefgrootte (~24 normale waarden), zoals een dag aan uurwaarden.
    tijdstippen = pd.date_range("2023-01-01", periods=25, freq="h", tz="UTC")
    waarden = [1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.02, 0.98] * 3 + [50.0]
    df = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "h",
            "tijdstip_start": tijdstippen,
            "e_net__W": waarden,
        }
    )
    flags = uitschieter_flags(df, "e_net__W", n_sigma=3.0)
    assert bool(flags.iloc[-1])
    assert not flags.iloc[:-1].any()


def test_uitschieter_flags_constante_reeks_geeft_na_niet_true():
    df = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "h",
            "tijdstip_start": pd.date_range("2023-01-01", periods=5, freq="h", tz="UTC"),
            "e_net__W": [1.0] * 5,
        }
    )
    flags = uitschieter_flags(df, "e_net__W")
    assert flags.isna().all()


def test_extreme_uitschieters_rapport_meterwissel_patroon():
    # Nabouw van het §12.6-patroon: woning "1" heeft één maand met een extreme, gelijktijdige
    # e_net- én g_gebruik-uitschieter (mogelijke gecombineerde meterwissel); woning "2" heeft een
    # kleinere, losstaande e_net-uitschieter (geen gas-uitschieter erbij). Een ruime, realistische
    # reeksgrootte (~3 jaar aan maandwaarden), anders jaagt de extreme waarde zijn eigen std zo
    # omhoog dat de z-score hem "verstopt" (zelfde valkuil als bij een te kleine steekproef in
    # test_uitschieter_flags_vlagt_extreme_waarde).
    maanden = pd.date_range("2023-01-01", periods=36, freq="MS", tz="UTC")
    duur = pd.Series([INTERVAL_DUUR_S["m"]] * 36, dtype="int32")
    normaal_e = [10.0, 12.0, 11.0, 9.0, 13.0, 10.0, 11.0, 8.0, 14.0, 9.5, 10.5, 12.5] * 3
    normaal_g = [5.0, 6.0, 5.5, 5.0, 6.0, 5.0, 5.5, 4.5, 6.5, 5.2, 5.8, 5.1] * 3
    e_net_1 = list(normaal_e)
    e_net_1[3] = -2117.0
    g_gebruik_1 = list(normaal_g)
    g_gebruik_1[3] = -740.0
    df1 = pd.DataFrame(
        {
            "home_id__str": "1",
            "interval_type__cat": "m",
            "tijdstip_start": maanden,
            "interval_duur__s": duur,
            "e_net__W": e_net_1,
            "g_gebruik__m3_s_1": g_gebruik_1,
        }
    )
    e_net_2 = list(normaal_e)
    e_net_2[2] = -227.0
    df2 = pd.DataFrame(
        {
            "home_id__str": "2",
            "interval_type__cat": "m",
            "tijdstip_start": maanden,
            "interval_duur__s": duur,
            "e_net__W": e_net_2,
            "g_gebruik__m3_s_1": [0.0] * 36,
        }
    )
    measurements = pd.concat([df1, df2], ignore_index=True)
    quality = build_quality_table(measurements)

    rapport = extreme_uitschieters_rapport(measurements, quality, top_n=10)

    assert not rapport.empty
    # De grootste (home 1, e_net -2117) staat vooraan en is een gecombineerde uitschieter.
    top = rapport.iloc[0]
    assert top["home_id__str"] == "1"
    assert top["beide_uitschieter__bool"]

    # Home 2's e_net-uitschieter staat er ook in, maar zonder gas erbij (gas is een constante
    # reeks van exacte nullen, geen uitschieter).
    home2_rijen = rapport[rapport["home_id__str"] == "2"]
    assert len(home2_rijen) == 1
    assert not home2_rijen.iloc[0]["beide_uitschieter__bool"]


def test_gas_voor_koppeling_verdacht_rapport_onderscheidt_verdacht_van_zelf_consistent():
    # Nabouw van het §12.7-patroon: woning "1027-achtig" heeft 90 dagen exact 0 gas, gevolgd door
    # een reeks met normale variatie, én metadata die reëel gasgebruik verwacht (kookt op gas):
    # dat is verdacht. Woning "1001-achtig" heeft ALTIJD exact 0 gas (geen gasgebruik verwacht,
    # all-electric); dat is zelf-consistent, niet verdacht.
    dagen = pd.date_range("2023-01-01", periods=150, freq="D", tz="UTC")
    gas_verdacht = [0.0] * 90 + [0.5, 0.0, 1.2, 0.8, 0.0] * 12
    df_verdacht = pd.DataFrame(
        {
            "home_id__str": "verdacht",
            "interval_type__cat": "d",
            "tijdstip_start": dagen,
            "g_gebruik__m3_s_1": gas_verdacht,
        }
    )
    df_zelfconsistent = pd.DataFrame(
        {
            "home_id__str": "zelfconsistent",
            "interval_type__cat": "d",
            "tijdstip_start": dagen,
            "g_gebruik__m3_s_1": [0.0] * 150,
        }
    )
    measurements = pd.concat([df_verdacht, df_zelfconsistent], ignore_index=True)

    homes = pd.DataFrame(
        [
            {"home_id__str": "verdacht", "kookt_op_gas__bool": True, "heeft_hr_ketel__bool": False},
            {"home_id__str": "zelfconsistent", "kookt_op_gas__bool": False, "heeft_hr_ketel__bool": False},
        ]
    )

    rapport = gas_voor_koppeling_verdacht_rapport(measurements, homes, venster_dagen=60)

    verdacht_rij = rapport[rapport["home_id__str"] == "verdacht"].iloc[0]
    assert verdacht_rij["verdacht__bool"]

    zelfconsistent_rij = rapport[rapport["home_id__str"] == "zelfconsistent"].iloc[0]
    assert not zelfconsistent_rij["verdacht__bool"]
