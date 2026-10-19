# SPDX-License-Identifier: EUPL-1.2
"""Cleaning-vlaggen op ``measurements`` (ontwerp-preprocessing.md §3, §5).

Principes (§3): nul is een waarde, geen ontbrekende waarde (dus nooit stilzwijgend imputeren);
niets verwijderen zonder vlag; geen harde regel zonder semantische onderbouwing per variabele.
Deze module vlagt dus alleen; filteren/imputeren gebeurt hier expliciet niet.

Werkt sinds ontwerp-intervalsemantiek.md §3 op de FLOW-kolommen (``e_net__W``,
``g_gebruik__m3_s_1``), niet meer op de energiekolommen: delen door een positieve duur verandert
het teken en de nul-eigenschap nooit, dus alle checks hieronder blijven inhoudelijk geldig op de
flow-waarden (zie ontwerp-intervalsemantiek.md §3, "Wat de flow-conversie NIET verandert").
"""

from __future__ import annotations

import pandas as pd

from .quality import constante_reeks_flags, uitschieter_flags

UITSCHIETER_N_SIGMA = 3.0  # voorlopige drempel, zie docs/data-quality.md


def build_quality_table(measurements: pd.DataFrame) -> pd.DataFrame:
    """Bouw de ``quality``-tabel: één rij per measurement-rij met ``<veld>__flag``-kolommen.

    - ``e_net_ontbrekend__flag`` / ``g_gebruik_ontbrekend__flag``: expliciete NaN-vlag. Een 0 is
      een geldige waarde (bv. vakantie, geen verbruik), een NaN is dat niet. Nooit verward. Deze
      twee zijn zelf altijd True/False (``isna()`` is per definitie nooit onbepaald), dus plain
      ``bool``, geen nullable dtype nodig.
    - ``g_gebruik_negatief__flag``: informationeel (§10.3 nog niet bevestigd als brongegeven-regel,
      dus geen filter, alleen een vlag). Nullable ``boolean``: voor een all-electric woning zonder
      `gas`-kolom (§12.1) is "is gas negatief" niet met False te beantwoorden (dat zou "nee,
      gemeten en niet-negatief" impliceren) maar met ``pd.NA`` ("niet van toepassing").
    - ``e_net_constante_reeks__flag`` / ``g_gebruik_constante_reeks__flag``: de HELE reeks van die
      woning+interval_type varieert nooit (std==0); zie
      :func:`im3_preprocessing.quality.constante_reeks_flags` voor waarom dit, ná feedback, een
      lokale "N identieke waarden op een rij"-heuristiek vervangt.
    - ``e_net_uitschieter__flag`` / ``g_gebruik_uitschieter__flag``: > ``UITSCHIETER_N_SIGMA``
      standaarddeviaties van het (woning, interval_type)-gemiddelde, zie
      :func:`im3_preprocessing.quality.uitschieter_flags`.
    """
    quality = measurements[["home_id__str", "tijdstip_start", "interval_type__cat"]].copy()

    quality["e_net_ontbrekend__flag"] = measurements["e_net__W"].isna()
    quality["g_gebruik_ontbrekend__flag"] = measurements["g_gebruik__m3_s_1"].isna()

    gas = measurements["g_gebruik__m3_s_1"]
    quality["g_gebruik_negatief__flag"] = (gas < 0).astype("boolean").mask(gas.isna())

    quality["e_net_constante_reeks__flag"] = constante_reeks_flags(measurements, "e_net__W")
    quality["g_gebruik_constante_reeks__flag"] = constante_reeks_flags(
        measurements, "g_gebruik__m3_s_1"
    )

    quality["e_net_uitschieter__flag"] = uitschieter_flags(
        measurements, "e_net__W", n_sigma=UITSCHIETER_N_SIGMA
    )
    quality["g_gebruik_uitschieter__flag"] = uitschieter_flags(
        measurements, "g_gebruik__m3_s_1", n_sigma=UITSCHIETER_N_SIGMA
    )

    return quality
