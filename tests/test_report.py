# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.report: de gegenereerde rapporttekst, de Nederlandse getalopmaak
daarin, en het bewaren/herbouwen van het rapport zonder de pijplijn opnieuw te draaien (ontwerp
§12.17).
"""

from __future__ import annotations

import re

import pandas as pd

from im3_preprocessing import report
from im3_preprocessing.pipeline import RapportAccumulator

_NBSP = " "


def _accumulator_met_testdata() -> RapportAccumulator:
    acc = RapportAccumulator()
    acc.n_rijen = 12345
    acc.n_woningen = 2
    acc.n_zonder_gaskolom = 1
    acc.vlag_tellingen = {"e_net_uitschieter__flag": 20000, "g_gebruik_ontbrekend__flag": 5}
    acc.interval_tellingen = {"q": 12000, "h": 345}
    acc.tijdstip_min = pd.Timestamp("2022-01-01", tz="UTC")
    acc.tijdstip_max = pd.Timestamp("2023-06-01", tz="UTC")
    acc.dagcheck_kwartier = [pd.array([1.0, 2.0, 400.0], dtype="float32").to_numpy()]
    acc.n_dagcheck_kwartier = 3
    acc.dagcheck_uur = []
    acc.n_dagcheck_uur = 0
    acc.dst_aanwezig = 1
    acc.dst_totaal = 3
    acc.gas_negatief_rijen = 12345
    acc.n_gas_negatief_woningen = 1
    acc.extreme_uitschieters = [
        pd.DataFrame(
            {
                "home_id__str": ["1"],
                "tijdstip_start": [pd.Timestamp("2023-05-01", tz="UTC")],
                "interval_type__cat": ["m"],
                "veld": ["e_net__W"],
                "waarde": [-2117.0],
                "abs_waarde": [2117.0],
                "beide_uitschieter__bool": [True],
            }
        )
    ]
    acc.gas_voor_koppeling = [
        pd.DataFrame(
            {
                "home_id__str": ["2"],
                "n_vroege_dagen": [60],
                "frac_nul_latere_dagen": [0.1],
                "kookt_op_gas__bool": [True],
                "heeft_hr_ketel__bool": [False],
                "verdacht__bool": [True],
            }
        )
    ]
    acc.im3_weer = [
        pd.DataFrame(
            {
                "weerstation_nr": pd.array([260], dtype="int16"),
                "tijdstip": [pd.Timestamp("2022-06-01T12:00", tz="UTC")],
                "temp_buiten__degC": pd.array([18.5], dtype="float32"),
                "wind__m_s_1": pd.array([3.0], dtype="float32"),
                "ghi__W_m_2": pd.array([120.0], dtype="float32"),
                "bron__cat": pd.Series(["im3"], dtype="category"),
            }
        )
    ]
    acc.gas_hhv_bron_tellingen = {"actueel": 12000, "vast_gemiddelde_fallback": 345}
    return acc


def _homes() -> pd.DataFrame:
    return pd.DataFrame(
        {"home_id__str": ["1", "2"], "woningtype_bron_afgekapt__bool": [True, False]}
    )


def _weer_consistentie_testdata() -> pd.DataFrame:
    """Zelfde kolommen als weer.consistency_check() teruggeeft (weerstation_nr, n_overlap, en per
    WEERVELD een `<veld>_mediane_abs_afwijking`/`<veld>_binnen_drempel`) -- _weer_sectie() leest ze
    allemaal, dus een onvolledige testtabel geeft een KeyError zodra len(...) > 0."""
    return pd.DataFrame(
        {
            "weerstation_nr": [260],
            "n_overlap": [100],
            "temp_buiten__degC_mediane_abs_afwijking": [0.1],
            "temp_buiten__degC_binnen_drempel": [True],
            "wind__m_s_1_mediane_abs_afwijking": [0.2],
            "wind__m_s_1_binnen_drempel": [True],
            "ghi__W_m_2_mediane_abs_afwijking": [5.0],
            "ghi__W_m_2_binnen_drempel": [True],
        }
    )


# --------------------------------------------------------------------------------------------
# Nederlandse getalopmaak in het gegenereerde rapport
# --------------------------------------------------------------------------------------------


def test_build_report_geen_amerikaanse_duizendtalkomma():
    tekst = report.build_report(
        acc=_accumulator_met_testdata(), homes=_homes(), weer_consistentie=pd.DataFrame(), is_steekproef=False
    )
    # Oude {:,}-opmaak zou deze grote testgetallen (n_rijen/gas_negatief_rijen=12345,
    # vlag_tellingen=20000/12000) als "12,345"/"20,000"/"12,000" hebben geschreven. Let op: dit is
    # GEEN blanco "geen komma-cijfer-cijfer-cijfer"-regex -- `_fmt` schrijft bv. "2,000" voor de
    # dagcheck-mediaan (2,000 als DRIE-decimalen-Nederlands getal, niet als Amerikaans "tweeduizend"),
    # en die twee zien er toevallig identiek uit. Alleen de bekende, echt-grote testgetallen worden
    # dus expliciet gecontroleerd, niet elk cijfer-komma-drie-cijfers-patroon in de hele tekst.
    for oude_amerikaanse_schrijfwijze in ("12,345", "20,000", "12,000"):
        assert oude_amerikaanse_schrijfwijze not in tekst


def test_build_report_gebruikt_punt_als_duizendtalscheiding():
    tekst = report.build_report(
        acc=_accumulator_met_testdata(), homes=_homes(), weer_consistentie=pd.DataFrame(), is_steekproef=False
    )
    # acc.n_rijen = 12345 en acc.gas_negatief_rijen = 12345 komen als "12.345" terecht.
    assert "12.345" in tekst


def test_build_report_gebruikt_komma_als_decimaalteken_in_percentages():
    tekst = report.build_report(
        acc=_accumulator_met_testdata(), homes=_homes(), weer_consistentie=pd.DataFrame(), is_steekproef=False
    )
    assert re.search(r"\d,\d" + _NBSP + "%", tekst)


# --------------------------------------------------------------------------------------------
# RapportAccumulator.naar_json_dict / uit_json_dict / voeg_accumulator_toe
# --------------------------------------------------------------------------------------------


def test_naar_json_dict_uit_json_dict_levert_hetzelfde_rapport_op():
    """De kern van hervatbaarheid: een chunk-accumulator die via JSON heen en weer is, moet
    hetzelfde rapport opleveren als het origineel -- anders zou een hervatte run een ander
    (fout) rapport schrijven dan een ononderbroken run."""
    acc = _accumulator_met_testdata()
    acc_terug = RapportAccumulator.uit_json_dict(acc.naar_json_dict())

    origineel = report.build_report(acc=acc, homes=_homes(), weer_consistentie=pd.DataFrame(), is_steekproef=False)
    na_round_trip = report.build_report(
        acc=acc_terug, homes=_homes(), weer_consistentie=pd.DataFrame(), is_steekproef=False
    )
    assert origineel == na_round_trip


def test_uit_json_dict_lege_accumulator():
    lege = RapportAccumulator()
    terug = RapportAccumulator.uit_json_dict(lege.naar_json_dict())
    assert terug.n_rijen == 0
    assert terug.tijdstip_min is None
    aantal, mediaan, p95 = terug.dagcheck_statistiek("kwartier")
    assert aantal == 0
    assert pd.isna(mediaan) and pd.isna(p95)


def test_voeg_accumulator_toe_sommeert_additieve_velden():
    a = RapportAccumulator()
    a.n_rijen = 10
    a.vlag_tellingen = {"x__flag": 3}
    a.tijdstip_min = pd.Timestamp("2022-01-01", tz="UTC")
    a.tijdstip_max = pd.Timestamp("2022-06-01", tz="UTC")
    a.n_gas_negatief_woningen = 1

    b = RapportAccumulator()
    b.n_rijen = 5
    b.vlag_tellingen = {"x__flag": 2, "y__flag": 1}
    b.tijdstip_min = pd.Timestamp("2021-01-01", tz="UTC")
    b.tijdstip_max = pd.Timestamp("2023-01-01", tz="UTC")
    b.n_gas_negatief_woningen = 4

    a.voeg_accumulator_toe(b)

    assert a.n_rijen == 15
    assert a.vlag_tellingen == {"x__flag": 5, "y__flag": 1}
    assert a.tijdstip_min == pd.Timestamp("2021-01-01", tz="UTC")
    assert a.tijdstip_max == pd.Timestamp("2023-01-01", tz="UTC")
    assert a.n_gas_negatief_woningen == 5


def test_naar_json_dict_uit_json_dict_met_meerdere_dagcheck_buffers_van_verschillende_lengte():
    """Regressietest (05-09-2026): een accumulator die al meerdere chunks heeft samengevoegd, heeft
    per chunk een EIGEN, mogelijk ongelijk lange dagcheck-buffer. ``uit_json_dict`` maakte daar ten
    onrechte één (ongeldige) array van i.p.v. een lijst van aparte arrays, wat pas crashte zodra
    ``dagcheck_statistiek`` ze probeerde te concateneren -- niet zichtbaar bij een enkele-chunk-
    accumulator, wél op de echte 4-chunks-steekproef die dit aan het licht bracht."""
    a = RapportAccumulator()
    a.dagcheck_kwartier = [pd.array([1.0, 2.0], dtype="float32").to_numpy()]
    b = RapportAccumulator()
    b.dagcheck_kwartier = [pd.array([3.0, 4.0, 5.0, 6.0], dtype="float32").to_numpy()]  # andere lengte
    a.voeg_accumulator_toe(b)
    assert len(a.dagcheck_kwartier) == 2

    a_terug = RapportAccumulator.uit_json_dict(a.naar_json_dict())
    assert len(a_terug.dagcheck_kwartier) == 2
    aantal, mediaan, _ = a_terug.dagcheck_statistiek("kwartier")
    assert aantal == 6
    assert mediaan == 3.5


def test_voeg_accumulator_toe_combineert_dagcheck_steekproeven_voor_een_correcte_mediaan():
    # Twee "chunks" met elk een deel van de steekproef; de mediaan van het GEHEEL (1,2,3,4,100) is
    # 3, wat NIET het gemiddelde is van de twee losse chunk-medianen (1,5 en 52) -- vandaar dat de
    # ruwe steekproeven samengevoegd moeten worden, niet de per-chunk statistiek.
    a = RapportAccumulator()
    a.dagcheck_kwartier = [pd.array([1.0, 2.0], dtype="float32").to_numpy()]
    a.n_dagcheck_kwartier = 2
    b = RapportAccumulator()
    b.dagcheck_kwartier = [pd.array([3.0, 4.0, 100.0], dtype="float32").to_numpy()]
    b.n_dagcheck_kwartier = 3

    a.voeg_accumulator_toe(b)
    aantal, mediaan, _ = a.dagcheck_statistiek("kwartier")
    assert aantal == 5
    assert mediaan == 3.0


# --------------------------------------------------------------------------------------------
# schrijf_accumulator / lees_accumulator / herbouw (de CLI-functies)
# --------------------------------------------------------------------------------------------


def test_schrijf_en_lees_accumulator_round_trip(tmp_path):
    acc = _accumulator_met_testdata()
    weer_consistentie = _weer_consistentie_testdata()
    pad = tmp_path / "rapport_accumulator.json"
    report.schrijf_accumulator(
        pad,
        acc=acc,
        is_steekproef=True,
        weer_venster_dagen=30,
        weer_consistentie=weer_consistentie,
        weer_consistentie_geointerpoleerd=None,
        im3_weer=acc.samengevoegd_im3_weer(),
    )
    assert pad.is_file()

    kwargs = report.lees_accumulator(pad)
    assert kwargs["is_steekproef"] is True
    assert kwargs["weer_venster_dagen"] == 30
    assert kwargs["weer_consistentie"]["weerstation_nr"].tolist() == [260]
    assert kwargs["im3_weer"]["weerstation_nr"].tolist() == [260]

    # Het rapport gebouwd uit de teruggelezen kwargs moet identiek zijn aan het origineel.
    origineel = report.build_report(
        acc=acc, homes=_homes(), weer_consistentie=weer_consistentie, is_steekproef=True, weer_venster_dagen=30
    )
    herbouwd = report.build_report(homes=_homes(), **kwargs)
    assert origineel == herbouwd


def test_herbouw_leest_homes_en_weer_parquet_terug(tmp_path):
    out_dir = tmp_path / "processed"
    out_dir.mkdir()
    docs_dir = tmp_path / "docs"

    homes = _homes()
    homes.to_parquet(out_dir / "homes.parquet", index=False)

    acc = _accumulator_met_testdata()
    report.schrijf_accumulator(
        out_dir / "rapport_accumulator.json",
        acc=acc,
        is_steekproef=False,
        weer_venster_dagen=None,
        weer_consistentie=pd.DataFrame(),
        weer_consistentie_geointerpoleerd=None,
        im3_weer=acc.samengevoegd_im3_weer(),
    )

    pad = report.herbouw(out_dir, docs_dir)
    assert pad == docs_dir / "data-quality.md"
    assert pad.is_file()
    assert "Datakwaliteitsrapport" in pad.read_text(encoding="utf-8")
