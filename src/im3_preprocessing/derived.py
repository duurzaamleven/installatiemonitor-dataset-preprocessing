# SPDX-License-Identifier: EUPL-1.2
"""Afgeleide gasgrootheden: vermogen uit volumestroom x calorische waarde
(ontwerp-preprocessing.md §3 principe 1, §8; ontwerp-intervalsemantiek.md §3).

``e_net__W`` staat sinds ontwerp-intervalsemantiek.md §3 in ``measurements`` (het is een
aannamevrije conversie, geen externe koppeling nodig) en dus niet meer hier; zie
:func:`im3_preprocessing.pipeline.build_measurements`. Deze module voegt alleen toe wat een
externe waarde nodig heeft: de calorische gaswaarde om ``g_gebruik__m3_s_1`` (al aanwezig in
``measurements``, aannamevrij) om te rekenen naar ``g_gebruik__W``.

Bewust NIET hier: H/C/τ-schatting, COP-modellen, warmtepomp-disaggregatie. Dat is fysische
modellering, geen preprocessing (§8), en hoort in een aparte analysemodule.
"""

from __future__ import annotations

import pandas as pd

from .gaskwaliteit import GAS_CALORISCHE_WAARDE_FALLBACK__J_M3


def build_derived(
    measurements: pd.DataFrame,
    gas_hhv__J_m_3: pd.Series | None = None,
) -> pd.DataFrame:
    """``home_id__str, tijdstip_start, interval_type__cat, g_gebruik__m3_s_1, g_gebruik__W``.

    ``g_gebruik__m3_s_1`` (volumestroom) wordt hier ongewijzigd overgenomen uit ``measurements``
    (al aannamevrij afgeleid, inclusief de §2-correctie voor ``m``-rijen). ``g_gebruik__W`` is de
    enige kolom die hier daadwerkelijk wordt uitgerekend: volumestroom [m³/s] x calorische waarde
    [J/m³] = vermogen [W], zonder nog een keer door een duur te hoeven delen.

    ``gas_hhv__J_m_3``: optionele, per-rij werkelijke calorische waarde (J/m³), uitgelijnd op
    ``measurements.index``. Zie :mod:`im3_preprocessing.gaskwaliteit` voor de automatische ingest
    van de daadwerkelijke, per-uur gepubliceerde waarde i.p.v. een vaste jaarconstante. Zonder dit
    argument (bv. in losse tests, of wanneer de ingest is overgeslagen) valt dit terug op
    :data:`im3_preprocessing.gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3` voor alle rijen.
    """
    derived = measurements[
        ["home_id__str", "tijdstip_start", "interval_type__cat", "g_gebruik__m3_s_1"]
    ].copy()

    if gas_hhv__J_m_3 is None:
        gas_hhv__J_m_3 = pd.Series(
            GAS_CALORISCHE_WAARDE_FALLBACK__J_M3, index=measurements.index, dtype="float32"
        )

    # NB: float32 (array) vermenigvuldigd met float32 blijft float32; expliciete .astype("float32")
    # hier vooral om nullable/object-invoer (bv. losse tests) niet stilzwijgend naar float64 te
    # laten promoten.
    derived["g_gebruik__W"] = (
        measurements["g_gebruik__m3_s_1"] * gas_hhv__J_m_3
    ).astype("float32")

    return derived
