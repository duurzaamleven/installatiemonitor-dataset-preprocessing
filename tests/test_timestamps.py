# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.timestamps, inclusief de verplichte DST-testcases (ontwerp §2.4)."""

import datetime as dt

import pandas as pd
import pytest

from im3_preprocessing.timestamps import (
    TZ_LOKAAL,
    local_day_window,
    local_month_window,
    resolve_timestamps,
)


def test_local_day_window_gewone_dag_is_24_uur():
    start, eind = local_day_window(dt.date(2023, 6, 15))
    assert (eind - start) == pd.Timedelta(hours=24)


def test_local_day_window_voorjaarsovergang_is_23_uur():
    # 2023-03-26: nacht van 02:00->03:00 lokaal bestaat niet, dag telt 23 uur (§2.4).
    start, eind = local_day_window(dt.date(2023, 3, 26))
    assert (eind - start) == pd.Timedelta(hours=23)
    # 92 kwartieren op deze dag, niet 96.
    assert (eind - start) / pd.Timedelta(minutes=15) == 92


def test_local_day_window_najaarsovergang_is_25_uur():
    # 2023-10-29: nacht van 03:00->02:00 lokaal, dag telt 25 uur (§2.4).
    start, eind = local_day_window(dt.date(2023, 10, 29))
    assert (eind - start) == pd.Timedelta(hours=25)
    # 100 kwartieren op deze dag, niet 96.
    assert (eind - start) / pd.Timedelta(minutes=15) == 100


@pytest.mark.parametrize(
    "datum,verwachte_kwartieren",
    [
        (dt.date(2022, 3, 27), 92),
        (dt.date(2023, 3, 26), 92),
        (dt.date(2024, 3, 31), 92),
        (dt.date(2025, 3, 30), 92),
        (dt.date(2022, 10, 30), 100),
        (dt.date(2023, 10, 29), 100),
        (dt.date(2024, 10, 27), 100),
        (dt.date(2025, 10, 26), 100),
    ],
)
def test_alle_dst_transitiedata_2022_2025(datum, verwachte_kwartieren):
    start, eind = local_day_window(datum)
    assert (eind - start) / pd.Timedelta(minutes=15) == verwachte_kwartieren


def test_local_month_window_bevat_dst_overgang():
    # Maart 2023 bevat de voorjaarsovergang: de maand is 1 uur korter dan 31*24h.
    start, eind = local_month_window(dt.date(2023, 3, 31))
    assert (eind - start) == pd.Timedelta(days=31) - pd.Timedelta(hours=1)


def test_local_month_window_zonder_dst_overgang():
    start, eind = local_month_window(dt.date(2023, 6, 30))
    assert (eind - start) == pd.Timedelta(days=30)


def test_resolve_timestamps_q_h_is_begin_van_interval_utc_min_duur():
    # RVO's letterlijke voorbeeld: kwartier 12:00-12:15 staat op de regel met (eind-)timestamp
    # 12:15; tijdstip_start is dus 12:00. Idem voor het uur 12:00-13:00, brontimestamp 13:00.
    datetime_raw = pd.Series(["2023-03-01 12:15:00+00:00", "2023-03-01 13:00:00+00:00"])
    interval_type = pd.Series(["q", "h"])
    result = resolve_timestamps(datetime_raw, interval_type)
    assert result.iloc[0] == pd.Timestamp("2023-03-01 12:00:00", tz="UTC")
    assert result.iloc[1] == pd.Timestamp("2023-03-01 12:00:00", tz="UTC")


def test_resolve_timestamps_d_is_lokaal_middernacht_begin_van_dag():
    datetime_raw = pd.Series(["2023-01-30"])
    interval_type = pd.Series(["d"])
    result = resolve_timestamps(datetime_raw, interval_type)
    verwacht = pd.Timestamp("2023-01-30 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert result.iloc[0] == verwacht


def test_resolve_timestamps_m_is_begin_van_eerste_dag_van_de_maand_lokaal():
    # RVO levert de LAATSTE dag van de maand (31 maart); tijdstip_start moet de EERSTE dag van
    # diezelfde maand zijn (1 maart), niet 31 maart en niet "datetime_raw - interval_duur__s".
    datetime_raw = pd.Series(["2022-03-31"])
    interval_type = pd.Series(["m"])
    result = resolve_timestamps(datetime_raw, interval_type)
    verwacht = pd.Timestamp("2022-03-01 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert result.iloc[0] == verwacht


def test_resolve_timestamps_m_uit_een_andere_dag_dan_de_1e_geeft_toch_de_1e():
    # RVO levert altijd de laatste dag, maar deze functie moet niet stilzwijgend op die aanname
    # leunen: elke dag in juli 2023 hoort naar 2023-07-01 te resolven.
    datetime_raw = pd.Series(["2023-07-15"])
    interval_type = pd.Series(["m"])
    result = resolve_timestamps(datetime_raw, interval_type)
    verwacht = pd.Timestamp("2023-07-01 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert result.iloc[0] == verwacht


def test_resolve_timestamps_tijdstip_start_plus_duur_is_einde_van_interval():
    # De kernbelofte van ontwerp-intervalsemantiek.md §1/§4: tijdstip_start + interval_duur__s
    # geeft voor elk intervaltype het einde van het bedoelde interval, ook over een maandgrens en
    # een DST-overgang heen.
    from im3_preprocessing.intervals import compute_interval_duur_s

    datetime_raw = pd.Series(
        ["2023-03-01 12:15:00+00:00", "2023-03-01 13:00:00+00:00", "2023-01-30", "2022-03-31"]
    )
    interval_type = pd.Series(["q", "h", "d", "m"])
    start = resolve_timestamps(datetime_raw, interval_type)
    duur = compute_interval_duur_s(datetime_raw, interval_type)
    eind = start + pd.to_timedelta(duur, unit="s")

    assert eind.iloc[0] == pd.Timestamp("2023-03-01 12:15:00", tz="UTC")
    assert eind.iloc[1] == pd.Timestamp("2023-03-01 13:00:00", tz="UTC")
    assert eind.iloc[2] == pd.Timestamp("2023-01-31 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert eind.iloc[3] == pd.Timestamp("2022-04-01 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")


@pytest.mark.parametrize(
    "datum,volgende_dag",
    [
        ("2023-03-26", "2023-03-27"),  # voorjaarsovergang: dag telt lokaal 23 uur
        ("2023-10-29", "2023-10-30"),  # najaarsovergang: dag telt lokaal 25 uur
    ],
)
def test_resolve_timestamps_d_plus_duur_is_einde_van_interval_op_dst_overgangsdagen(datum, volgende_dag):
    # §6.5: expliciet vereist naast de gewone-dag-variant hierboven.
    from im3_preprocessing.intervals import compute_interval_duur_s

    datetime_raw = pd.Series([datum])
    interval_type = pd.Series(["d"])
    start = resolve_timestamps(datetime_raw, interval_type)
    duur = compute_interval_duur_s(datetime_raw, interval_type)
    eind = start + pd.to_timedelta(duur, unit="s")

    verwacht = pd.Timestamp(f"{volgende_dag} 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert eind.iloc[0] == verwacht


def test_resolve_timestamps_m_plus_duur_is_einde_van_interval_met_dst_overgang():
    # Maart 2023 bevat de voorjaarsovergang: de maand is 1 uur korter dan een naïeve 31*24h-som.
    from im3_preprocessing.intervals import compute_interval_duur_s

    datetime_raw = pd.Series(["2023-03-31"])  # RVO levert de laatste dag van de maand
    interval_type = pd.Series(["m"])
    start = resolve_timestamps(datetime_raw, interval_type)
    duur = compute_interval_duur_s(datetime_raw, interval_type)
    eind = start + pd.to_timedelta(duur, unit="s")

    assert start.iloc[0] == pd.Timestamp("2023-03-01 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")
    assert eind.iloc[0] == pd.Timestamp("2023-04-01 00:00:00", tz=TZ_LOKAAL).tz_convert("UTC")


def test_resolve_timestamps_onbekend_interval_type_raised():
    datetime_raw = pd.Series(["2023-01-30"])
    interval_type = pd.Series(["x"])
    with pytest.raises(ValueError):
        resolve_timestamps(datetime_raw, interval_type)


def test_naar_lokale_tijdzone_behoudt_instant_en_maakt_lokaal_leesbaar():
    from im3_preprocessing.timestamps import naar_lokale_tijdzone

    # Midden in de zomertijd: UTC 12:00 is lokaal 14:00 (CEST, UTC+2).
    df = pd.DataFrame({"tijdstip": pd.to_datetime(["2023-07-01 12:00:00+00:00"], utc=True)})
    origineel = df["tijdstip"].iloc[0]

    resultaat = naar_lokale_tijdzone(df.copy())
    lokaal = resultaat["tijdstip"].iloc[0]

    assert str(lokaal.tz) == TZ_LOKAAL
    assert lokaal.hour == 14, "lokale tijd moet direct afleesbaar zijn"
    # Zelfde absolute moment: tz_convert verandert de weergave, niet het instant.
    assert lokaal == origineel
    assert lokaal.tz_convert("UTC").hour == 12


def test_naar_lokale_tijdzone_weigert_naive_kolom():
    from im3_preprocessing.timestamps import naar_lokale_tijdzone

    # Een tz-naive kolom omzetten zou raden zijn naar de bedoelde tijdzone i.p.v. hem alleen
    # anders weergeven; dat hoort een expliciete fout te zijn, geen stille aanname.
    df = pd.DataFrame({"tijdstip": pd.to_datetime(["2023-07-01 12:00:00"])})
    with pytest.raises(ValueError, match="niet tz-aware"):
        naar_lokale_tijdzone(df)
