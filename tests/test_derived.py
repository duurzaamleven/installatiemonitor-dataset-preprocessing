# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.derived.

Sinds ontwerp-intervalsemantiek.md §3 bevat ``derived`` alleen nog wat een externe koppeling nodig
heeft (de calorische gaswaarde); ``e_net__W`` en de m-rij-vermogenscorrectie (§2) zitten sinds die
wijziging in :mod:`im3_preprocessing.pipeline` (``build_measurements``), niet meer hier. Zie
``tests/test_pipeline.py`` voor die regressietest.
"""

import pandas as pd
import pytest

from im3_preprocessing.derived import build_derived
from im3_preprocessing.gaskwaliteit import GAS_CALORISCHE_WAARDE_FALLBACK__J_M3


def _measurements(g_m3_s_1):
    n = len(g_m3_s_1)
    return pd.DataFrame(
        {
            "home_id__str": ["1"] * n,
            "tijdstip_start": pd.date_range("2023-01-01", periods=n, freq="h", tz="UTC"),
            "interval_type__cat": ["h"] * n,
            "g_gebruik__m3_s_1": g_m3_s_1,
        }
    )


def test_build_derived_kolommen():
    measurements = _measurements([0.001, 0.002])
    derived = build_derived(measurements)
    assert list(derived.columns) == [
        "home_id__str", "tijdstip_start", "interval_type__cat", "g_gebruik__m3_s_1", "g_gebruik__W",
    ]
    assert "e_net__W" not in derived.columns  # zit sinds §3 in measurements, niet meer hier


def test_build_derived_g_gebruik_w_is_volumestroom_maal_calorische_waarde():
    measurements = _measurements([0.001])
    hhv = pd.Series([35.0e6], index=measurements.index, dtype="float32")
    derived = build_derived(measurements, gas_hhv__J_m_3=hhv)
    assert derived["g_gebruik__W"].iloc[0] == pytest.approx(0.001 * 35.0e6, rel=1e-4)


def test_build_derived_zonder_hhv_gebruikt_fallback_constante():
    measurements = _measurements([0.001])
    derived = build_derived(measurements)
    assert derived["g_gebruik__W"].iloc[0] == pytest.approx(
        0.001 * GAS_CALORISCHE_WAARDE_FALLBACK__J_M3, rel=1e-4
    )
