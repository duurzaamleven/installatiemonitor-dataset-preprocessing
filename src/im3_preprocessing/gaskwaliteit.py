# SPDX-License-Identifier: EUPL-1.2
"""Werkelijke calorische waarde van geleverd gas, i.p.v. een vaste Groningen-gas-constante.

``derived.g_gebruik__W`` gebruikte tot 26-aug-2026 een vaste constante
(``GAS_CALORISCHE_WAARDE__MJ_M3 = 35.17``, Groningen-kwaliteit gas) om ``g_gebruik__m3`` om te
rekenen naar vermogen. Op verzoek (zie ook
``needforheat-diagnosis-software/examples/RHC_gas_quality.ipynb`` als inspiratiebron) wordt dit
i.p.v. daarvan zoveel mogelijk direct op de daadwerkelijke, per-uur gepubliceerde calorische
waarde gebaseerd, via een automatische ingest en niet via handmatige CSV-downloads zoals in dat
notebook (die kon toen geen automatische aanroep vinden; zie de API hieronder).

**Bron:** `mijnenergiedata.nl/calorische-gaswaarden <https://www.mijnenergiedata.nl/calorische-gaswaarden/>`_
(EDSN/regionale netbeheerders, maandelijks bijgewerkt). Dit is een **niet publiek gedocumenteerde**
API, ontdekt door de SPA's eigen JS-bundel te inspecteren (``GET .../api/v1/calorificValues
?startMonth=YYYY-MM&endMonth=YYYY-MM``, zonder ``gridArea`` alleen toegestaan als beide maanden
gelijk zijn, en dan worden alle netgebieden tegelijk teruggegeven). Kan zonder aankondiging
wijzigen; dit is een bekend risico, geen garantie zoals bij een gedocumenteerde API.

IM3 levert geen netbeheerder/netgebied per woning (niet een van de 18 metadata-kenmerken), dus een
per-woning-exacte calorische waarde is hieruit niet af te leiden. In lijn met
``RHC_gas_quality.ipynb`` wordt daarom het **NL-gemiddelde over alle netgebieden per uur**
gebruikt: nauwkeuriger dan een vaste jaarconstante, maar geen vervanging voor een echte
netgebied-specifieke waarde.
"""

from __future__ import annotations

import io as _io
import logging

import numpy as np
import pandas as pd

from . import weer as weer_mod
from .timestamps import TZ_LOKAAL, naar_epoch_ns

log = logging.getLogger(__name__)

API_URL = "https://www.mijnenergiedata.nl/calorische-gaswaarden/api/v1/calorificValues"
KOLOM = "actual_gas_std_hhv__J_m_3"  # zelfde naam als needforheat-diagnosis-software (nfh_utils)

# Publieke, gestandaardiseerde fallback-constante (Gaswet-referentiewaarde), alleen gebruikt voor
# rijen waarvoor de werkelijke-waarde-ingest geen dekking heeft (bv. buiten het opgehaalde venster).
GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 = 35.17e6


def _maanden_tussen(start: pd.Timestamp, eind: pd.Timestamp) -> list[str]:
    periode = pd.period_range(start.tz_convert("Europe/Amsterdam"), eind.tz_convert("Europe/Amsterdam"), freq="M")
    return [p.strftime("%Y-%m") for p in periode]


def _fetch_maand(maand: str) -> pd.DataFrame:
    import requests

    resp = requests.get(
        API_URL, params={"startMonth": maand, "endMonth": maand}, headers={"Accept": "*/*"}, timeout=60
    )
    resp.raise_for_status()
    ruw = pd.read_csv(_io.StringIO(resp.text))
    ruw["date_time"] = pd.to_datetime(ruw["date_time"], utc=True)
    # NL-gemiddelde over alle netgebieden per uur (zelfde aanpak als RHC_gas_quality.ipynb); IM3
    # levert geen netgebied per woning, dus dit is de best beschikbare granulariteit.
    per_uur = ruw.groupby("date_time")["value"].mean()
    return pd.DataFrame(
        {"tijdstip": per_uur.index, KOLOM: (per_uur.to_numpy() * 1e6).astype("float32")}
    )


def fetch_actual_gas_hhv(start: pd.Timestamp, eind: pd.Timestamp) -> pd.DataFrame:
    """Haal de werkelijke, NL-gemiddelde calorische waarde van gas op voor ``[start, eind]``.

    Eén request per kalendermaand (de API laat zonder ``gridArea`` maar één maand per keer toe).
    Retourneert ``tijdstip`` (UTC, uurresolutie) + :data:`KOLOM` (float32, J/m³).
    """
    maanden = _maanden_tussen(start, eind)
    frames = []
    for maand in maanden:
        try:
            frames.append(_fetch_maand(maand))
        except Exception as exc:  # netwerkfout of format-wijziging van de niet-gedocumenteerde API
            log.warning("Kon calorische-gaswaarde voor %s niet ophalen (%s); sla over.", maand, exc)

    if not frames:
        return pd.DataFrame(columns=["tijdstip", KOLOM])

    return pd.concat(frames, ignore_index=True).sort_values("tijdstip").reset_index(drop=True)


def couple_gas_hhv_to_measurements(
    measurements: pd.DataFrame, gas_hhv: pd.DataFrame
) -> pd.DataFrame:
    """Koppel de (NL-brede, uur-) calorische-waardereeks aan measurement-rijen, per
    ``interval_type__cat`` op dezelfde manier als weer (§2.3 van het ontwerp): ``h`` exact,
    ``q`` geïnterpoleerd tussen omliggende uren, ``d``/``m`` het gemiddelde over het lokale-
    dag-/maandvenster (zomertijd-aware). Anders dan weer is dit geen per-station reeks, maar één
    landelijke reeks voor alle woningen, dus geen groepering per station nodig.

    Rijen buiten het opgehaalde venster (of als de ingest is overgeslagen) krijgen
    :data:`GAS_CALORISCHE_WAARDE_FALLBACK__J_M3` met ``gas_hhv_bron__cat="vast_gemiddelde_fallback"``
    i.p.v. een lege waarde; de vaste constante blijft dus de terugvaloptie, nooit de eerste keus.
    """
    n = len(measurements)
    hhv = np.full(n, np.nan)

    if not gas_hhv.empty:
        interval = np.asarray(measurements["interval_type__cat"].astype(str))
        tijdstip_start = measurements["tijdstip_start"]
        # Overal epoch-ns als sleutel: eenduidig UTC, en het voorkomt dat een lookup van tz-naive
        # numpy-waarden tegen een tz-aware index terugvalt op trage object-vergelijking.
        tijd_ns = naar_epoch_ns(tijdstip_start)
        # gas_hhv is een losstaande, per-uur brontabel (niet een van de drie herziene
        # output-tabellen); de eigen "tijdstip"-kolom daarvan blijft ongewijzigd.
        reeks = gas_hhv.set_index("tijdstip")[KOLOM].sort_index()
        reeks_ns = pd.Series(reeks.to_numpy(), index=naar_epoch_ns(reeks.index))

        rijen = np.flatnonzero(interval == "h")
        if len(rijen):
            hhv[rijen] = reeks_ns.reindex(tijd_ns[rijen]).to_numpy()

        rijen = np.flatnonzero(interval == "q")
        if len(rijen):
            hhv[rijen] = np.interp(
                tijd_ns[rijen], reeks_ns.index.to_numpy(), reeks_ns.to_numpy(),
                left=np.nan, right=np.nan,
            )

        # d/m: vectorized via een gemiddelde per lokale kalenderdag/-maand i.p.v. een Python-loop
        # met een mask per rij: zelfde ingreep en zelfde exacte uitkomst als bij
        # :func:`im3_preprocessing.weer.couple_weather_to_measurements`, zie daar voor de
        # onderbouwing (inclusief waarom de zomertijd-correctheid behouden blijft).
        bron_dag = weer_mod._lokale_dagsleutel(reeks.index.tz_convert(TZ_LOKAAL))
        for itv in ("d", "m"):
            rijen = np.flatnonzero(interval == itv)
            if not len(rijen):
                continue
            bron_sleutel = bron_dag if itv == "d" else weer_mod._lokale_maandsleutel(bron_dag)
            gemiddelden = pd.Series(reeks.to_numpy()).groupby(bron_sleutel).mean()

            dag = weer_mod._lokale_dagsleutel(tijdstip_start.iloc[rijen].dt.tz_convert(TZ_LOKAAL))
            sleutel = dag if itv == "d" else weer_mod._lokale_maandsleutel(dag)
            hhv[rijen] = gemiddelden.reindex(sleutel).to_numpy()

    ontbrekend = np.isnan(hhv)
    hhv[ontbrekend] = GAS_CALORISCHE_WAARDE_FALLBACK__J_M3

    resultaat = measurements[["home_id__str", "tijdstip_start", "interval_type__cat"]].copy()
    resultaat[KOLOM] = hhv.astype("float32")
    resultaat["gas_hhv_bron__cat"] = pd.Categorical(
        np.where(ontbrekend, "vast_gemiddelde_fallback", "mijnenergiedata_actueel")
    )
    return resultaat
