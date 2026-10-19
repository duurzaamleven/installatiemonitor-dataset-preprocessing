# SPDX-License-Identifier: EUPL-1.2
"""Tijdstempel-resolutie voor IM3-rijen (zie ontwerp-preprocessing.md §1, §2.3, §2.4, en
ontwerp-intervalsemantiek.md §1/§4 voor de begin-van-interval-conventie hieronder).

RVO's eigen (bron-)intervalsemantiek is NIET uniform over de vier intervaltypen:

- ``q``/``h``: ``datetime`` is een tz-aware UTC-tijdstip aan het **einde** van het interval.
- ``d``:       ``datetime`` is een kale lokale datum (Europe/Amsterdam), verankerd aan het
  **begin** van die kalenderdag.
- ``m``:       ``datetime`` is een kale lokale datum (de laatste dag van de maand), verankerd aan
  het begin van die dag (00:00 lokale tijd) -- dus NOCH het begin, NOCH het einde van de maand
  waar de rij over gaat.

Deze bronconventie is intern inconsistent en voor ``m`` ronduit onbruikbaar (``tijdstip_start +
interval_duur__s`` zou op de verkeerde dag uitkomen). :func:`resolve_timestamps` rekent daarom
alles om naar één uniforme conventie voor de OUTPUT-kolom ``tijdstip_start``: het begin van het
interval, voor alle vier de typen (ontwerp-intervalsemantiek.md §1, "Keuze: begin van het
interval"). ``tijdstip_start + interval_duur__s`` is na deze omzetting altijd het einde van het
bedoelde interval.

Bovendien is een lokale kalenderdag/-maand niet altijd 24h*n vanwege zomertijd (§2.4): de nacht van
de voorjaarsovergang telt lokaal 23 uur, de najaarsovergang 25 uur. Daarom wordt hier nergens een
vaste duur aangenomen voor ``d``/``m``: alles wordt afgeleid uit het echte lokale-tijdvenster.

Let op: dit is bewust een eigen, kleine implementatie. Er bestaat elders vergelijkbare
zomertijd-correcte tijdas-code, maar niet onder een licentie die hergebruik hier toestaat; zie
ontwerp-preprocessing.md §2.4, kanttekening.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd

# Europe/Amsterdam als lokale tijdzone is onderbouwd, niet aangenomen; zie
# ontwerp-preprocessing.md §12.10 voor het bewijs (alle 6.283 woningen hangen aan een van 28
# Europees-Nederlandse KNMI-stations, en de ISDE-regeling waar deze dataset op leunt geldt
# uitsluitend voor Europees Nederland; Caribisch Nederland kent AST/UTC-4 zonder zomertijd en zou
# hier dus fout gelabeld worden).
TZ_LOKAAL = "Europe/Amsterdam"

VALID_INTERVAL_TYPES = ("q", "h", "d", "m")


def naar_lokale_tijdzone(
    df: pd.DataFrame, kolommen: tuple[str, ...] = ("tijdstip", "tijdstip_start")
) -> pd.DataFrame:
    """Zet tz-aware tijdkolommen om naar :data:`TZ_LOKAAL` voor de uiteindelijke output.

    ``tz_convert`` verandert het **instant** niet, alleen hoe het wordt weergegeven. De kolom
    blijft dus tz-aware, zodat zowel de lokale tijd (direct afleesbaar, en dát is wat menselijk
    gedrag stuurt) als de absolute tijd (één ``.dt.tz_convert("UTC")`` verderop) beschikbaar
    blijft. Intern rekent de pipeline in UTC; deze omzetting gebeurt pas vlak vóór het
    wegschrijven.

    Standaard beide mogelijke kolomnamen: ``measurements``/``quality``/``derived`` heten
    ``tijdstip_start`` (ontwerp-intervalsemantiek.md §1), maar ``weer.parquet`` heet bewust nog
    ``tijdstip`` (§4, "Wat er NIET verandert" -- dat is geen interval, maar een KNMI-uurpunt). Een
    tabel heeft er nooit meer dan één van; de andere wordt hierboven stil overgeslagen (``kolom
    not in df.columns``), dus dit is veilig te combineren.
    """
    for kolom in kolommen:
        if kolom not in df.columns:
            continue
        serie = df[kolom]
        if not isinstance(serie.dtype, pd.DatetimeTZDtype):
            raise ValueError(
                f"Kolom {kolom!r} is niet tz-aware ({serie.dtype}); omzetten naar {TZ_LOKAAL} zou "
                "raden zijn naar de bedoelde tijdzone in plaats van hem alleen anders weergeven."
            )
        df[kolom] = serie.dt.tz_convert(TZ_LOKAAL)
    return df


def naar_epoch_ns(tijdstip) -> "np.ndarray":
    """Epoch-nanoseconden, ongeacht de tijdresolutie van de aangeleverde reeks.

    ``astype("int64")`` op een datetime-reeks geeft het getal in de **eigen** resolutie van die
    reeks: bij ``datetime64[ns]`` nanoseconden, bij ``datetime64[us]`` microseconden. Dat scheelt
    een factor 1000, en twee reeksen met verschillende resolutie zijn daardoor stilzwijgend
    onvergelijkbaar geworden zodra je op die integers matcht of interpoleert.

    Dat is precies wat er misging (ontwerp §12.14): ``measurements.tijdstip`` is
    ``datetime64[ns]``, maar de KNMI-reeks kwam als ``datetime64[us]`` uit de externe library.
    De exacte match voor ``h``-rijen kon dus nooit slagen en ``np.interp`` legde alle ``q``-rijen
    rechts buiten het bereik, wat met ``right=np.nan`` overal NaN gaf. Er kwam geen enkele
    foutmelding: de rijen kregen netjes ``ontbrekend_buiten_archief`` mee, wat een geldige
    uitkomst is en dus niets verraadde.

    Deze functie dwingt daarom altijd nanoseconden af, in plaats van erop te vertrouwen dat elke
    bron dezelfde resolutie levert.
    """
    serie = tijdstip if isinstance(tijdstip, pd.Series) else pd.Series(tijdstip)
    if not isinstance(serie.dtype, pd.DatetimeTZDtype):
        raise ValueError(
            f"Verwacht een tz-aware datetime-reeks, kreeg {serie.dtype}; zonder tijdzone is een "
            "epoch-omzetting een gok naar de bedoelde tijdzone."
        )
    return serie.dt.as_unit("ns").astype("int64").to_numpy()


def local_day_window(
    local_date: _dt.date, tz: str = TZ_LOKAAL
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC-venster ``[start, eind)`` van één lokale kalenderdag, zomertijd-aware.

    ``local_date`` is de kalenderdag zelf, geen tijdstip. Middernacht lokale tijd is in
    Europe/Amsterdam nooit ambigu of niet-bestaand: de DST-overgang valt op 02:00-03:00 lokaal,
    niet om 00:00, dus er is hier geen ``ambiguous``/``nonexistent``-keuze nodig.
    """
    start_naive = pd.Timestamp(local_date)
    end_naive = start_naive + pd.Timedelta(days=1)
    start_utc = start_naive.tz_localize(tz).tz_convert("UTC")
    end_utc = end_naive.tz_localize(tz).tz_convert("UTC")
    return start_utc, end_utc


def local_month_window(
    local_date: _dt.date, tz: str = TZ_LOKAAL
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC-venster ``[start, eind)`` van de lokale kalendermaand waarin ``local_date`` valt.

    RVO levert bij ``m``-rijen de laatste dag van de maand aan; deze functie geeft het venster
    van de hele maand (nodig om de duur in seconden te bepalen, §2.4).
    """
    period = pd.Timestamp(local_date).to_period("M")
    start_naive = period.start_time
    end_naive = (period + 1).start_time
    start_utc = start_naive.tz_localize(tz).tz_convert("UTC")
    end_utc = end_naive.tz_localize(tz).tz_convert("UTC")
    return start_utc, end_utc


# q/h: UTC kent geen zomertijd, dus deze aftrek is altijd exact 900/3600 s, ook op een
# zomertijd-overgangsdag (ontwerp-intervalsemantiek.md §4).
_DUUR_VAST_S = {"q": pd.Timedelta(seconds=900), "h": pd.Timedelta(seconds=3600)}


def resolve_timestamps(datetime_raw: pd.Series, interval_type: pd.Series) -> pd.Series:
    """Vectorized: reken RVO's ``datetime``-kolom om naar één tz-aware UTC ``tijdstip_start``-kolom,
    het BEGIN van het interval, ongeacht ``interval_type`` (ontwerp-intervalsemantiek.md §4).

    Per intervaltype, en NIET uniform (``tijdstip_start = datetime_raw - interval_duur__s`` klopt
    alleen voor ``q``/``h``):

    - ``q``/``h``: ``datetime_raw`` is een tz-aware UTC-tijdstip aan het EIND van het interval
      (RVO's bronconventie); het begin is dat tijdstip min de vaste duur (900 / 3600 s). De aftrek
      gebeurt op de absolute (UTC-)instant, dus zomertijd-neutraal.
    - ``d``: ``datetime_raw`` is al een kale lokale datum = begin van die dag (RVO's bronconventie
      is hier toevallig al begin-gelabeld); lokaliseren + naar UTC converteren.
    - ``m``: ``datetime_raw`` is een kale lokale datum, maar de LAATSTE dag van de maand (RVO's
      bronconventie), niet de eerste. ``tijdstip_start`` wordt hier daarom de EERSTE dag van
      diezelfde lokale maand, 00:00 lokaal -- expliciet NIET ``datetime_raw`` zelf (dat zou het
      begin van de laatste dag zijn, niet het begin van de maand) en ook NIET
      ``datetime_raw - interval_duur__s`` (dat zou de vorige maand ingaan). Middernacht op de 1e
      van een maand is in Europe/Amsterdam nooit ambigu of niet-bestaand (dezelfde redenering als
      :func:`local_day_window`).

    Onbekende ``interval_type``-waarden leveren een ``ValueError`` op: dit hoort niet stil te
    falen, want het raakt de rest van de pijplijn.
    """
    onbekend = ~interval_type.isin(VALID_INTERVAL_TYPES)
    if onbekend.any():
        raise ValueError(
            f"Onbekende interval_type-waarden aangetroffen: {sorted(interval_type[onbekend].unique())}"
        )

    result = pd.Series(pd.NaT, index=datetime_raw.index, dtype="datetime64[ns, UTC]")

    for itv, duur in _DUUR_VAST_S.items():
        mask = interval_type == itv
        if mask.any():
            result.loc[mask] = pd.to_datetime(datetime_raw.loc[mask], utc=True) - duur

    mask_d = interval_type == "d"
    if mask_d.any():
        # Kale lokale datum -> lokaal middernacht -> UTC. Vectorized; middernacht is nooit
        # ambigu/niet-bestaand in Europe/Amsterdam (zie module-docstring hierboven).
        naive = pd.to_datetime(datetime_raw.loc[mask_d])
        result.loc[mask_d] = naive.dt.tz_localize(TZ_LOKAAL).dt.tz_convert("UTC")

    mask_m = interval_type == "m"
    if mask_m.any():
        # Kale lokale datum (laatste dag van de maand) -> eerste dag van diezelfde maand, lokaal
        # middernacht -> UTC. ``to_period("M").to_timestamp()`` geeft de eerste dag van de maand
        # als naive Timestamp (zelfde aanpak als local_month_window).
        naive = pd.to_datetime(datetime_raw.loc[mask_m])
        eerste_van_maand = naive.dt.to_period("M").dt.to_timestamp()
        result.loc[mask_m] = eerste_van_maand.dt.tz_localize(TZ_LOKAAL).dt.tz_convert("UTC")

    return result
