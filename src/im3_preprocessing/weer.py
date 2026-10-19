# SPDX-License-Identifier: EUPL-1.2
"""Weer: IM3-geleverde kolommen + eigen, reproduceerbare KNMI-ingest (ontwerp-preprocessing.md §5.1, §7.2, §7.3, §12.13).

Weer hoort niet in ``measurements.parquet`` (het is per-woning gedenormaliseerd brongegeven, §5.1)
maar in een eigen, op ``(weerstation_nr, tijdstip)`` genormaliseerde tabel met een eigen bron naast
de IM3-geleverde reeks (``bron__cat``): ``"im3"`` (RVO-geleverd) en ``"eigen_ingest"`` (zelf
opgehaald, via ``needforheat-dutch-weather-software``, Apache 2.0). ``"eigen_ingest"`` is sinds
§12.13 bewust de **rauwe, niet-geïnterpoleerde** waarde van het KNMI-station zelf
(:func:`fetch_own_weather_direct`), géén RBF-geospatiale interpolatie: er wordt altijd de eigen
coördinaat van een bekend station opgevraagd, nooit een willekeurig GPS-punt, en voor precies dat
geval is RBF-interpolatie een dure omweg naar hetzelfde antwoord (zie hieronder).

Geospatiale interpolatie (:func:`fetch_own_weather`, bron ``"eigen_ingest_geointerpoleerd"``)
bestaat nog wél, maar wordt niet standaard aangeroepen. Ze is opt-in via
``--weer-geointerpoleerd-diagnose`` en dient alleen om de §12.4-vraag (ligt een consistentie-
mismatch aan de interpolatiestap zelf?) opnieuw te kunnen beantwoorden, of als bouwsteen voor
toekomstig werk dat wél naar een echt GPS-punt interpoleert (§7.3, kanttekening).

Volgorde, niet-omkeerbaar (§7.3): eerst de consistentiecheck (:func:`consistency_check`), pas bij
een goede match de eigen ingest als primaire bron gebruiken.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

from .timestamps import TZ_LOKAAL, naar_epoch_ns

# --- IM3-geleverde weer (§5.1) -----------------------------------------------------------------


def sun_kWh_m2_naar_W_m2(sun__kWh_m_2: pd.Series, interval_duur__s: pd.Series) -> pd.Series:
    """RVO's ``sun`` (gesommeerde instraling in kWh/m2 over het interval) naar de gemiddelde
    instraling in W/m2 over dat interval: ``sun x 1000 / (interval_duur__s / 3600)``.

    Voorbeeld: 0,5 kWh/m2 in een uur is gemiddeld 500 W/m2; in een kwartier 2000 W/m2.
    """
    return sun__kWh_m_2 * 1000.0 / (interval_duur__s / 3600.0)


def extract_im3_weather(measurements_raw: pd.DataFrame, homes: pd.DataFrame) -> pd.DataFrame:
    """Haal de per-woning gedupliceerde IM3-weerkolommen (``wind``, ``temp``, ``sun``) uit de
    ruwe measurement-rijen en normaliseer naar ``(weerstation_nr, tijdstip)``.

    RVO's weer staat in de steekproef alleen op ``h``-rijen gevuld (ontwerp §1); rijen zonder een
    gevulde weerwaarde worden hier al genegeerd. ``measurements_raw`` moet een resolved UTC
    ``tijdstip``-kolom hebben (zie :mod:`im3_preprocessing.timestamps`).
    """
    weer_kolommen = ["wind", "temp", "sun"]
    heeft_weer = measurements_raw[weer_kolommen].notna().any(axis=1)
    # Output-kolom blijft "tijdstip" (niet "tijdstip_start"): deze tabel is geen van de drie
    # herziene output-tabellen, en moet direct mergen met weer_tabel (eigen KNMI-ingest), die zijn
    # eigen "tijdstip"-kolom ongewijzigd behoudt (ontwerp-intervalsemantiek.md §4, "Wat er NIET
    # verandert" -- weer.parquet blijft ongewijzigd).
    df = measurements_raw.loc[
        heeft_weer, ["home_id__str", "tijdstip_start", "interval_duur__s"] + weer_kolommen
    ].copy()
    df = df.rename(columns={"tijdstip_start": "tijdstip"})
    df = df.merge(
        homes[["home_id__str", "weerstation_nr"]], on="home_id__str", how="left", validate="m:1"
    )
    # "sun" is volgens RVO "gesommeerde zoninstraling" in kWh/m2 over het interval (informatie-
    # document, variabelentabel), dus een energietotaal per interval en geen gemiddelde instraling.
    # De waarden bevestigen dat: ze zijn veelvouden van 1/360 (1 J/cm2 = 10 kJ/m2 = 1/360 kWh/m2,
    # de resolutie van KNMI's Q-veld) en lopen tot ongeveer 0,94. Omrekenen naar gemiddelde W/m2,
    # dezelfde eenheid als de eigen KNMI-ingest: x 1000 (kW -> W) en delen door de duur in uren.
    # Weer staat in de bron alleen op h-rijen (duur 1 uur); de deling maakt de omrekening ook
    # correct als dat ooit anders is.
    df["sun"] = sun_kWh_m2_naar_W_m2(df["sun"], df["interval_duur__s"])
    df = df.drop(columns="interval_duur__s").rename(
        columns={"wind": "wind__m_s_1", "temp": "temp_buiten__degC", "sun": "ghi__W_m_2"}
    )

    # Verificatie van de §5.1-bevinding (0 verschillen tussen woningen op hetzelfde station): als
    # dat binnen deze run niet klopt, is dat zelf een bevinding, geen stille aggregatie-keuze.
    n_varianten = df.groupby(["weerstation_nr", "tijdstip"])["temp_buiten__degC"].nunique()
    afwijkende_groepen = int((n_varianten > 1).sum())

    genormaliseerd = (
        df.groupby(["weerstation_nr", "tijdstip"])[["temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2"]]
        .first()
        .reset_index()
    )
    # float32 (zelfde precisie-keuze als de meetwaarden, zie pipeline.build_measurements) en
    # category voor bron__cat (twee vaste waarden: "im3"/"eigen_ingest").
    for veld in ("temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2"):
        genormaliseerd[veld] = genormaliseerd[veld].astype("float32")
    genormaliseerd["weerstation_nr"] = genormaliseerd["weerstation_nr"].astype("int16")
    genormaliseerd["bron__cat"] = pd.Series("im3", index=genormaliseerd.index, dtype="category")
    genormaliseerd.attrs["afwijkende_groepen_meerdere_temp_waarden"] = afwijkende_groepen
    return genormaliseerd


# --- Eigen KNMI-ingest (§7.3) ------------------------------------------------------------------

METRICS = {
    "T": ("temp_buiten__degC", 0.1),
    "FH": ("wind__m_s_1", 0.1),
    "Q": ("ghi__W_m_2", (100 * 100) / (60 * 60)),
}


def get_station_coordinates(peildatum: str = "20240101") -> pd.DataFrame:
    """STN -> (LON, LAT) voor alle KNMI-stations, uit het header-blok van het KNMI-uurbestand.

    Kleine, losstaande parser met dezelfde aanpak als
    ``dutch_weather.knmi.process_knmi_weather_data`` (Apache 2.0, © Windesheim/@henriterhofte),
    hier apart geïmplementeerd omdat die functie de STN-kolom na het mergen weggooit, terwijl wij
    'm net nodig hebben om `Weerstation_nr` (IM3) aan een coördinaat te koppelen (§7.3: interpoleren
    naar de coördinaat van hetzelfde station, niet naar een GPS-punt).
    """
    from dutch_weather.knmi import download_knmi_uurgegevens

    raw = download_knmi_uurgegevens(peildatum, peildatum, metrics=["T"])
    lines = raw.splitlines()[5:]
    station_lines = [lines[0].lstrip("# ")]
    for line in lines:
        if re.match(r"^# \d{3}", line):
            station_lines.append(line.lstrip("# "))
        elif line.startswith("# STN,YYYYMMDD"):
            break

    df_stations = pd.read_fwf(io.StringIO("\n".join(station_lines)))
    df_stations.columns = df_stations.columns.str.replace(r"\(.*\)", "", regex=True).str.strip()
    return df_stations.set_index("STN")[["LON", "LAT"]].rename(
        columns={"LON": "lon__degE", "LAT": "lat__degN"}
    )


WEER_KOLOMMEN = ["weerstation_nr", "tijdstip", "temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2", "bron__cat"]


def fetch_ruwe_stationsdata(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Eénmalige ophaal van alle-stations-uurdata voor ``[start, end]`` (Apache 2.0,
    ``dutch_weather.knmi.fetch_hourly_dutch_weather_data``); de basis voor zowel de
    geïnterpoleerde (:func:`fetch_own_weather`) als de directe (:func:`fetch_own_weather_direct`)
    variant, zodat beide op precies dezelfde brondata werken en het netwerk maar één keer wordt
    aangesproken.
    """
    from dutch_weather.knmi import fetch_hourly_dutch_weather_data

    interval = pd.Interval(left=start, right=end, closed="both")
    return fetch_hourly_dutch_weather_data(interval, metrics=METRICS)


def _naar_weer_kolommen(breed: pd.DataFrame, stn: int, bron: str) -> pd.DataFrame:
    breed = breed.copy()
    # Q is Wh/m^2 per uur, numeriek gelijk aan het gemiddelde vermogen (W/m^2) over dat uur: een
    # flow, geen energietotaal. Sinds ontwerp-intervalsemantiek.md §3 blijft dit dus ongedeeld
    # W/m^2 i.p.v. eerder (foutief) naar kWh/m^2 om te rekenen.
    breed["ghi__W_m_2"] = breed["ghi__W_m_2"].astype("float32")
    breed["temp_buiten__degC"] = breed["temp_buiten__degC"].astype("float32")
    breed["wind__m_s_1"] = breed["wind__m_s_1"].astype("float32")
    breed["weerstation_nr"] = pd.array([stn] * len(breed), dtype="int16")
    breed["bron__cat"] = pd.Series(bron, index=breed.index, dtype="category")
    uit = breed.reset_index().rename(columns={"timestamp": "tijdstip"})
    # Naar ns-resolutie, gelijk aan measurements: de externe KNMI-library levert us, en dat
    # verschil brak stilzwijgend de h/q-koppeling (§12.14). Hier bij de bron rechtzetten, zodat
    # ook weer.parquet dezelfde resolutie krijgt als de andere tabellen.
    uit["tijdstip"] = uit["tijdstip"].dt.as_unit("ns")
    return uit


def fetch_own_weather(
    start: pd.Timestamp,
    end: pd.Timestamp,
    station_coords: dict[int, tuple[float, float]],
    interpolate__min: int = 60,
    df_alle_stations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Eigen KNMI-ingest, geospatiaal geïnterpoleerd (``bron="eigen_ingest_geointerpoleerd"``):
    interpoleer per gevraagd station naar de coördinaat van dát station zelf.

    **Sinds §12.13 niet meer de standaard-bron** (die is :func:`fetch_own_weather_direct`, zonder
    RBF): omdat er hier altijd geïnterpoleerd wordt naar de coördinaat van een station dat al in
    ``df_alle_stations`` zit, is de RBF-uitkomst per definitie (bijna) gelijk aan de rauwe waarde
    van dat station zelf (exacte-interpolant-eigenschap) — geverifieerd zowel in
    ``tests/test_weer.py`` (netwerktest, mediane afwijking < 0,5 °C) als in de §7.2-consistentie-
    cijfers zelf (station 210: 0,885 °C geïnterpoleerd vs. 0,800 °C rauw; station 240: 0,600 °C
    beide, zie `docs/data-quality.md`). Deze functie levert dus geen ander antwoord op, alleen een
    veel duurder antwoord: elke RBF-aanroep hieronder rebuild een nieuwe ``RBFInterpolator`` per
    tijdstip én per metric, dus de kosten schalen met ``n_stations × n_tijdstippen × n_metrics`` —
    op een volledige, multi-jaar/28-stations-run (§2.3: terug tot de vroegste ``m``-rij per woning)
    was dat precies de stap die de weer-ingest onbruikbaar traag maakte.

    Blijft beschikbaar (opt-in via ``--weer-geointerpoleerd-diagnose``) voor: (a) de §12.4-vraag
    opnieuw beantwoorden of de interpolatiestap zelf een mismatch verklaart, en (b) toekomstig werk
    dat wél naar een echt GPS-punt interpoleert i.p.v. naar een bekend station (§7.3, kanttekening)
    — dát is een situatie waarin RBF-interpolatie wél het enige antwoord geeft, want dan bestaat er
    geen rauwe stationswaarde om tegen te vergelijken.

    ``station_coords``: ``{weerstation_nr: (lat__degN, lon__degE)}``, zie
    :func:`get_station_coordinates`. ``df_alle_stations``: hergebruik een al opgehaalde
    :func:`fetch_ruwe_stationsdata`-tabel i.p.v. opnieuw ophalen.
    """
    from dutch_weather.weather_interpolate import (
        geo_interpolate_weather_data,
        temporal_interpolate_weather_data,
    )

    if df_alle_stations is None:
        df_alle_stations = fetch_ruwe_stationsdata(start, end)

    if df_alle_stations.empty:
        return pd.DataFrame(columns=WEER_KOLOMMEN)

    frames = []
    for stn, (lat, lon) in station_coords.items():
        geinterpoleerd = geo_interpolate_weather_data(df_alle_stations, lat__degN=lat, lon__degE=lon)
        geinterpoleerd = temporal_interpolate_weather_data(
            geinterpoleerd, interpolate__min=interpolate__min
        )
        breed = geinterpoleerd["value"].unstack("property")
        frames.append(_naar_weer_kolommen(breed, stn, "eigen_ingest_geointerpoleerd"))

    return pd.concat(frames, ignore_index=True)[WEER_KOLOMMEN]


def _dichtstbijzijnde_latlon(df_alle_stations: pd.DataFrame, lat: float, lon: float) -> tuple[float, float]:
    """Het (lat, lon)-paar in ``df_alle_stations`` dat het dichtst bij ``(lat, lon)`` ligt.

    Matcht op afstand, niet op exacte float-gelijkheid: ``lat``/``lon`` komen uit
    :func:`get_station_coordinates` (eigen kleine parser), ``df_alle_stations`` uit de externe
    library's eigen parser; beide lezen dezelfde KNMI-stationslijst, maar zonder garantie op
    bit-identieke afronding. Voor het juiste station is de afstand vrijwel 0.
    """
    lat_lons = df_alle_stations.index.droplevel("timestamp").unique().to_numpy()
    afstanden = [(la - lat) ** 2 + (lo - lon) ** 2 for la, lo in lat_lons]
    return lat_lons[int(np.argmin(afstanden))]


def fetch_own_weather_direct(
    start: pd.Timestamp,
    end: pd.Timestamp,
    station_coords: dict[int, tuple[float, float]],
    interpolate__min: int = 60,
    df_alle_stations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Eigen KNMI-ingest, ZONDER geospatiale interpolatie (``bron="eigen_ingest"``, de standaard-
    bron sinds §12.13): de rauwe uurwaarde van het dichtstbijzijnde station zelf, rechtstreeks uit
    :func:`fetch_ruwe_stationsdata`, en hergebruikt bewust alleen die functie uit
    ``needforheat-dutch-weather-software`` (Apache 2.0), NIET ``geo_interpolate_weather_data``.

    **Waarom dit de standaard is (§12.13):** deze preprocessing evalueert altijd op de coördinaat
    van een al bekend KNMI-station, nooit op een willekeurig GPS-punt — IM3 geeft alleen
    "dichtstbijzijnde station", geen woningcoördinaat (§7.3). Voor precies dát geval levert RBF-
    geospatiale interpolatie (:func:`fetch_own_weather`) vrijwel hetzelfde antwoord als deze rauwe
    waarde, tegen een veelvoud van de rekentijd (zie de docstring daar). Reproduceren van de eigen
    stationsreeks is hier het doel, niet interpoleren naar een plek waar geen station staat.

    **Herkomst:** deze functie bestond al als diagnostisch hulpmiddel om een consistentie-mismatch
    (§7.2) toe te schrijven aan de interpolatiestap zelf, vóór iets anders te vermoeden
    (station/product/tijdzone) — zie §12.4. Op de steekproef bleek "direct" nagenoeg dezelfde
    afwijking te geven als "geïnterpoleerd", wat achteraf bezien al aantoonde dat de interpolatie
    geen inhoudelijk verschil maakt en dus overbodige kosten waren voor een volledige run.
    """
    from dutch_weather.weather_interpolate import temporal_interpolate_weather_data

    if df_alle_stations is None:
        df_alle_stations = fetch_ruwe_stationsdata(start, end)

    if df_alle_stations.empty:
        return pd.DataFrame(columns=WEER_KOLOMMEN)

    frames = []
    for stn, (lat, lon) in station_coords.items():
        dichtstbijzijnd = _dichtstbijzijnde_latlon(df_alle_stations, lat, lon)
        reeks = df_alle_stations.xs(dichtstbijzijnd, level=["lat__degN", "lon__degE"])
        if reeks.empty:
            continue

        # temporal_interpolate_weather_data verwacht een lang formaat (MultiIndex
        # (timestamp, property), kolom 'value'); reeks is al breed (kolom per metric), even
        # hetzelfde lange formaat opbouwen als de geïnterpoleerde tak gebruikt.
        lang = (
            reeks.reset_index()
            .melt(id_vars="timestamp", var_name="property", value_name="value")
            .set_index(["timestamp", "property"])
            .sort_index()
        )
        geinterpoleerd = temporal_interpolate_weather_data(lang, interpolate__min=interpolate__min)
        breed = geinterpoleerd["value"].unstack("property")
        frames.append(_naar_weer_kolommen(breed, stn, "eigen_ingest"))

    if not frames:
        return pd.DataFrame(columns=WEER_KOLOMMEN)

    return pd.concat(frames, ignore_index=True)[WEER_KOLOMMEN]


# --- Consistentiecheck (§7.2) -------------------------------------------------------------------

# Voorlopige, vooraf vastgelegde matchdrempels (open vraag §10.4 nog niet extern bevestigd); zie
# docs/data-quality.md voor de expliciete vermelding dat dit een voorlopige keuze is.
TEMP_MATCH_DREMPEL_degC = 0.5
WIND_MATCH_DREMPEL_m_s_1 = 0.5
# Was 0,05 kWh/m2; ontwerp-intervalsemantiek.md §3 zet ghi om naar W/m2 (x1000, geen kWh meer).
GHI_MATCH_DREMPEL_W_m2 = 50.0

_DREMPELS = {
    "temp_buiten__degC": TEMP_MATCH_DREMPEL_degC,
    "wind__m_s_1": WIND_MATCH_DREMPEL_m_s_1,
    "ghi__W_m_2": GHI_MATCH_DREMPEL_W_m2,
}


def consistency_check(im3_weer: pd.DataFrame, eigen_weer: pd.DataFrame) -> pd.DataFrame:
    """§7.2/§7.3 stap 1-2: per station, mediane absolute afwijking IM3 vs. eigen ingest.

    Geen keuze wélke bron "juist" is bij een slechte match; dat is een bevinding voor
    docs/data-quality.md (§7.3 stap 3), geen cleaning-beslissing.
    """
    merged = im3_weer.merge(eigen_weer, on=["weerstation_nr", "tijdstip"], suffixes=("_im3", "_eigen"))

    rows = []
    for stn, g in merged.groupby("weerstation_nr"):
        row = {"weerstation_nr": stn, "n_overlap": len(g)}
        for veld, drempel in _DREMPELS.items():
            afwijking = (g[f"{veld}_im3"] - g[f"{veld}_eigen"]).abs()
            mediane_afwijking = afwijking.median()
            row[f"{veld}_mediane_abs_afwijking"] = mediane_afwijking
            row[f"{veld}_binnen_drempel"] = (
                bool(mediane_afwijking < drempel) if pd.notna(mediane_afwijking) else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


# --- Koppeling aan measurement-rijen (§2.3) ------------------------------------------------------

WEERKOPPELING_METHODE = {
    "q": "punt_interpolatie",
    "h": "punt_uur",
    "d": "gemiddelde_dag",
    "m": "gemiddelde_maand",
}



WEERVELDEN = ["temp_buiten__degC", "wind__m_s_1", "ghi__W_m_2"]


def _lokale_dagsleutel(tijdstip: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Lokale kalenderdag als ``datetime64[ns]`` (lokaal middernacht), niet als Python-``date``.

    ``.dt.date`` maakt één Python-object per rij, en op miljoenen rijen is dat de duurste stap van
    de hele koppeling. ``tz_localize(None)`` houdt de lokale wandkloktijd en gooit alleen de
    tz-info weg, waarna ``normalize()`` naar middernacht afrondt; het resultaat is dezelfde
    kalenderdag-indeling, maar volledig in numpy-datatypes.
    """
    lokaal = tijdstip.dt if isinstance(tijdstip, pd.Series) else tijdstip
    naief = lokaal.tz_localize(None)
    genormaliseerd = naief.normalize() if hasattr(naief, "normalize") else naief.dt.normalize()
    return np.asarray(genormaliseerd, dtype="datetime64[ns]")


def _lokale_maandsleutel(dagsleutel: np.ndarray) -> np.ndarray:
    """Lokale kalendermaand als ``datetime64[ns]`` (eerste van de maand), afgeleid van de dag."""
    return dagsleutel.astype("datetime64[M]").astype("datetime64[ns]")


def couple_weather_to_measurements(
    measurements: pd.DataFrame, weer: pd.DataFrame, bron: str = "eigen_ingest"
) -> pd.DataFrame:
    """Koppel ``weer`` aan measurement-rijen, per ``interval_type__cat`` een andere methode (§2.3):
    ``q`` interpoleert tussen omliggende uurwaarden, ``h`` is een exacte match, ``d``/``m`` zijn
    het gemiddelde van de eigen uurreeks over het lokale-dag-/maandvenster (§2.4-aware).

    Verwacht dat ``measurements`` al een ``weerstation_nr``-kolom heeft (join met ``homes``).

    **Vectorized**, en dat is geen optimalisatie achteraf maar een noodzaak: een Python-loop per rij die
    telkens een boolean mask over de hele uurreeks legde: 37 s voor 21k rijen, wat op de volledige
    dataset (~4,7 M d/m-rijen én een ~43× langere weerreeks) op uren zou uitkomen. Nu wordt het
    weer éénmalig per lokale kalenderdag/-maand voorgeaggregeerd en met een merge gekoppeld.

    Dat geeft **exact hetzelfde resultaat**: het lokale-dagvenster ``[dag 00:00, dag+1 00:00)``
    bevat per definitie precies de uren waarvan de lokale kalenderdatum die dag is. De
    zomertijd-correctheid (§2.4) blijft dus behouden zonder het venster expliciet uit te rekenen:
    een 23-uursdag levert simpelweg 23 uren in die groep, een 25-uursdag 25. Geverifieerd tegen de
    oude implementatie op de steekproef: identiek op float32-afrondverschil na, geen enkele
    NaN-mismatch.

    De resultaten worden positioneel in numpy-arrays opgebouwd en pas aan het eind in één keer in
    een DataFrame gezet; ``df.loc[mask, kolom] = ...`` op miljoenen rijen is zelf een merkbare
    kostenpost.
    """
    n = len(measurements)
    tijdstip_start = measurements["tijdstip_start"]
    # Epoch-nanoseconden rechtstreeks uit de tz-aware pandas-Series: dat is eenduidig UTC en
    # vermijdt de "no explicit representation of timezones"-waarschuwing die je krijgt als je
    # eerst naar een numpy datetime64 casteert.
    tijd_ns = naar_epoch_ns(tijdstip_start)
    station = measurements["weerstation_nr"].to_numpy()
    interval = np.asarray(measurements["interval_type__cat"].astype(str))

    waarden = {veld: np.full(n, np.nan) for veld in WEERVELDEN}
    methode = np.full(n, "ontbrekend_buiten_archief", dtype=object)

    weer_bron = weer[weer["bron__cat"] == bron].sort_values("tijdstip")
    if weer_bron.empty:
        return _bouw_koppeling(measurements, waarden, methode)

    bron_dag = _lokale_dagsleutel(weer_bron["tijdstip"].dt.tz_convert(TZ_LOKAAL))
    bron_ns = naar_epoch_ns(weer_bron["tijdstip"])
    voorgeaggregeerd = {
        "d": _gemiddelde_per_sleutel(weer_bron, bron_dag),
        "m": _gemiddelde_per_sleutel(weer_bron, _lokale_maandsleutel(bron_dag)),
    }

    for itv, methode_naam in WEERKOPPELING_METHODE.items():
        rijen = np.flatnonzero(interval == itv)
        if not len(rijen):
            continue

        if itv == "h":
            gekoppeld = _merge_op_tijdstip(station[rijen], tijd_ns[rijen], weer_bron, bron_ns)
        elif itv == "q":
            gekoppeld = _interpoleer_per_station(station[rijen], tijd_ns[rijen], weer_bron, bron_ns)
        else:
            dag = _lokale_dagsleutel(tijdstip_start.iloc[rijen].dt.tz_convert(TZ_LOKAAL))
            sleutel = dag if itv == "d" else _lokale_maandsleutel(dag)
            gekoppeld = _merge_op_sleutel(station[rijen], sleutel, voorgeaggregeerd[itv])

        for veld in WEERVELDEN:
            waarden[veld][rijen] = gekoppeld[veld]
        # Alleen rijen die daadwerkelijk een waarde kregen krijgen de echte methode-naam; de rest
        # houdt de 'ontbrekend_buiten_archief'-default waarmee het array begon. Dat dekt zowel een
        # station zonder weerdata als een rij die buiten het opgehaalde venster valt, precies
        # waar dat label voor bedoeld is (§2.3). Zonder deze koppeling aan de wérkelijke waarde
        # zou een lege rij ten onrechte 'punt_interpolatie' o.i.d. melden.
        heeft_waarde = ~np.isnan(gekoppeld[WEERVELDEN[0]])
        methode[rijen[heeft_waarde]] = methode_naam

    return _bouw_koppeling(measurements, waarden, methode)


def _bouw_koppeling(measurements: pd.DataFrame, waarden: dict, methode: np.ndarray) -> pd.DataFrame:
    out = measurements[["home_id__str", "tijdstip_start", "interval_type__cat", "weerstation_nr"]].copy()
    for veld in WEERVELDEN:
        out[veld] = waarden[veld].astype("float32")
    out["weerkoppeling_methode__cat"] = pd.Categorical(methode)
    return out


def _gemiddelde_per_sleutel(weer_bron: pd.DataFrame, sleutel: np.ndarray) -> pd.DataFrame:
    hulp = pd.DataFrame({"weerstation_nr": weer_bron["weerstation_nr"].to_numpy(), "sleutel": sleutel})
    for veld in WEERVELDEN:
        hulp[veld] = weer_bron[veld].to_numpy()
    return hulp.groupby(["weerstation_nr", "sleutel"], observed=True, sort=False)[WEERVELDEN].mean().reset_index()


def _merge_op_sleutel(station: np.ndarray, sleutel: np.ndarray, gemiddelden: pd.DataFrame) -> dict:
    links = pd.DataFrame({"weerstation_nr": station, "sleutel": sleutel})
    gejoined = links.merge(gemiddelden, on=["weerstation_nr", "sleutel"], how="left")
    return {veld: gejoined[veld].to_numpy() for veld in WEERVELDEN}


def _merge_op_tijdstip(
    station: np.ndarray, tijd_ns: np.ndarray, weer_bron: pd.DataFrame, bron_ns: np.ndarray
) -> dict:
    links = pd.DataFrame({"weerstation_nr": station, "tijd_ns": tijd_ns})
    rechts = pd.DataFrame(
        {"weerstation_nr": weer_bron["weerstation_nr"].to_numpy(), "tijd_ns": bron_ns}
    )
    for veld in WEERVELDEN:
        rechts[veld] = weer_bron[veld].to_numpy()
    gejoined = links.merge(rechts, on=["weerstation_nr", "tijd_ns"], how="left")
    return {veld: gejoined[veld].to_numpy() for veld in WEERVELDEN}


def _interpoleer_per_station(
    station: np.ndarray, tijd_ns: np.ndarray, weer_bron: pd.DataFrame, bron_ns: np.ndarray
) -> dict:
    """``q``-rijen: lineair interpoleren tussen de omliggende uurwaarden, per station.

    Loop over stations (hoogstens 28) i.p.v. over rijen: ``np.interp`` doet alle kwartieren van
    één station in één aanroep.
    """
    resultaat = {veld: np.full(len(station), np.nan) for veld in WEERVELDEN}
    bron_station = weer_bron["weerstation_nr"].to_numpy()

    for stn in np.unique(station):
        bron_rijen = np.flatnonzero(bron_station == stn)
        if not len(bron_rijen):
            continue
        rijen = np.flatnonzero(station == stn)
        x = bron_ns[bron_rijen]
        for veld in WEERVELDEN:
            resultaat[veld][rijen] = np.interp(
                tijd_ns[rijen], x, weer_bron[veld].to_numpy()[bron_rijen], left=np.nan, right=np.nan
            )

    return resultaat
