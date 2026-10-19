# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.pipeline.build_measurements.

Vooral gericht op de regressie uit ontwerp-intervalsemantiek.md §2: de vermogens van m-rijen waren
een factor ~30 te laag doordat `energie / interval_duur__s` de MAANDDUUR als deler gebruikte,
terwijl een m-waarde het GEMIDDELDE DAGVERBRUIK van die maand is (§2.1 van het hoofdontwerp).
"""

from __future__ import annotations

import pandas as pd
import pytest

from im3_preprocessing.io import CustomerFile
from im3_preprocessing.pipeline import MEASUREMENTS_OUTPUT_KOLOMMEN, build_measurements


def _customer_file(home_id, rows):
    df = pd.DataFrame(rows)
    df["home_id__str"] = home_id
    for kolom in ("wind", "temp", "sun"):
        if kolom not in df.columns:
            df[kolom] = float("nan")
    return CustomerFile(home_id__str=home_id, df=df, issues=[])


def _homes(home_ids):
    return pd.DataFrame({"home_id__str": home_ids, "weerstation_nr": [260] * len(home_ids)})


def test_build_measurements_m_rij_vermogen_gebruikt_dagduur_als_deler():
    # Juni 2023: 30 dagen, geen DST-overgang, dus een schone rekensom.
    # 24 kWh/dag * 3.6e6 J/kWh / 86400 s = 1000 W precies -- als de bug terugkeert (delen door de
    # maandduur, 30*86400 s) komt hier 1000/30 = 33.33 W uit: een factor 30 te laag (ontwerp
    # ontwerp-intervalsemantiek.md §2, exact het gemeten patroon op de echte dataset).
    cf = _customer_file(
        "1",
        [{"datetime": "2023-06-30", "elec": 24.0, "interval": "m", "gas": float("nan")}],
    )
    measurements, _ = build_measurements([cf], _homes(["1"]))

    assert measurements["e_net__W"].iloc[0] == pytest.approx(1000.0, rel=1e-4)


def test_build_measurements_q_h_d_vermogen_gebruikt_interval_duur_s_als_deler():
    cf = _customer_file(
        "1",
        [
            # 1 kWh in een kwartier (900 s) -> 4000 W.
            {"datetime": "2023-06-15 12:15:00+00:00", "elec": 1.0, "interval": "q", "gas": float("nan")},
            # 1 kWh in een uur (3600 s) -> 1000 W.
            {"datetime": "2023-06-15 13:00:00+00:00", "elec": 1.0, "interval": "h", "gas": float("nan")},
            # 24 kWh op een gewone dag (86400 s) -> 1000 W.
            {"datetime": "2023-06-15", "elec": 24.0, "interval": "d", "gas": float("nan")},
        ],
    )
    measurements, _ = build_measurements([cf], _homes(["1"]))
    per_type = measurements.set_index("interval_type__cat")

    assert per_type.loc["q", "e_net__W"] == pytest.approx(4000.0, rel=1e-4)
    assert per_type.loc["h", "e_net__W"] == pytest.approx(1000.0, rel=1e-4)
    assert per_type.loc["d", "e_net__W"] == pytest.approx(1000.0, rel=1e-4)


def test_build_measurements_output_kolommen_bevatten_geen_energie_of_interne_werkkolommen():
    # ontwerp-intervalsemantiek.md §3: measurements.parquet bevat alleen vermogen, geen energie,
    # en geen interne werkkolommen (e_net__kWh, g_gebruik__m3, g_gebruik__m3_s_1, weerstation_nr).
    cf = _customer_file(
        "1", [{"datetime": "2023-06-15 13:00:00+00:00", "elec": 1.0, "interval": "h", "gas": 0.1}]
    )
    measurements, _ = build_measurements([cf], _homes(["1"]))

    assert MEASUREMENTS_OUTPUT_KOLOMMEN == [
        "home_id__str", "tijdstip_start", "interval_type__cat", "interval_duur__s",
        "granulariteit__cat", "e_net__W",
    ]
    output = measurements[MEASUREMENTS_OUTPUT_KOLOMMEN]
    for interne_kolom in ("e_net__kWh", "g_gebruik__m3", "g_gebruik__m3_s_1", "weerstation_nr"):
        assert interne_kolom not in output.columns


