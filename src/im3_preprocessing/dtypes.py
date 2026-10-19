# SPDX-License-Identifier: EUPL-1.2
"""Vaste dtypes voor de kolommen met een gesloten waardenverzameling.

Twee redenen om de categorieën hier *vast* te leggen in plaats van ze per DataFrame te laten
afleiden:

1. **Stabiel Parquet-schema bij chunked wegschrijven.** De pipeline verwerkt de dataset in
   chunks van woningen en schrijft die incrementeel weg met één ``ParquetWriter``. Als chunk 1
   toevallig alleen ``q``/``h`` bevat en chunk 2 ook ``d``, dan verschilt het afgeleide
   categorie-dtype tussen de chunks en weigert de writer het tweede blok. Met een vaste
   categorieënlijst is het schema per definitie identiek.
2. **Zelfdocumentatie.** De volledige waardenverzameling staat op één plek, in plaats van impliciet
   in wat de data toevallig laat zien.

Naamgevingsconventie (zie ``docs/variable-dictionary.md``): ``__cat`` = string met lage
cardinaliteit, opgeslagen als pandas ``category``; ``__str`` = vrije/hoog-cardinale string
(alleen ``home_id__str``).
"""

from __future__ import annotations

import pandas as pd

# §2.1: `m` is GEEN maandtotaal maar het gemiddelde dagverbruik van die maand, expliciet zo
# gelabeld, niet stilzwijgend als totaal doorgegeven.
GRANULARITEIT = {
    "q": "kwartier_totaal",
    "h": "uur_totaal",
    "d": "dag_totaal",
    "m": "maand_gemiddeld_per_dag",
}

INTERVAL_TYPE_DTYPE = pd.CategoricalDtype(["q", "h", "d", "m"])
GRANULARITEIT_DTYPE = pd.CategoricalDtype(list(GRANULARITEIT.values()))
WEERKOPPELING_METHODE_DTYPE = pd.CategoricalDtype(
    ["punt_interpolatie", "punt_uur", "gemiddelde_dag", "gemiddelde_maand", "ontbrekend_buiten_archief"]
)
GAS_HHV_BRON_DTYPE = pd.CategoricalDtype(["mijnenergiedata_actueel", "vast_gemiddelde_fallback"])
# `im3` staat hier bewust NIET meer bij: de door RVO per woning gedupliceerde weerreeks wordt sinds
# 26-aug-2026 niet meer weggeschreven (zie ontwerp §12.8). Ze wordt tijdens de run nog wel
# ingelezen voor de consistentiecheck (§7.2), maar belandt niet in de output.
#
# `eigen_ingest` is de rauwe, niet-geïnterpoleerde stationswaarde (ontwerp §12.13);
# `eigen_ingest_geointerpoleerd` is de RBF-geïnterpoleerde variant en komt alleen voor bij
# een expliciete --weer-geointerpoleerd-diagnose-run.
WEER_BRON_DTYPE = pd.CategoricalDtype(["eigen_ingest", "eigen_ingest_geointerpoleerd"])

VASTE_CATEGORIEEN: dict[str, pd.CategoricalDtype] = {
    "interval_type__cat": INTERVAL_TYPE_DTYPE,
    "granulariteit__cat": GRANULARITEIT_DTYPE,
    "weerkoppeling_methode__cat": WEERKOPPELING_METHODE_DTYPE,
    "gas_hhv_bron__cat": GAS_HHV_BRON_DTYPE,
    "bron__cat": WEER_BRON_DTYPE,
}


def pas_vaste_categorieen_toe(df: pd.DataFrame) -> pd.DataFrame:
    """Cast elke bekende ``__cat``-kolom naar zijn vaste categorieënlijst.

    Een waarde die niet in de lijst voorkomt wordt door pandas stil ``NaN``, en dat zou een echt
    defect verbergen, dus hier expliciet gecontroleerd en als fout gemeld.
    """
    for kolom, dtype in VASTE_CATEGORIEEN.items():
        if kolom not in df.columns:
            continue
        # Waarden vóór de cast vasthouden: ná de cast zijn onbekende waarden al NaN geworden en
        # is niet meer te zien wát er stond.
        origineel = df[kolom].astype("object")
        gecast = df[kolom].astype(dtype)
        onbekend = gecast.isna() & origineel.notna()
        if onbekend.any():
            waarden = sorted({str(v) for v in origineel[onbekend].unique()})
            raise ValueError(
                f"Kolom {kolom!r} bevat waarden buiten de vaste categorieënlijst "
                f"{list(dtype.categories)}: {waarden}"
            )
        df[kolom] = gecast
    return df
