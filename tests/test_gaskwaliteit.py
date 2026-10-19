# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.gaskwaliteit."""

import numpy as np
import pandas as pd
import pytest

from im3_preprocessing.gaskwaliteit import (
    GAS_CALORISCHE_WAARDE_FALLBACK__J_M3,
    KOLOM,
    _maanden_tussen,
    couple_gas_hhv_to_measurements,
    fetch_actual_gas_hhv,
)


def test_maanden_tussen_binnen_een_maand():
    start = pd.Timestamp("2024-01-05", tz="UTC")
    eind = pd.Timestamp("2024-01-20", tz="UTC")
    assert _maanden_tussen(start, eind) == ["2024-01"]


def test_maanden_tussen_over_jaargrens():
    start = pd.Timestamp("2023-12-15", tz="UTC")
    eind = pd.Timestamp("2024-02-05", tz="UTC")
    assert _maanden_tussen(start, eind) == ["2023-12", "2024-01", "2024-02"]


def test_couple_gas_hhv_zonder_data_valt_terug_op_constante():
    metingen = pd.DataFrame(
        [{"home_id__str": "1", "tijdstip_start": pd.Timestamp("2024-01-01", tz="UTC"), "interval_type__cat": "h"}]
    )
    resultaat = couple_gas_hhv_to_measurements(metingen, pd.DataFrame(columns=["tijdstip", KOLOM]))
    assert resultaat[KOLOM].iloc[0] == pytest.approx(GAS_CALORISCHE_WAARDE_FALLBACK__J_M3)
    assert resultaat["gas_hhv_bron__cat"].iloc[0] == "vast_gemiddelde_fallback"


def test_couple_gas_hhv_punt_uur_en_interpolatie_en_fallback_buiten_venster():
    uren = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    gas_hhv = pd.DataFrame({"tijdstip": uren, KOLOM: np.array([35.0e6, 35.1e6, 35.2e6, 35.3e6, 35.4e6], dtype="float32")})

    metingen = pd.DataFrame(
        [
            {"home_id__str": "1", "tijdstip_start": uren[1], "interval_type__cat": "h"},
            {"home_id__str": "1", "tijdstip_start": uren[1] + pd.Timedelta(minutes=30), "interval_type__cat": "q"},
            {"home_id__str": "1", "tijdstip_start": uren[-1] + pd.Timedelta(days=10), "interval_type__cat": "h"},
        ]
    )
    resultaat = couple_gas_hhv_to_measurements(metingen, gas_hhv)

    assert resultaat[KOLOM].iloc[0] == pytest.approx(35.1e6, rel=1e-4)
    assert resultaat["gas_hhv_bron__cat"].iloc[0] == "mijnenergiedata_actueel"

    assert resultaat[KOLOM].iloc[1] == pytest.approx(35.15e6, rel=1e-4)

    # Ver buiten het opgehaalde venster -> terugval op de vaste constante, niet leeg.
    assert resultaat[KOLOM].iloc[2] == pytest.approx(GAS_CALORISCHE_WAARDE_FALLBACK__J_M3, rel=1e-4)
    assert resultaat["gas_hhv_bron__cat"].iloc[2] == "vast_gemiddelde_fallback"


@pytest.mark.network
def test_fetch_actual_gas_hhv_live():
    start = pd.Timestamp("2024-01-05", tz="UTC")
    eind = pd.Timestamp("2024-01-06", tz="UTC")
    result = fetch_actual_gas_hhv(start, eind)
    assert not result.empty
    # Aardgas ligt qua calorische waarde (bovenwaarde) in de praktijk ergens tussen 30 en 40 MJ/m^3.
    assert result[KOLOM].between(30e6, 40e6).all()
