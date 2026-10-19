# SPDX-License-Identifier: EUPL-1.2
"""``interval_duur__s`` per rij, nooit hardcoded voor ``d``/``m`` (ontwerp-preprocessing.md §2.4).

Een hardcoded 86400 voor ``d``-rijen geeft op de twee jaarlijkse zomertijdovergangsdagen een
systematische fout van ±4% in elke op duur gebaseerde afleiding (bijv. ``g_gebruik__W``). Deze
module leidt de duur daarom altijd af uit het echte lokale-tijdvenster (Europe/Amsterdam-aware).
"""

from __future__ import annotations

import pandas as pd

from .timestamps import local_day_window, local_month_window

# q/h: UTC kent geen zomertijd, dus deze duur is altijd exact.
INTERVAL_DUUR_S_VAST = {"q": 900, "h": 3600}

J_PER_KWH = 3_600_000
DAG_S = 86_400


def compute_energie_deler_s(interval_type: pd.Series, interval_duur__s: pd.Series) -> pd.Series:
    """Deler in seconden voor de energie->vermogen-omzetting (ontwerp-intervalsemantiek.md §2).

    Voor ALLE intervaltypen behalve ``m`` is de deler gewoon ``interval_duur__s``: de gerapporteerde
    energie is een echt totaal over dat interval. Voor ``m`` is de gerapporteerde waarde volgens
    ontwerp-preprocessing.md §2.1 GEEN maandtotaal maar het GEMIDDELDE DAGVERBRUIK van die maand
    (zie ``dtypes.GRANULARITEIT["m"] == "maand_gemiddeld_per_dag"``). Delen door de maandduur zou
    de vermogens van ``m``-rijen dus stelselmatig een factor ~30 te laag maken (op de volledige
    dataset gemeten: 28-31x, zie ontwerp-intervalsemantiek.md §2); de juiste deler is één dag
    (86.400 s), niet ``interval_duur__s``.

    ``interval_duur__s`` zelf blijft overal ongewijzigd: die beschrijft correct de lengte van het
    interval waar de rij over gaat. Het is uitsluitend de deler voor de vermogens-afleiding die
    hier voor ``m`` afwijkt.
    """
    return interval_duur__s.where(interval_type != "m", DAG_S).astype("int32")


def _window_duur_s(local_date, window_fn) -> int:
    start, eind = window_fn(local_date)
    return int((eind - start).total_seconds())


def compute_interval_duur_s(datetime_raw: pd.Series, interval_type: pd.Series) -> pd.Series:
    """Vectorized ``interval_duur__s``.

    - ``q``/``h``: vaste duur (900 / 3600 s).
    - ``d``: duur van de lokale kalenderdag zelf: 86400 s, behalve 82800 s (23h,
      voorjaarsovergang) of 90000 s (25h, najaarsovergang).
    - ``m``: duur van de lokale kalendermaand (28-31 dagen), zelf ook zomertijd-aware berekend.
      Een maand met een DST-overgang erin is 1 uur korter/langer dan een naïeve dagenteller zou
      geven.

    Berekeningen per unieke datum worden gecachet (niet per rij herhaald): ``d``/``m``-datums
    komen over duizenden woningen heen vaak voor.

    Retourneert plain ``int32`` (niet nullable ``Int64``): elke geldige ``interval_type`` (q/h/d/m,
    afgedwongen door :func:`im3_preprocessing.io.read_customer_stream`) wordt hier exhaustief
    gevuld, dus een NaN zou een echte bug zijn, vandaar de expliciete check ipv. een stil
    nullable resultaat. int32 volstaat: het grootste geval (31-dagen-maand) is ~2,68 miljoen
    seconden, ruim binnen int32 (max ~2,15 miljard) en ver buiten int16 (max 32.767).
    """
    # Tijdens opbouw nog nullable: zo is aan het eind met .isna() te zien of echt elke rij
    # geraakt is door één van de vier maskers hieronder: geen aanname, een check.
    result = pd.Series(pd.NA, index=datetime_raw.index, dtype="Int64")

    for itv, duur in INTERVAL_DUUR_S_VAST.items():
        mask = interval_type == itv
        if mask.any():
            result.loc[mask] = duur

    mask_d = interval_type == "d"
    if mask_d.any():
        dates = pd.to_datetime(datetime_raw.loc[mask_d]).dt.date
        cache = {d: _window_duur_s(d, local_day_window) for d in dates.unique()}
        result.loc[mask_d] = dates.map(cache).to_numpy()

    mask_m = interval_type == "m"
    if mask_m.any():
        dates = pd.to_datetime(datetime_raw.loc[mask_m]).dt.date
        cache = {d: _window_duur_s(d, local_month_window) for d in dates.unique()}
        result.loc[mask_m] = dates.map(cache).to_numpy()

    if result.isna().any():
        onbekend = sorted(interval_type[result.isna()].unique())
        raise ValueError(f"interval_duur__s niet bepaald voor interval_type {onbekend}")

    return result.astype("int32")
