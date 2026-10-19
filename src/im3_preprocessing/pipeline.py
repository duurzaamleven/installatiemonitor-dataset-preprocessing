# SPDX-License-Identifier: EUPL-1.2
"""Orchestratie: bouwt homes/measurements/weer/quality/derived uit de ruwe IM3-bestanden.

Volgorde volgt ontwerp-preprocessing.md §11: eerst io + schema, dan weer (consistentiecheck vóór
vervanging), dan timestamps/intervals, pas daarna cleaning/derived.

**Chunked** (ontwerp §12.9): de woningen worden in blokken verwerkt en
incrementeel naar Parquet geschreven. De eerdere versie hield alle tabellen tegelijk in geheugen,
wat op de volledige dataset (~536 M measurement-rijen) ~63 GB zou vragen, meer dan een gewone
laptop heeft. Nu is het geheugengebruik ongeveer constant en bepaald door ``--chunk-grootte``:
~0,35 GB vast plus ~17 MB per woning in de chunk.

Dit kán alleen omdat elke kwaliteitscontrole per woning groepeert: ``constante_reeks_flags``,
``uitschieter_flags``, ``q_h_vs_dag_consistency``, ``dst_dag_rij_aanwezig`` en
``gas_voor_koppeling_verdacht_rapport`` kijken nooit over woninggrenzen heen. Een chunk-grens die
tussen twee woningen ligt verandert dus geen enkele uitkomst; een chunk-grens dwars dóór een
woning zou dat wél doen, en daarom wordt er uitsluitend op woningniveau gesplitst.

**Uitpakken hoort bij de preprocessing** (ontwerp §12.11): ``--raw-dir`` mag
naar ``dataset_openbaar.zip`` wijzen (of naar een map waar die zip in staat), en de klantbestanden
worden dan als stream uit het archief gelezen. Er belandt geen 23,9 GB aan losse CSV's op schijf,
niet tijdens de run en niet erna. Zie :mod:`im3_preprocessing.bron`.

**Hervatbaar sinds deze versie** (ontwerp §12.9, patroon overgenomen van de zusterrepo
demoprojecthybride-dataset-preprocessing): elke chunk schrijft zijn deel atomisch weg naar
``<out-dir>/parts/`` (zie :mod:`im3_preprocessing.chunking`) vóórdat de eindtabellen samengevoegd
worden. Een afgebroken run (Ctrl-C, stroomstoring, een kapotte laptop-nacht) hoeft bij een volgende
poging niet bij chunk 0 te beginnen: chunks waarvan alle deelbestanden al compleet zijn worden
overgeslagen. ``--opnieuw`` gooit dat weg en begint schoon.

Gebruik als CLI: ``python -m im3_preprocessing.pipeline --raw-dir data/raw --out-dir data/processed
--sample-size 30``. Zonder ``--sample-size``/``--home-ids`` wordt de VOLLEDIGE dataset verwerkt.
Dat is een expliciete, aparte keuze (zie ontwerp §11), niet het standaardpad tijdens ontwikkeling.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import bron as bron_mod, chunking, cleaning, derived as derived_mod, gaskwaliteit, io as im3io, quality, report, weer as weer_mod
from . import datapackage as datapackage_mod
from .dtypes import GRANULARITEIT, pas_vaste_categorieen_toe
from .intervals import J_PER_KWH, compute_energie_deler_s, compute_interval_duur_s
from .timestamps import TZ_LOKAAL, naar_lokale_tijdzone, resolve_timestamps

log = logging.getLogger(__name__)

# Gemeten op de echte dataset (26-aug-2026, 100 woningen, zip-bron): het piekgeheugen is ongeveer
# 0,35 GB vast + 17 MB per woning in de chunk, en een grotere chunk is *niet* sneller: 5/10/25/50/100
# woningen kostten respectievelijk 134/129/159/161/237 s bij 0,43/0,60/1,07/1,71/2,03 GB piek-RSS.
# De eerdere standaard van 250 zou ~4 GB vragen zonder er iets voor terug te geven. 25 laat een run
# comfortabel binnen ~1,1 GB passen; verlaag naar 10 op een machine met weinig vrij geheugen.
# (Woont nu in chunking.py, hier alleen nog een alias zodat bestaand gebruik van
# pipeline.CHUNK_GROOTTE_STANDAARD blijft werken.)
CHUNK_GROOTTE_STANDAARD = chunking.CHUNK_GROOTTE_STANDAARD

# Definitieve kolomindeling van measurements.parquet (ontwerp-intervalsemantiek.md §3): uitsluitend
# aannamevrije conversies, geen energiewaarden meer (alleen vermogen). ``e_net__kWh``,
# ``g_gebruik__m3``, ``g_gebruik__m3_s_1`` en ``weerstation_nr`` zijn interne werkkolommen die de
# rest van de chunk-verwerking nog nodig heeft (quality/derived/weer-koppeling), maar die hier vóór
# het wegschrijven worden afgeknipt.
MEASUREMENTS_OUTPUT_KOLOMMEN = [
    "home_id__str",
    "tijdstip_start",
    "interval_type__cat",
    "interval_duur__s",
    "granulariteit__cat",
    "e_net__W",
]


def build_measurements(
    raw_files: list[im3io.CustomerFile], homes: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bouw de (interne, nog niet afgeknipte) ``measurements``-werktabel (§5) uit ruwe
    :class:`CustomerFile`'s.

    Retourneert ``(measurements, raw_with_tijdstip)``, waarbij ``raw_with_tijdstip`` ook de nog
    niet gedropte ``wind``/``temp``/``sun``-kolommen, nodig voor
    :func:`im3_preprocessing.weer.extract_im3_weather`. (Niet via ``.attrs`` doorgegeven: pandas'
    ``merge``/``__finalize__`` probeert ``.attrs``-waarden onderling te vergelijken met ``==``, wat
    faalt zodra een attr zelf een DataFrame is.)

    ``measurements`` bevat hier nog meer dan uiteindelijk naar ``measurements.parquet`` gaat:
    ``e_net__W`` en ``g_gebruik__m3_s_1`` (het vermogen/de flow, ontwerp-intervalsemantiek.md §2/§3)
    worden al hier berekend, omdat :mod:`im3_preprocessing.cleaning` en :mod:`im3_preprocessing.quality`
    daarop moeten werken (niet meer op de energiekolommen; zie cleaning.py). Zie
    :data:`MEASUREMENTS_OUTPUT_KOLOMMEN` voor de kolommen die daadwerkelijk weggeschreven worden.
    """
    frames = []
    for cf in raw_files:
        df = cf.df.copy()
        df["tijdstip_start"] = resolve_timestamps(df["datetime"], df["interval"])
        df["interval_duur__s"] = compute_interval_duur_s(df["datetime"], df["interval"])
        frames.append(df)

    raw_with_tijdstip = pd.concat(frames, ignore_index=True)

    measurements = raw_with_tijdstip.rename(
        columns={"interval": "interval_type__cat", "elec": "e_net__kWh", "gas": "g_gebruik__m3"}
    )[
        [
            "home_id__str",
            "tijdstip_start",
            "interval_type__cat",
            "interval_duur__s",
            "e_net__kWh",
            "g_gebruik__m3",
        ]
    ].copy()
    # float32 voor elec/gas: ruim genoeg voor kWh-precisie, en float ondersteunt NaN al native
    # (nodig voor de 707/6.283 all-electric woningen zonder gas-kolom, §12.1) zonder een nullable
    # extension-type. Zie docs/variable-dictionary.md voor het volledige dtype-beleid.
    measurements["e_net__kWh"] = measurements["e_net__kWh"].astype("float32")
    measurements["g_gebruik__m3"] = measurements["g_gebruik__m3"].astype("float32")
    measurements["granulariteit__cat"] = measurements["interval_type__cat"].map(GRANULARITEIT)
    measurements = pas_vaste_categorieen_toe(measurements)

    # §2 ontwerp-intervalsemantiek.md: voor m-rijen is de gerapporteerde waarde het gemiddelde
    # dagverbruik van de maand, dus is de juiste deler een dag (86.400 s), niet de maandduur.
    deler_s = compute_energie_deler_s(measurements["interval_type__cat"], measurements["interval_duur__s"])
    measurements["e_net__W"] = (
        (measurements["e_net__kWh"] * J_PER_KWH) / deler_s
    ).astype("float32")
    measurements["g_gebruik__m3_s_1"] = (measurements["g_gebruik__m3"] / deler_s).astype("float32")

    measurements = measurements.merge(
        homes[["home_id__str", "weerstation_nr"]], on="home_id__str", how="left", validate="m:1"
    )

    return measurements, raw_with_tijdstip


def build_weer_tables(
    start: pd.Timestamp,
    eind: pd.Timestamp,
    stations: list[int],
    weer_venster_dagen: int | None = None,
    geointerpoleerd_diagnose: bool = False,
) -> pd.DataFrame:
    """Haal de eigen KNMI-reeks op voor ``[start, eind]``.

    - ``bron="eigen_ingest"``: de rauwe, niet-geïnterpoleerde waarde van het station zelf (de
      standaard-bron sinds §12.13). Er wordt hier altijd de coördinaat van een al bekend KNMI-
      station opgevraagd, nooit een willekeurig GPS-punt, en voor dat geval levert RBF-geospatiale
      interpolatie geen ander antwoord, alleen een veel duurder antwoord (zie
      :func:`im3_preprocessing.weer.fetch_own_weather`).
    - ``bron="eigen_ingest_geointerpoleerd"``: alléén met ``geointerpoleerd_diagnose=True``
      (CLI: ``--weer-geointerpoleerd-diagnose``). RBF-geospatiaal geïnterpoleerd naar diezelfde
      stationscoördinaat; puur om de §12.4-vraag opnieuw te kunnen beantwoorden (ligt een
      consistentie-mismatch aan de interpolatiestap zelf?), niet nodig voor een gewone run.

    De door RVO meegeleverde reeks (``bron="im3"``) zit hier bewust NIET in: die wordt per woning
    gedupliceerd aangeleverd en is via een nieuwe ophaal altijd terug te krijgen, dus hij hoort
    niet in de output thuis (§12.8). Voor de consistentiecheck (§7.2) wordt hij tijdens de run wel
    ingelezen; zie :class:`RapportAccumulator`.
    """
    if not stations:
        return pd.DataFrame(columns=weer_mod.WEER_KOLOMMEN)

    coords_alle = weer_mod.get_station_coordinates()
    station_coords = {
        stn: (coords_alle.loc[stn, "lat__degN"], coords_alle.loc[stn, "lon__degE"])
        for stn in stations
        if stn in coords_alle.index
    }
    if not station_coords:
        return pd.DataFrame(columns=weer_mod.WEER_KOLOMMEN)

    if weer_venster_dagen is not None:
        start = max(start, eind - pd.Timedelta(days=weer_venster_dagen))
        log.info("Weer-venster beperkt tot de laatste %d dagen (steekproef-run)", weer_venster_dagen)

    log.info(
        "Eigen KNMI-ingest voor %d station(s)%s, venster %s .. %s",
        len(station_coords),
        " (+ geospatiale-interpolatie-diagnose)" if geointerpoleerd_diagnose else "",
        start, eind,
    )
    df_alle_stations = weer_mod.fetch_ruwe_stationsdata(start, eind)
    frames = [
        weer_mod.fetch_own_weather_direct(
            start, eind, station_coords, df_alle_stations=df_alle_stations
        )
    ]
    if geointerpoleerd_diagnose:
        frames.append(
            weer_mod.fetch_own_weather(
                start, eind, station_coords, df_alle_stations=df_alle_stations
            )
        )

    weer_tabel = pd.concat(frames, ignore_index=True)
    return pas_vaste_categorieen_toe(weer_tabel)


def _records_naar_frames(records: list[dict], tijdkolommen: list[str]) -> list[pd.DataFrame]:
    """Inverse van ``df.to_json(orient="records", date_format="iso")`` + ``json.loads``: zet een
    (mogelijk lege) lijst records terug in een ``[DataFrame]`` (of ``[]`` als ``records`` leeg is,
    zodat dit direct als ``RapportAccumulator.extreme_uitschieters``/``.gas_voor_koppeling``/
    ``.im3_weer`` kan dienen). ``tijdkolommen`` benoemt de kolommen die JSON als kale ISO-string
    teruggeeft en die hier weer een tz-aware ``pd.Timestamp`` moeten worden.
    """
    if not records:
        return []
    df = pd.DataFrame.from_records(records)
    for kolom in tijdkolommen:
        if kolom in df.columns:
            df[kolom] = pd.to_datetime(df[kolom])
    return [df]


@dataclass
class RapportAccumulator:
    """Verzamelt de rapportcijfers over de chunks heen, zonder de volledige tabellen te bewaren.

    Alles wat hier wordt bijgehouden is O(aantal woningen) of O(1), niet O(aantal rijen), zodat
    het geheugengebruik van de rapportage niet met de dataset meegroeit. Uitzondering: de
    dagconsistentie-afwijkingen, waarvan alleen de kale float32-waarden worden bewaard (nodig voor
    een mediaan/percentiel achteraf, ~4 bytes per woning-dag).

    **Hervatbaar sinds deze versie** (:mod:`im3_preprocessing.chunking`): elke chunk wordt niet
    meer alleen live in dit object opgeteld, maar zijn bijdrage wordt ook los weggeschreven als
    JSON (:func:`naar_json_dict`/:func:`uit_json_dict`, gebruikt door ``chunking.rapport_pad``).
    Zo hoeft een hervatte run een overgeslagen chunk niet opnieuw te verwerken om toch zijn
    rapportcijfers mee te tellen: :func:`voeg_accumulator_toe` voegt een teruggelezen chunk-
    accumulator toe alsof ``voeg_chunk_toe`` net was aangeroepen. ``pipeline.run`` bouwt de
    uiteindelijke accumulator daarom altijd via deze route -- ÉÉN pas over alle chunks, ongeacht
    welke daarvan in DEZE run vers verwerkt zijn en welke uit een vorige run hervat zijn -- in
    plaats van twee losse codepaden voor "vers" en "hervat" te onderhouden.

    Dit MAG omdat elke woning in precies één chunk zit (chunks partitioneren op woning, ontwerp
    §12.9): alle tellingen hieronder zijn dus veilig te SOMMEREN over chunk-accumulators heen,
    zonder risico op dubbeltelling. Uitzondering: ``tijdstip_min``/``tijdstip_max`` (min/max, geen
    som) en ``dagcheck_kwartier``/``dagcheck_uur`` (de ruwe steekproeven moeten samengevoegd worden
    vóórdat een mediaan/percentiel opnieuw uitgerekend wordt; het gemiddelde van per-chunk medianen
    is niet hetzelfde als de mediaan van het geheel).
    """

    n_rijen: int = 0
    n_woningen: int = 0
    n_zonder_gaskolom: int = 0
    vlag_tellingen: dict[str, int] = field(default_factory=dict)
    interval_tellingen: dict[str, int] = field(default_factory=dict)
    tijdstip_min: pd.Timestamp | None = None
    tijdstip_max: pd.Timestamp | None = None
    dagcheck_kwartier: list[np.ndarray] = field(default_factory=list)
    dagcheck_uur: list[np.ndarray] = field(default_factory=list)
    n_dagcheck_kwartier: int = 0
    n_dagcheck_uur: int = 0
    dst_aanwezig: int = 0
    dst_totaal: int = 0
    gas_negatief_rijen: int = 0
    # Was een `set` met de getroffen home_id's; sinds het hervatten enkel de LENGTE ooit nodig
    # heeft (report.py) en een woning nooit in twee chunks tegelijk zit, volstaat een simpele
    # optelbare teller -- dat scheelt ook het (kunstmatige) plaatshoudersobject dat nodig zou zijn
    # om een JSON-deserialisatie alsnog een "set met de juiste lengte" te laten zijn.
    n_gas_negatief_woningen: int = 0
    extreme_uitschieters: list[pd.DataFrame] = field(default_factory=list)
    gas_voor_koppeling: list[pd.DataFrame] = field(default_factory=list)
    im3_weer: list[pd.DataFrame] = field(default_factory=list)
    gas_hhv_bron_tellingen: dict[str, int] = field(default_factory=dict)

    def voeg_chunk_toe(
        self,
        measurements: pd.DataFrame,
        quality_tabel: pd.DataFrame,
        derived_tabel: pd.DataFrame,
        homes_chunk: pd.DataFrame,
        im3_weer_chunk: pd.DataFrame,
        n_zonder_gas: int,
    ) -> None:
        self.n_rijen += len(measurements)
        self.n_woningen += homes_chunk["home_id__str"].nunique()
        self.n_zonder_gaskolom += n_zonder_gas

        for kolom in quality_tabel.filter(like="__flag").columns:
            self.vlag_tellingen[kolom] = self.vlag_tellingen.get(kolom, 0) + int(
                quality_tabel[kolom].sum()
            )

        for itv, n in measurements["interval_type__cat"].value_counts().items():
            self.interval_tellingen[itv] = self.interval_tellingen.get(itv, 0) + int(n)

        if "gas_hhv_bron__cat" in derived_tabel.columns:
            for bron, n in derived_tabel["gas_hhv_bron__cat"].value_counts().items():
                self.gas_hhv_bron_tellingen[bron] = self.gas_hhv_bron_tellingen.get(bron, 0) + int(n)

        chunk_min, chunk_max = measurements["tijdstip_start"].min(), measurements["tijdstip_start"].max()
        self.tijdstip_min = chunk_min if self.tijdstip_min is None else min(self.tijdstip_min, chunk_min)
        self.tijdstip_max = chunk_max if self.tijdstip_max is None else max(self.tijdstip_max, chunk_max)

        dagconsistentie = quality.q_h_vs_dag_consistency(measurements)
        if len(dagconsistentie):
            for kol, buffer, teller in (
                ("e_dagcheck_kwartier__kWh", self.dagcheck_kwartier, "n_dagcheck_kwartier"),
                ("e_dagcheck_uur__kWh", self.dagcheck_uur, "n_dagcheck_uur"),
            ):
                waarden = dagconsistentie[kol].dropna().abs().to_numpy(dtype="float32")
                if len(waarden):
                    buffer.append(waarden)
                    setattr(self, teller, getattr(self, teller) + len(waarden))

        dst = quality.dst_dag_rij_aanwezig(measurements)
        self.dst_aanwezig += int(dst["d_rij_aanwezig"].sum())
        self.dst_totaal += len(dst)

        gas_neg = quality.gas_negatief_rapport(measurements)
        self.gas_negatief_rijen += gas_neg["n_rijen_negatief"]
        self.n_gas_negatief_woningen += len(gas_neg["woningen_getroffen"])

        uitschieters = quality.extreme_uitschieters_rapport(measurements, quality_tabel)
        if len(uitschieters):
            self.extreme_uitschieters.append(uitschieters)

        koppeling = quality.gas_voor_koppeling_verdacht_rapport(measurements, homes_chunk)
        if len(koppeling):
            self.gas_voor_koppeling.append(koppeling)

        if not im3_weer_chunk.empty:
            self.im3_weer.append(im3_weer_chunk)
            # Meteen samenvoegen en ontdubbelen: alle woningen op hetzelfde station leveren
            # dezelfde reeks (§5.1), dus zonder ontdubbelen groeit dit onnodig mee met het aantal
            # woningen i.p.v. met het aantal stations.
            self.im3_weer = [
                pd.concat(self.im3_weer, ignore_index=True).drop_duplicates(
                    subset=["weerstation_nr", "tijdstip"]
                )
            ]

    def dagcheck_statistiek(self, welke: str) -> tuple[int, float, float]:
        buffers = self.dagcheck_kwartier if welke == "kwartier" else self.dagcheck_uur
        if not buffers:
            return 0, float("nan"), float("nan")
        alles = np.concatenate(buffers)
        return len(alles), float(np.median(alles)), float(np.quantile(alles, 0.95))

    def samengevoegde_uitschieters(self, top_n: int = 10) -> pd.DataFrame:
        if not self.extreme_uitschieters:
            return pd.DataFrame()
        alles = pd.concat(self.extreme_uitschieters, ignore_index=True)
        return alles.sort_values("abs_waarde", ascending=False).head(top_n).reset_index(drop=True)

    def samengevoegde_gaskoppeling(self) -> pd.DataFrame:
        if not self.gas_voor_koppeling:
            return pd.DataFrame()
        return pd.concat(self.gas_voor_koppeling, ignore_index=True)

    def samengevoegd_im3_weer(self) -> pd.DataFrame:
        return self.im3_weer[0] if self.im3_weer else pd.DataFrame()

    def voeg_accumulator_toe(self, andere: "RapportAccumulator") -> None:
        """Voeg de staat van ``andere`` toe aan ``self``, alsof ``andere``'s chunk(s) net via
        :func:`voeg_chunk_toe` waren verwerkt. Zie de klasse-docstring voor waarom dit veilig
        sommeren is (chunks partitioneren op woning, dus geen enkele woning zit in beide)."""
        self.n_rijen += andere.n_rijen
        self.n_woningen += andere.n_woningen
        self.n_zonder_gaskolom += andere.n_zonder_gaskolom
        for kolom, n in andere.vlag_tellingen.items():
            self.vlag_tellingen[kolom] = self.vlag_tellingen.get(kolom, 0) + n
        for itv, n in andere.interval_tellingen.items():
            self.interval_tellingen[itv] = self.interval_tellingen.get(itv, 0) + n
        for bron, n in andere.gas_hhv_bron_tellingen.items():
            self.gas_hhv_bron_tellingen[bron] = self.gas_hhv_bron_tellingen.get(bron, 0) + n

        if andere.tijdstip_min is not None:
            self.tijdstip_min = (
                andere.tijdstip_min if self.tijdstip_min is None else min(self.tijdstip_min, andere.tijdstip_min)
            )
        if andere.tijdstip_max is not None:
            self.tijdstip_max = (
                andere.tijdstip_max if self.tijdstip_max is None else max(self.tijdstip_max, andere.tijdstip_max)
            )

        self.dagcheck_kwartier.extend(andere.dagcheck_kwartier)
        self.dagcheck_uur.extend(andere.dagcheck_uur)
        self.n_dagcheck_kwartier += andere.n_dagcheck_kwartier
        self.n_dagcheck_uur += andere.n_dagcheck_uur

        self.dst_aanwezig += andere.dst_aanwezig
        self.dst_totaal += andere.dst_totaal
        self.gas_negatief_rijen += andere.gas_negatief_rijen
        self.n_gas_negatief_woningen += andere.n_gas_negatief_woningen

        self.extreme_uitschieters.extend(andere.extreme_uitschieters)
        self.gas_voor_koppeling.extend(andere.gas_voor_koppeling)

        if andere.im3_weer:
            self.im3_weer.extend(andere.im3_weer)
            # Zelfde ontdubbeling als in voeg_chunk_toe (§5.1: alle woningen op hetzelfde station
            # leveren dezelfde reeks).
            self.im3_weer = [
                pd.concat(self.im3_weer, ignore_index=True).drop_duplicates(subset=["weerstation_nr", "tijdstip"])
            ]

    def naar_json_dict(self, *, inclusief_im3_weer_ruw: bool = True) -> dict:
        """Volledig-getrouwe JSON-serialisatie van deze accumulator (round-trip via
        :func:`uit_json_dict`).

        Dit is bewust de RUWE staat, inclusief de kale dagcheck-steekproeven: dat is nodig zodra
        deze momentopname nog met ANDERE chunks samengevoegd moet worden (:func:`voeg_accumulator_toe`),
        want een mediaan/percentiel is niet opnieuw te berekenen uit alleen een eerder uitgerekende
        mediaan. Gebruikt voor het per-chunk rapportdeel (``chunking.rapport_pad``, klein: één
        chunk woningen).

        **``inclusief_im3_weer_ruw=False`` voor ``<out-dir>/rapport_accumulator.json``.** Eerst
        was de aanname hier "dat bestand is toch al klein op de steekproefschaal van deze taak" --
        gemeten (05-09-2026, 20 woningen, ~4 jaar) bleek dat niet te kloppen: ``im3_weer`` alleen al
        bevatte 274.793 station-uur-rijen (65 MB), want die tabel is niet O(aantal woningen) maar
        O(aantal stations x aantal uren) -- vergelijkbaar met ``weer.parquet`` zelf, niet klein.
        ``report.build_report`` gebruikt uit ``acc`` zelf nooit ``im3_weer``/``samengevoegd_im3_weer()``
        (alleen via een aparte, al tot de stationslijst gereduceerde parameter, zie
        ``report.schrijf_accumulator``), dus is de ruwe tabel hier overbodige ballast zodra de
        accumulator zijn laatste vorm heeft (na afloop van de run wordt er nooit meer een chunk aan
        toegevoegd). ``inclusief_im3_weer_ruw=False`` laat "im3_weer" daarom leeg; alle andere velden
        blijven zoals altijd (die zijn geen van alle zo groot).
        """
        return {
            "n_rijen": self.n_rijen,
            "n_woningen": self.n_woningen,
            "n_zonder_gaskolom": self.n_zonder_gaskolom,
            "vlag_tellingen": self.vlag_tellingen,
            "interval_tellingen": self.interval_tellingen,
            "tijdstip_min": self.tijdstip_min.isoformat() if self.tijdstip_min is not None else None,
            "tijdstip_max": self.tijdstip_max.isoformat() if self.tijdstip_max is not None else None,
            "dagcheck_kwartier": [w.tolist() for w in self.dagcheck_kwartier],
            "dagcheck_uur": [w.tolist() for w in self.dagcheck_uur],
            "n_dagcheck_kwartier": self.n_dagcheck_kwartier,
            "n_dagcheck_uur": self.n_dagcheck_uur,
            "dst_aanwezig": self.dst_aanwezig,
            "dst_totaal": self.dst_totaal,
            "gas_negatief_rijen": self.gas_negatief_rijen,
            "n_gas_negatief_woningen": self.n_gas_negatief_woningen,
            "extreme_uitschieters": json.loads(
                self.samengevoegde_uitschieters().to_json(orient="records", date_format="iso")
            ),
            "gas_voor_koppeling": json.loads(
                self.samengevoegde_gaskoppeling().to_json(orient="records", date_format="iso")
            ),
            "im3_weer": (
                json.loads(self.samengevoegd_im3_weer().to_json(orient="records", date_format="iso"))
                if inclusief_im3_weer_ruw
                else []
            ),
            "gas_hhv_bron_tellingen": self.gas_hhv_bron_tellingen,
        }

    @classmethod
    def uit_json_dict(cls, data: dict) -> "RapportAccumulator":
        """De inverse van :func:`naar_json_dict`."""
        acc = cls()
        acc.n_rijen = data["n_rijen"]
        acc.n_woningen = data["n_woningen"]
        acc.n_zonder_gaskolom = data["n_zonder_gaskolom"]
        acc.vlag_tellingen = dict(data["vlag_tellingen"])
        acc.interval_tellingen = dict(data["interval_tellingen"])
        acc.tijdstip_min = pd.Timestamp(data["tijdstip_min"]) if data["tijdstip_min"] else None
        acc.tijdstip_max = pd.Timestamp(data["tijdstip_max"]) if data["tijdstip_max"] else None
        # Let op: dit is een lijst VAN buffers (één per samengevoegde chunk, mogelijk verschillend
        # van lengte), geen platte lijst getallen -- elke deelbuffer moet een EIGEN array worden,
        # anders probeert np.array() er ten onrechte één (ongeldige, want ongelijke-lengte) 2D-array
        # van te maken, wat dagcheck_statistiek's np.concatenate later laat crashen zodra er meer
        # dan één chunk is samengevoegd (per chunk een andere n dagen).
        acc.dagcheck_kwartier = [np.array(buffer, dtype="float32") for buffer in data["dagcheck_kwartier"]]
        acc.dagcheck_uur = [np.array(buffer, dtype="float32") for buffer in data["dagcheck_uur"]]
        acc.n_dagcheck_kwartier = data["n_dagcheck_kwartier"]
        acc.n_dagcheck_uur = data["n_dagcheck_uur"]
        acc.dst_aanwezig = data["dst_aanwezig"]
        acc.dst_totaal = data["dst_totaal"]
        acc.gas_negatief_rijen = data["gas_negatief_rijen"]
        acc.n_gas_negatief_woningen = data["n_gas_negatief_woningen"]
        acc.extreme_uitschieters = _records_naar_frames(data["extreme_uitschieters"], ["tijdstip_start"])
        acc.gas_voor_koppeling = _records_naar_frames(data["gas_voor_koppeling"], ["tijdstip_start"])
        acc.im3_weer = _records_naar_frames(data["im3_weer"], ["tijdstip"])
        acc.gas_hhv_bron_tellingen = dict(data["gas_hhv_bron_tellingen"])
        return acc


def _lees_chunk(bron: bron_mod.Bron, home_ids: list[str]) -> list[im3io.CustomerFile]:
    """Lees de klantbestanden van één chunk als stream, of de bron nu een map of een zip is."""
    raw_files = []
    for home_id in home_ids:
        with bron.open_klantbestand(home_id) as stream:
            raw_files.append(im3io.read_customer_stream(stream, home_id))
    return raw_files


def _verwerk_chunk(
    bron: bron_mod.Bron,
    chunk_ids: list[str],
    homes_chunk: pd.DataFrame,
    weer_tabel: pd.DataFrame,
    gas_hhv: pd.DataFrame,
    fetch_eigen_weer: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """Verwerk één blok woningen tot (measurements, quality, derived, im3_weer, n_zonder_gas)."""
    raw_files = _lees_chunk(bron, chunk_ids)
    n_zonder_gas = sum(1 for cf in raw_files if any("gas" in issue for issue in cf.issues))

    measurements, raw_with_tijdstip = build_measurements(raw_files, homes_chunk)
    del raw_files

    im3_weer = weer_mod.extract_im3_weather(raw_with_tijdstip, homes_chunk)
    del raw_with_tijdstip

    quality_tabel = cleaning.build_quality_table(measurements)

    gas_koppeling = gaskwaliteit.couple_gas_hhv_to_measurements(measurements, gas_hhv)
    derived_tabel = derived_mod.build_derived(
        measurements, gas_hhv__J_m_3=gas_koppeling[gaskwaliteit.KOLOM]
    )
    derived_tabel[gaskwaliteit.KOLOM] = gas_koppeling[gaskwaliteit.KOLOM]
    derived_tabel["gas_hhv_bron__cat"] = gas_koppeling["gas_hhv_bron__cat"]

    if not weer_tabel.empty:
        weer_bron = "eigen_ingest" if fetch_eigen_weer else "im3"
        koppeling = weer_mod.couple_weather_to_measurements(
            measurements, weer_tabel, bron=weer_bron
        )
        for kolom in ["weerkoppeling_methode__cat"] + weer_mod.WEERVELDEN:
            derived_tabel[kolom] = koppeling[kolom].to_numpy()

    derived_tabel = pas_vaste_categorieen_toe(derived_tabel)
    return measurements, quality_tabel, derived_tabel, im3_weer, n_zonder_gas


def _verwerk_en_schrijf_chunk(
    bron: bron_mod.Bron,
    chunk_ids: list[str],
    homes_chunk: pd.DataFrame,
    weer_tabel: pd.DataFrame,
    gas_hhv: pd.DataFrame,
    fetch_eigen_weer: bool,
    parts_dir: Path,
    chunk_idx: int,
) -> int:
    """Verwerk chunk ``chunk_idx`` en schrijf zijn drie contracttabellen + rapportdeel atomisch weg
    naar ``parts_dir`` (:mod:`im3_preprocessing.chunking`). Retourneert het aantal measurement-rijen,
    puur voor logging.

    De rapportbijdrage (``chunk_acc``) wordt hier bewust uit de nog NIET afgeknipte ``measurements``
    gehaald (met ``g_gebruik__m3_s_1`` en andere interne werkkolommen die ``quality``'s
    rapportfuncties nodig hebben, maar die niet in ``measurements.parquet`` belanden, zie
    :data:`MEASUREMENTS_OUTPUT_KOLOMMEN`). Dat kan alleen NU, terwijl deze chunk nog vers in
    geheugen staat -- een later teruggelezen ``measurements.parquet`` zou die kolommen missen. Dit
    is precies waarom de rapportbijdrage een eigen deelbestand krijgt (``chunking.rapport_pad``) in
    plaats van bij het samenvoegen uit de drie Parquet-delen herleid te worden.
    """
    measurements, quality_tabel, derived_tabel, im3_weer, n_zonder_gas = _verwerk_chunk(
        bron, chunk_ids, homes_chunk, weer_tabel, gas_hhv, fetch_eigen_weer
    )

    chunk_acc = RapportAccumulator()
    chunk_acc.voeg_chunk_toe(measurements, quality_tabel, derived_tabel, homes_chunk, im3_weer, n_zonder_gas)

    # Pas hier naar lokale tijd: intern is alles UTC (eenduidig voor joins/interpolatie), in de
    # output is het tz-aware Europe/Amsterdam (§12.10). Afknippen naar de definitieve kolomindeling
    # (ontwerp-intervalsemantiek.md §3): de interne werkkolommen horen niet in de output.
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "measurements", chunk_idx),
        naar_lokale_tijdzone(measurements[MEASUREMENTS_OUTPUT_KOLOMMEN].copy()),
    )
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "quality", chunk_idx), naar_lokale_tijdzone(quality_tabel)
    )
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "derived", chunk_idx), naar_lokale_tijdzone(derived_tabel)
    )
    chunking.schrijf_json_atomisch(chunking.rapport_pad(parts_dir, chunk_idx), chunk_acc.naar_json_dict())

    n_measurements = len(measurements)
    del measurements, quality_tabel, derived_tabel, im3_weer, chunk_acc
    return n_measurements


def run(
    raw_dir: Path,
    out_dir: Path,
    home_ids: list[str] | None = None,
    raw_bron: str = "auto",
    interim_dir: Path | None = Path("data/interim"),
    fetch_eigen_weer: bool = True,
    weer_venster_dagen: int | None = None,
    weer_geointerpoleerd_diagnose: bool = False,
    fetch_gaskwaliteit: bool = True,
    gaskwaliteit_venster_dagen: int | None = None,
    docs_dir: Path | None = Path("docs"),
    chunk_grootte: int = CHUNK_GROOTTE_STANDAARD,
    opnieuw: bool = False,
    datapackage_pad: Path | None = Path(datapackage_mod.DATAPACKAGE_BESTANDSNAAM),
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bron = bron_mod.maak_bron(raw_dir, voorkeur=raw_bron, cache_map=interim_dir)
    log.info("Ruwe databron: %s", bron.omschrijving)

    try:
        return _run_met_bron(
            bron,
            out_dir,
            home_ids=home_ids,
            fetch_eigen_weer=fetch_eigen_weer,
            weer_venster_dagen=weer_venster_dagen,
            weer_geointerpoleerd_diagnose=weer_geointerpoleerd_diagnose,
            fetch_gaskwaliteit=fetch_gaskwaliteit,
            gaskwaliteit_venster_dagen=gaskwaliteit_venster_dagen,
            docs_dir=docs_dir,
            chunk_grootte=chunk_grootte,
            opnieuw=opnieuw,
            datapackage_pad=datapackage_pad,
        )
    finally:
        bron.sluit()


def _run_met_bron(
    bron: bron_mod.Bron,
    out_dir: Path,
    home_ids: list[str] | None,
    fetch_eigen_weer: bool,
    weer_venster_dagen: int | None,
    weer_geointerpoleerd_diagnose: bool,
    fetch_gaskwaliteit: bool,
    gaskwaliteit_venster_dagen: int | None,
    docs_dir: Path | None,
    chunk_grootte: int,
    opnieuw: bool = False,
    datapackage_pad: Path | None = None,
) -> dict:
    with bron.open_metadata() as stream:
        homes = im3io.read_homes_metadata(stream)

    if home_ids is not None:
        te_verwerken = [hid for hid in home_ids if bron.bevat(hid)]
        ontbrekend = sorted(set(home_ids) - set(te_verwerken))
        if ontbrekend:
            log.warning(
                "%d gevraagde home_id(s) zitten niet in de bron: %s", len(ontbrekend), ontbrekend
            )
    else:
        te_verwerken = bron.home_ids()
    # Alleen woningen waarvan er ook echt een klantbestand is: een metadata-rij zonder bestand zou
    # anders wél in homes.parquet en in de rapportagetellingen belanden, maar zonder één meting.
    # (Op de echte dataset komen beide op 6.283 uit, dus dit filtert daar niets weg.)
    homes_gebruikt = homes[homes["home_id__str"].isin(te_verwerken)].reset_index(drop=True)

    log.info("%d klantbestanden, chunks van %d woningen", len(te_verwerken), chunk_grootte)

    # --- eenmalige, chunk-onafhankelijke ingest -------------------------------------------------
    # Het tijdbereik is alleen nodig om het weer-/gaskwaliteitvenster te bepalen. Zonder die twee
    # ingests wordt de scan overgeslagen -- bij een zip-bron kost die een volledige
    # decompressiepass (zie bron.ZipBron.tijdbereik), dus dat is geen triviale besparing.
    start = eind = None
    if fetch_eigen_weer or fetch_gaskwaliteit:
        start, eind = bron.tijdbereik(te_verwerken)
        if start is None:
            raise ValueError("Geen bruikbare tijdstempels gevonden in de klantbestanden")
        log.info("Tijdbereik over alle bestanden: %s .. %s", start, eind)

    weer_tabel = pd.DataFrame(columns=weer_mod.WEER_KOLOMMEN)
    if fetch_eigen_weer:
        stations = sorted(homes_gebruikt["weerstation_nr"].unique().tolist())
        weer_tabel = build_weer_tables(
            start, eind, stations, weer_venster_dagen, weer_geointerpoleerd_diagnose
        )

    gas_hhv = pd.DataFrame(columns=["tijdstip", gaskwaliteit.KOLOM])
    if fetch_gaskwaliteit:
        gk_start = start
        if gaskwaliteit_venster_dagen is not None:
            gk_start = max(start, eind - pd.Timedelta(days=gaskwaliteit_venster_dagen))
            log.info(
                "Gaskwaliteit-venster beperkt tot de laatste %d dagen (steekproef-run)",
                gaskwaliteit_venster_dagen,
            )
        log.info("Calorische-gaswaarde-ingest voor venster %s .. %s", gk_start, eind)
        gas_hhv = gaskwaliteit.fetch_actual_gas_hhv(gk_start, eind)

    # --- chunk-loop (hervatbaar, ontwerp §12.9) --------------------------------------------------
    # Elke chunk schrijft zijn eigen deel atomisch naar parts_dir; pas ná de hele loop worden de
    # eindtabellen samengevoegd (zie hieronder). Dat is wat hervatten mogelijk maakt: een chunk
    # waarvan alle deelbestanden al compleet zijn (van een vorige, afgebroken poging) staat niet in
    # `te_doen` en wordt hier dus niet opnieuw verwerkt.
    chunks = chunking.verdeel_in_chunks(te_verwerken, chunk_grootte)
    log.info("%d chunk(s) van ten hoogste %d woning(en)", len(chunks), chunk_grootte)
    parts_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw)
    log.info("%d van %d chunk(s) moeten (opnieuw) gedaan worden", len(te_doen), len(chunks))

    for teller, chunk_idx in enumerate(te_doen, start=1):
        chunk_ids = chunks[chunk_idx]
        homes_chunk = homes_gebruikt[homes_gebruikt["home_id__str"].isin(chunk_ids)].reset_index(drop=True)

        n_measurements = _verwerk_en_schrijf_chunk(
            bron, chunk_ids, homes_chunk, weer_tabel, gas_hhv, fetch_eigen_weer, parts_dir, chunk_idx
        )
        log.info(
            "chunk %d/%d (index %d, %d woning(en)) verwerkt: %s measurement-rij(en)",
            teller, len(te_doen), chunk_idx, len(chunk_ids), f"{n_measurements:,}",
        )

    # --- samenvoegen: streamend, zonder een volledige tabel in pandas te laden (ontwerp §12.9) ---
    paden: dict[str, Path] = {}
    n_rijen: dict[str, int] = {}
    for naam in chunking.PARTS_TABELLEN:
        pad = out_dir / f"{naam}.parquet"
        n_rijen[naam] = chunking.voeg_samen_streamend(parts_dir, naam, len(chunks), pad)
        paden[naam] = pad
        log.info("%s geschreven: %s (%d rijen)", naam, pad, n_rijen[naam])

    # --- eenmalige output (niet gechunkt, zie de module-docstring) -------------------------------
    homes_output = homes_gebruikt.copy()
    # installatiedatum_wp is een kale lokale maand (YYYY-MM -> 1e van de maand); die krijgt hier de
    # lokale tijdzone toegekend, zodat ook in `homes` elke tijdkolom tz-aware is (§12.10).
    homes_output["installatiedatum_wp"] = (
        homes_output["installatiedatum_wp"].dt.tz_localize(TZ_LOKAAL)
    )
    homes_output.to_parquet(out_dir / "homes.parquet", index=False)
    if not weer_tabel.empty:
        naar_lokale_tijdzone(weer_tabel).to_parquet(out_dir / "weer.parquet", index=False)

    # --- rapportaccumulator: altijd samengevoegd uit ALLE chunks (ontwerp §12.9/chunking.py) -----
    # Dit is dezelfde pas ongeacht of een chunk in DEZE run vers verwerkt is of hervat/overgeslagen:
    # er is maar één codepad, dat de per-chunk JSON-rapportdelen leest en optelt. Zie
    # RapportAccumulator.voeg_accumulator_toe voor waarom dat veilig is.
    acc = RapportAccumulator()
    for i in range(len(chunks)):
        deel = chunking.lees_rapport_deel(parts_dir, i)
        if deel is None:
            log.warning(
                "chunk %d: geen rapportdeel gevonden (ontbrekend of nog niet verwerkt); telt niet "
                "mee in het rapport",
                i,
            )
            continue
        acc.voeg_accumulator_toe(RapportAccumulator.uit_json_dict(deel))

    im3_weer_totaal = acc.samengevoegd_im3_weer()
    consistentie = pd.DataFrame()
    consistentie_geointerpoleerd = pd.DataFrame()
    if not im3_weer_totaal.empty and not weer_tabel.empty:
        consistentie = weer_mod.consistency_check(
            im3_weer_totaal, weer_tabel[weer_tabel["bron__cat"] == "eigen_ingest"]
        )
        # Alleen aanwezig bij --weer-geointerpoleerd-diagnose (§12.13); in een gewone run blijft
        # dit een lege tabel en toont report.py de vergelijking niet.
        geointerpoleerd = weer_tabel[weer_tabel["bron__cat"] == "eigen_ingest_geointerpoleerd"]
        if not geointerpoleerd.empty:
            consistentie_geointerpoleerd = weer_mod.consistency_check(im3_weer_totaal, geointerpoleerd)

    resultaat = {
        "acc": acc,
        "homes": homes_gebruikt,
        "weer": weer_tabel,
        "_weer_consistentie": consistentie,
        "_weer_consistentie_geointerpoleerd": consistentie_geointerpoleerd,
        "_im3_weer": im3_weer_totaal,
    }

    # Taak "rapport herbouwbaar zonder de run over te doen": de accumulator + de kleine, verder
    # nergens bewaarde rapportinvoer (weer-consistentie, welke stations in het IM3-weer voorkwamen)
    # gaan ALTIJD naar schijf, ongeacht `docs_dir` -- dit hoort net zo bij "de uitvoer van een run"
    # als de Parquet-tabellen, en is precies wat `python -m im3_preprocessing.report` straks nodig
    # heeft. Zie report.schrijf_accumulator voor het waarom van de gekozen vorm (JSON, niet pickle).
    report.schrijf_accumulator(
        out_dir / "rapport_accumulator.json",
        acc=acc,
        is_steekproef=home_ids is not None,
        weer_venster_dagen=weer_venster_dagen,
        weer_consistentie=consistentie,
        weer_consistentie_geointerpoleerd=consistentie_geointerpoleerd,
        im3_weer=im3_weer_totaal,
    )
    log.info("rapport_accumulator.json geschreven: %s", out_dir / "rapport_accumulator.json")

    if docs_dir is not None:
        docs_dir = Path(docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        report.write_report(
            docs_dir / "data-quality.md",
            acc=acc,
            homes=homes_gebruikt,
            weer_consistentie=consistentie,
            weer_consistentie_geointerpoleerd=consistentie_geointerpoleerd,
            im3_weer=im3_weer_totaal,
            weer=weer_tabel,
            is_steekproef=home_ids is not None,
            weer_venster_dagen=weer_venster_dagen,
        )
        log.info("data-quality.md geschreven: %s", docs_dir / "data-quality.md")

    # datapackage.json (Frictionless Data Package, zie datapackage.py) hoort net als data-quality.md
    # bij de documentatie van een run, en komt standaard in de repo-root te staan, naast README en
    # GEBRUIKSVOORWAARDEN.md, zoals in de WarmingUP- en DACS-HW-preprocessing. De inhoud komt
    # uitsluitend uit de code (tabellen.SCHEMAS), niet uit deze run; wat hier geschreven wordt is
    # dus identiek aan `python -m im3_preprocessing.datapackage`. None slaat het over (tests).
    if datapackage_pad is not None:
        datapackage_mod.schrijf_datapackage(Path(datapackage_pad))
        resultaat["datapackage"] = str(datapackage_pad)
        log.info("datapackage.json geschreven: %s", datapackage_pad)

    return resultaat


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help=(
            "Map met de ruwe data, of rechtstreeks het pad naar dataset_openbaar.zip. Staat de "
            "zip in de map, dan wordt daar direct uit gestreamd -- uitpakken naar schijf is niet "
            "nodig (zie im3_preprocessing.bron)"
        ),
    )
    p.add_argument(
        "--raw-bron",
        choices=("auto", "zip", "csv"),
        default="auto",
        help=(
            "Welke vorm van de ruwe data gebruikt wordt. 'auto' (standaard) kiest de zip als die "
            "er is, anders losse IM_customer_*.csv"
        ),
    )
    p.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    p.add_argument("--docs-dir", type=Path, default=Path("docs"))
    p.add_argument(
        "--datapackage-pad",
        type=Path,
        default=Path(datapackage_mod.DATAPACKAGE_BESTANDSNAAM),
        help=(
            "Waar datapackage.json (machineleesbare beschrijving van de uitvoer, zie "
            "im3_preprocessing.datapackage) aan het eind van de run geschreven wordt; standaard "
            "in de huidige map, dus de repo-root als je vanuit de repo-root draait"
        ),
    )
    p.add_argument(
        "--interim-dir",
        type=Path,
        default=Path("data/interim"),
        help=(
            "Map voor de tijdbereik-cache van een zip-bron (klein JSON-bestand; scheelt bij elke "
            "vervolgrun een volledige decompressiepass)"
        ),
    )
    p.add_argument("--sample-size", type=int, default=None, help="Verwerk alleen de eerste N woningen")
    p.add_argument("--home-ids", nargs="*", default=None, help="Verwerk alleen deze specifieke home_id's")
    p.add_argument(
        "--chunk-grootte",
        type=int,
        default=CHUNK_GROOTTE_STANDAARD,
        help=(
            "Aantal woningen per chunk; bepaalt het piekgeheugengebruik (~0,35 GB vast + 17 MB "
            "per woning). Groter is niet sneller, alleen duurder in geheugen; verlaag naar 10 op "
            f"een machine met weinig vrij RAM (standaard {CHUNK_GROOTTE_STANDAARD})"
        ),
    )
    p.add_argument("--skip-weer", action="store_true", help="Geen eigen KNMI-ingest (netwerk overslaan)")
    p.add_argument(
        "--weer-venster-dagen",
        type=int,
        default=None,
        help="Beperk de eigen KNMI-ingest tot de laatste N dagen (voor snelle steekproef-validatie)",
    )
    p.add_argument(
        "--weer-geointerpoleerd-diagnose",
        action="store_true",
        help=(
            "Haal ook de RBF-geospatiaal geïnterpoleerde weerreeks op naast de standaard rauwe "
            "stationswaarde (bron__cat 'eigen_ingest_geointerpoleerd'). Fors trager (§12.13); "
            "alleen nodig om de §12.4-vraag te herhalen of een consistentie-mismatch aan de "
            "interpolatiestap zelf ligt"
        ),
    )
    p.add_argument(
        "--skip-gaskwaliteit", action="store_true", help="Geen calorische-gaswaarde-ingest (netwerk overslaan)"
    )
    p.add_argument(
        "--gaskwaliteit-venster-dagen",
        type=int,
        default=None,
        help="Beperk de calorische-gaswaarde-ingest tot de laatste N dagen (voor snelle steekproef-validatie)",
    )
    p.add_argument(
        "--opnieuw",
        action="store_true",
        help=(
            "Gooi een eerdere (gedeeltelijke) run in --out-dir weg en begin schoon, in plaats van "
            "'m te hervatten. Zonder deze vlag worden chunks die al compleet op schijf staan "
            "overgeslagen (zie im3_preprocessing.chunking)"
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    home_ids = args.home_ids
    if home_ids is None and args.sample_size is not None:
        # Via de bron, niet via een glob: bij een zip-bron staan er helemaal geen losse CSV's.
        verkenner = bron_mod.maak_bron(
            args.raw_dir, voorkeur=args.raw_bron, cache_map=args.interim_dir
        )
        try:
            home_ids = verkenner.home_ids()[: args.sample_size]
        finally:
            verkenner.sluit()

    run(
        args.raw_dir,
        args.out_dir,
        home_ids=home_ids,
        raw_bron=args.raw_bron,
        interim_dir=args.interim_dir,
        fetch_eigen_weer=not args.skip_weer,
        weer_venster_dagen=args.weer_venster_dagen,
        weer_geointerpoleerd_diagnose=args.weer_geointerpoleerd_diagnose,
        fetch_gaskwaliteit=not args.skip_gaskwaliteit,
        gaskwaliteit_venster_dagen=args.gaskwaliteit_venster_dagen,
        docs_dir=args.docs_dir,
        chunk_grootte=args.chunk_grootte,
        opnieuw=args.opnieuw,
        datapackage_pad=args.datapackage_pad,
    )


if __name__ == "__main__":
    main()
