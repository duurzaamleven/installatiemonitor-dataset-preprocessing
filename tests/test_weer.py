# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.weer.

De meeste tests hier zijn puur (geen netwerk). Tests die echt KNMI bevragen zijn gemarkeerd met
``@pytest.mark.network`` en draaien niet standaard mee (zie pyproject.toml ``addopts``); draai ze
expliciet met ``pytest -m network``.
"""

import numpy as np
import pandas as pd
import pytest

from im3_preprocessing.timestamps import local_day_window
from im3_preprocessing.io import CustomerFile
from im3_preprocessing.pipeline import build_measurements
from im3_preprocessing.weer import (
    METRICS,
    consistency_check,
    couple_weather_to_measurements,
    extract_im3_weather,
    sun_kWh_m2_naar_W_m2,
)


def test_couple_weather_to_measurements_per_interval_type():
    datum = pd.Timestamp("2023-06-15").date()  # geen DST-overgang, dus 24 nette uurpunten
    start, eind = local_day_window(datum)
    uren = pd.date_range(start, eind, freq="1h", inclusive="left")
    assert len(uren) == 24

    weer = pd.DataFrame(
        {
            "weerstation_nr": 290,
            "tijdstip": uren,
            "temp_buiten__degC": np.arange(24, dtype=float),
            "wind__m_s_1": np.zeros(24),
            "ghi__W_m_2": np.zeros(24),
            "bron__cat": "eigen_ingest",
        }
    )

    metingen = pd.DataFrame(
        [
            {"home_id__str": "1", "tijdstip_start": uren[5], "interval_type__cat": "h", "weerstation_nr": 290},
            {
                "home_id__str": "1",
                "tijdstip_start": uren[5] + pd.Timedelta(minutes=30),
                "interval_type__cat": "q",
                "weerstation_nr": 290,
            },
            {"home_id__str": "1", "tijdstip_start": start, "interval_type__cat": "d", "weerstation_nr": 290},
        ]
    )

    result = couple_weather_to_measurements(metingen, weer, bron="eigen_ingest")

    h_rij = result[result["interval_type__cat"] == "h"].iloc[0]
    assert h_rij["temp_buiten__degC"] == 5.0
    assert h_rij["weerkoppeling_methode__cat"] == "punt_uur"

    q_rij = result[result["interval_type__cat"] == "q"].iloc[0]
    assert q_rij["temp_buiten__degC"] == pytest.approx(5.5)
    assert q_rij["weerkoppeling_methode__cat"] == "punt_interpolatie"

    d_rij = result[result["interval_type__cat"] == "d"].iloc[0]
    assert d_rij["temp_buiten__degC"] == pytest.approx(11.5)
    assert d_rij["weerkoppeling_methode__cat"] == "gemiddelde_dag"


def test_couple_weather_to_measurements_ontbrekend_station():
    weer = pd.DataFrame(
        columns=["weerstation_nr", "tijdstip", "temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2", "bron__cat"]
    )
    metingen = pd.DataFrame(
        [{"home_id__str": "1", "tijdstip_start": pd.Timestamp("2023-01-01", tz="UTC"), "interval_type__cat": "h", "weerstation_nr": 999}]
    )
    result = couple_weather_to_measurements(metingen, weer)
    assert result.iloc[0]["weerkoppeling_methode__cat"] == "ontbrekend_buiten_archief"


def _weer_reeks(temps):
    tijdstippen = pd.date_range("2023-06-15", periods=len(temps), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "weerstation_nr": 1,
            "tijdstip": tijdstippen,
            "temp_buiten__degC": temps,
            "wind__m_s_1": [2.0] * len(temps),
            "ghi__W_m_2": [0.1] * len(temps),
        }
    )


def test_consistency_check_binnen_drempel():
    im3 = _weer_reeks([10.0, 10.0, 10.0])
    eigen = _weer_reeks([10.1, 10.1, 10.1])  # afwijking 0.1, drempel 0.5
    result = consistency_check(im3, eigen)
    assert bool(result.iloc[0]["temp_buiten__degC_binnen_drempel"]) is True


def test_consistency_check_buiten_drempel():
    im3 = _weer_reeks([10.0, 10.0, 10.0])
    eigen = _weer_reeks([12.0, 12.0, 12.0])  # afwijking 2.0, drempel 0.5
    result = consistency_check(im3, eigen)
    assert bool(result.iloc[0]["temp_buiten__degC_binnen_drempel"]) is False


@pytest.mark.network
def test_get_station_coordinates_bevat_bekende_stations():
    from im3_preprocessing.weer import get_station_coordinates

    coords = get_station_coordinates()
    assert 290 in coords.index  # Twenthe Airport
    assert 240 in coords.index  # Schiphol Airport


def test_dichtstbijzijnde_latlon_kiest_het_juiste_punt():
    from im3_preprocessing.weer import _dichtstbijzijnde_latlon

    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2024-01-01", tz="UTC"), 52.0, 6.0),
            (pd.Timestamp("2024-01-01", tz="UTC"), 52.5, 6.9),
            (pd.Timestamp("2024-01-02", tz="UTC"), 52.0, 6.0),
        ],
        names=["timestamp", "lat__degN", "lon__degE"],
    )
    df = pd.DataFrame({"temp_buiten__degC": [1.0, 2.0, 3.0]}, index=index)

    dichtstbijzijnd = _dichtstbijzijnde_latlon(df, lat=52.4, lon=6.85)
    assert dichtstbijzijnd == (52.5, 6.9)


@pytest.mark.network
def test_fetch_own_weather_direct_live_tegen_bekend_station():
    from im3_preprocessing.weer import fetch_own_weather_direct, get_station_coordinates

    coords = get_station_coordinates()
    stn = 290  # Twenthe Airport
    station_coords = {stn: (coords.loc[stn, "lat__degN"], coords.loc[stn, "lon__degE"])}

    start = pd.Timestamp("2024-01-05", tz="UTC")
    eind = pd.Timestamp("2024-01-06", tz="UTC")
    result = fetch_own_weather_direct(start, eind, station_coords)

    assert not result.empty
    assert (result["weerstation_nr"] == stn).all()
    # Sinds §12.13 is de rauwe stationswaarde de standaard-bron `eigen_ingest`.
    assert (result["bron__cat"] == "eigen_ingest").all()
    # Nederlandse januari-temperaturen: ruime, sanity-check-brede grenzen.
    assert result["temp_buiten__degC"].between(-20, 20).all()


@pytest.mark.network
def test_geospatiale_interpolatie_geeft_op_een_station_hetzelfde_antwoord():
    """De onderbouwing van §12.13, als test in plaats van als bewering.

    RBF-interpolatie naar de coördinaat van een station dat zelf in de brondata zit, hoort
    (vrijwel) de rauwe waarde van dát station terug te geven. Zolang dat klopt, voegt de dure
    geospatiale stap niets toe zolang we alleen bekende stations opvragen, en is het terecht dat
    `eigen_ingest` de rauwe variant is.
    """
    from im3_preprocessing.weer import (
        fetch_own_weather,
        fetch_own_weather_direct,
        fetch_ruwe_stationsdata,
        get_station_coordinates,
    )

    coords = get_station_coordinates()
    stn = 290
    station_coords = {stn: (coords.loc[stn, "lat__degN"], coords.loc[stn, "lon__degE"])}
    start = pd.Timestamp("2024-01-05", tz="UTC")
    eind = pd.Timestamp("2024-01-06", tz="UTC")

    df_alle_stations = fetch_ruwe_stationsdata(start, eind)
    geinterpoleerd = fetch_own_weather(start, eind, station_coords, df_alle_stations=df_alle_stations)
    rauw = fetch_own_weather_direct(start, eind, station_coords, df_alle_stations=df_alle_stations)

    assert not geinterpoleerd.empty
    assert not rauw.empty
    assert (geinterpoleerd["bron__cat"] == "eigen_ingest_geointerpoleerd").all()
    assert (rauw["bron__cat"] == "eigen_ingest").all()

    verschil = (
        geinterpoleerd.set_index("tijdstip")["temp_buiten__degC"]
        - rauw.set_index("tijdstip")["temp_buiten__degC"]
    ).abs()
    assert verschil.median() < 0.5


def _weerframe(uren, resolutie: str) -> pd.DataFrame:
    """Weertabel op een gekozen tijdresolutie, om §12.14 te kunnen reproduceren."""
    return pd.DataFrame(
        {
            "weerstation_nr": 290,
            "tijdstip": pd.Series(uren).astype(f"datetime64[{resolutie}, UTC]"),
            "temp_buiten__degC": np.arange(len(uren), dtype=float),
            "wind__m_s_1": np.zeros(len(uren)),
            "ghi__W_m_2": np.zeros(len(uren)),
            "bron__cat": "eigen_ingest",
        }
    )


@pytest.mark.parametrize("resolutie", ["ns", "us", "ms", "s"])
def test_koppeling_werkt_ongeacht_tijdresolutie_van_de_weerreeks(resolutie):
    """Regressietest voor §12.14: h/q mogen niet stilzwijgend leeglopen bij een andere resolutie.

    De KNMI-library levert ``datetime64[us]`` terwijl ``measurements`` ``datetime64[ns]`` is.
    De koppeling matchte op ``.astype("int64")``, wat het getal in de EIGEN resolutie geeft, dus
    een factor 1000 verschil. Gevolg: geen enkele h-rij matchte en elke q-rij viel buiten het
    np.interp-bereik. Er kwam geen foutmelding, alleen ``ontbrekend_buiten_archief``.

    De oude fixture gebruikte ``pd.date_range`` (altijd ns) en kon dit dus per constructie niet
    zien. Vandaar hier expliciet meerdere resoluties.
    """
    datum = pd.Timestamp("2023-06-15").date()
    start, eind = local_day_window(datum)
    uren = pd.date_range(start, eind, freq="1h", inclusive="left")
    weer = _weerframe(uren, resolutie)

    metingen = pd.DataFrame(
        [
            {"home_id__str": "1", "tijdstip_start": uren[5], "interval_type__cat": "h", "weerstation_nr": 290},
            {"home_id__str": "1", "tijdstip_start": uren[5] + pd.Timedelta(minutes=30),
             "interval_type__cat": "q", "weerstation_nr": 290},
            {"home_id__str": "1", "tijdstip_start": start, "interval_type__cat": "d", "weerstation_nr": 290},
        ]
    )
    # Expliciet ns, precies zoals timestamps.resolve_timestamps het in de pipeline oplevert.
    # Zonder deze regel maakt pandas er us van (DataFrame uit losse Timestamp-objecten), en dan
    # staan beide kanten toevallig op dezelfde resolutie en test dit niets.
    metingen["tijdstip_start"] = metingen["tijdstip_start"].astype("datetime64[ns, UTC]")
    assert str(metingen["tijdstip_start"].dtype) == "datetime64[ns, UTC]"

    result = couple_weather_to_measurements(metingen, weer, bron="eigen_ingest")
    per_type = result.set_index("interval_type__cat")

    assert per_type.loc["h", "weerkoppeling_methode__cat"] == "punt_uur"
    assert per_type.loc["h", "temp_buiten__degC"] == 5.0
    assert per_type.loc["q", "weerkoppeling_methode__cat"] == "punt_interpolatie"
    assert per_type.loc["q", "temp_buiten__degC"] == pytest.approx(5.5)
    assert per_type.loc["d", "weerkoppeling_methode__cat"] == "gemiddelde_dag"
    assert per_type.loc["d", "temp_buiten__degC"] == pytest.approx(11.5)
    # De kern van de regressie: geen enkele rij mag stilzwijgend leeglopen.
    assert not (result["weerkoppeling_methode__cat"] == "ontbrekend_buiten_archief").any()


def test_sun_kWh_m2_naar_W_m2_bekende_gevallen():
    duur = pd.Series([3600, 3600, 900])
    sun = pd.Series([0.5, 1 / 360, 0.5])
    w = sun_kWh_m2_naar_W_m2(sun, duur)
    # 0,5 kWh/m2 in een uur = gemiddeld 500 W/m2; in een kwartier 2000 W/m2.
    assert w.iloc[0] == pytest.approx(500.0)
    assert w.iloc[2] == pytest.approx(2000.0)
    # 1/360 kWh/m2 is de kleinste stap in de bron (0,002778): 1 J/cm2 KNMI-Q. Na omrekening moet
    # dat precies de KNMI-factor van de eigen ingest opleveren (10.000/3.600 = 2,78 W/m2), anders
    # vergelijkt de consistentiecheck twee verschillende eenheden.
    assert w.iloc[1] == pytest.approx(METRICS["Q"][1])


def test_extract_im3_weather_rekent_sun_om_naar_W_m2():
    # Regressie: sun werd zonder schaling hernoemd naar ghi__W_m_2, waardoor de IM3-reeks een
    # factor 1000 te laag in de consistentiecheck belandde.
    df = pd.DataFrame(
        [
            {"datetime": "2023-03-01 12:00:00+00:00", "elec": 0.5, "interval": "h", "gas": 0.1,
             "wind": 5.0, "temp": 5.5, "sun": 0.533333},
            {"datetime": "2023-03-01 12:15:00+00:00", "elec": 0.1, "interval": "q", "gas": 0.0,
             "wind": float("nan"), "temp": float("nan"), "sun": float("nan")},
        ]
    )
    df["home_id__str"] = "1"
    homes = pd.DataFrame({"home_id__str": ["1"], "weerstation_nr": [260]})
    _, raw = build_measurements([CustomerFile(home_id__str="1", df=df, issues=[])], homes)

    im3 = extract_im3_weather(raw, homes)

    assert len(im3) == 1
    assert im3["ghi__W_m_2"].iloc[0] == pytest.approx(533.333, rel=1e-5)
    assert im3["tijdstip"].iloc[0] == pd.Timestamp("2023-03-01 11:00:00+00:00")
