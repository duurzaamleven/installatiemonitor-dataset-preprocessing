# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.intervals, inclusief de verplichte DST-testcases (ontwerp §2.4)."""

import pandas as pd

from im3_preprocessing.intervals import compute_energie_deler_s, compute_interval_duur_s


def test_q_en_h_zijn_vast():
    datetime_raw = pd.Series(["2023-03-01 12:15:00+00:00", "2023-03-01 13:00:00+00:00"])
    interval_type = pd.Series(["q", "h"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 900
    assert result.iloc[1] == 3600


def test_d_gewone_dag_is_86400():
    datetime_raw = pd.Series(["2023-06-15"])
    interval_type = pd.Series(["d"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 86400


def test_d_voorjaarsovergang_is_82800():
    # 23 uur * 3600 = 82800 s; een hardcoded 86400 zou hier ±4% fout geven (§2.4).
    datetime_raw = pd.Series(["2023-03-26"])
    interval_type = pd.Series(["d"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 82800


def test_d_najaarsovergang_is_90000():
    # 25 uur * 3600 = 90000 s.
    datetime_raw = pd.Series(["2023-10-29"])
    interval_type = pd.Series(["d"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 90000


def test_m_gewone_maand():
    datetime_raw = pd.Series(["2023-06-30"])  # juni, geen DST-overgang
    interval_type = pd.Series(["m"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 30 * 86400


def test_m_met_dst_overgang_is_1_uur_korter():
    datetime_raw = pd.Series(["2023-03-31"])  # maart, bevat de voorjaarsovergang
    interval_type = pd.Series(["m"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert result.iloc[0] == 31 * 86400 - 3600


def test_gemengde_interval_types_in_een_serie():
    datetime_raw = pd.Series(
        ["2023-03-01 12:15:00+00:00", "2023-03-26", "2022-03-31", "2023-03-01 13:00:00+00:00"]
    )
    interval_type = pd.Series(["q", "d", "m", "h"])
    result = compute_interval_duur_s(datetime_raw, interval_type)
    assert list(result) == [900, 82800, 31 * 86400 - 3600, 3600]


def test_energie_deler_m_rij_is_altijd_een_dag():
    # ontwerp-intervalsemantiek.md §2: de m-waarde is het gemiddelde dagverbruik van de maand, dus
    # de deler is 86.400 s, ook al is interval_duur__s (de maandduur) heel anders.
    interval_type = pd.Series(["m", "m"])
    interval_duur__s = pd.Series([31 * 86400, 31 * 86400 - 3600], dtype="int32")  # incl. DST-maand
    deler = compute_energie_deler_s(interval_type, interval_duur__s)
    assert list(deler) == [86400, 86400]


def test_energie_deler_q_h_d_is_interval_duur_s_zelf():
    interval_type = pd.Series(["q", "h", "d"])
    interval_duur__s = pd.Series([900, 3600, 82800], dtype="int32")
    deler = compute_energie_deler_s(interval_type, interval_duur__s)
    assert list(deler) == [900, 3600, 82800]
