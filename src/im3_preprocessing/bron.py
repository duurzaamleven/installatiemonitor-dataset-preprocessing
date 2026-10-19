# SPDX-License-Identifier: EUPL-1.2
"""Waar de ruwe IM3-bestanden vandaan komen: een uitgepakte map óf de zip zelf (ontwerp §12.11).

De dataset wordt als één ``dataset_openbaar.zip`` van 3,2 GB gedownload en is uitgepakt 23,9 GB.
Uitpakken is hier **onderdeel van de preprocessing** in plaats van een handmatige stap vooraf: de
pipeline leest de klantbestanden rechtstreeks als stream uit het archief, zodat er geen 23,9 GB aan
losse CSV's op de schijf hoeft te staan, niet tijdens de run en niet erna.

Dat kán omdat elk klantbestand precies één keer, sequentieel, van begin tot eind wordt gelezen.
Deflate is een stream-formaat: ``zipfile.ZipFile.open()`` geeft een file-object dat blok voor blok
decomprimeert, en ``pandas.read_csv`` leest daar direct uit. Het piekgeheugen is daarmee dat van
één klantbestand als DataFrame (hetzelfde als bij losse CSV's) plus een decompressiebuffer van
enkele tientallen kB.

Twee bronnen, één interface (:class:`Bron`):

- :class:`MapBron`: een map met losse ``IM_customer_*.csv``. Blijft bestaan: wie de dataset al
  uitgepakt heeft hoeft niets te veranderen, en de tests draaien erop.
- :class:`ZipBron`: het archief zelf.

Gemeten op de echte dataset (26-aug-2026, 8 cores): de centrale directory lezen kost 0,1 s,
volledige decompressie loopt op ~228 MB/s (~105 s voor alle 23,9 GB, één thread). Het lezen uit de
zip is dus niet trager dan van schijf: er wordt 3,2 GB in plaats van 23,9 GB van schijf gehaald,
en de CPU-tijd van deflate valt weg tegen die van het CSV-parsen.
"""

from __future__ import annotations

import json
import logging
import threading
import zipfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

import pandas as pd

from .timestamps import TZ_LOKAAL

log = logging.getLogger(__name__)

METADATA_BESTANDSNAAM = "00_IM_meta_data_openbaar.csv"
KLANT_PREFIX = "IM_customer_"
KLANT_SUFFIX = ".csv"

# Aantal bytes dat van het einde van een klantbestand nodig is om de laatste dataregel compleet te
# hebben. Een regel is ~60 bytes; 4 kB is ruim en past in één blok.
STAART_BYTES = 4096


class BronError(ValueError):
    """De opgegeven ruwe-databron is niet bruikbaar. Hoort niet stil te falen."""


def home_id_van_bestandsnaam(naam: str) -> str:
    """``IM_customer_1000.csv`` -> ``"1000"`` (werkt op een kale naam, niet op een pad)."""
    if not (naam.startswith(KLANT_PREFIX) and naam.endswith(KLANT_SUFFIX)):
        raise BronError(f"Onverwachte bestandsnaam, verwacht '{KLANT_PREFIX}<id>{KLANT_SUFFIX}': {naam}")
    return naam[len(KLANT_PREFIX) : -len(KLANT_SUFFIX)]


def bestandsnaam_van_home_id(home_id: str) -> str:
    return f"{KLANT_PREFIX}{home_id}{KLANT_SUFFIX}"


def _parse_datetime_veld(veld: str) -> pd.Timestamp | None:
    """Eerste CSV-veld -> een tz-aware UTC-tijdstempel die GEGARANDEERD niet later is dan het
    werkelijke ``tijdstip_start`` dat :func:`im3_preprocessing.timestamps.resolve_timestamps`
    voor deze regel zou opleveren, of ``None`` als het niet parseert.

    Dit hoeft géén exacte ``resolve_timestamps``-uitkomst te zijn (en kan dat, zonder de
    ``interval_type``-kolom te lezen, ook niet meer zijn sinds ontwerp-intervalsemantiek.md §4:
    ``q`` en ``h`` trekken een verschillende vaste duur af, en ``d``/``m`` verschillen juist WEL
    per type, in plaats van zoals voorheen hetzelfde te doen). Voor een venstergrens is een
    conservatieve ONDERSCHATTING voldoende en veilig: het venster wordt dan hooguit iets breder
    dan strikt nodig (extra fetch-kosten), nooit te smal (dat zou rijen buiten het venster laten
    vallen).

    - een veld mét tijdzone (de ``q``/``h``-rijen) is UTC; er wordt de grootste van de twee
      mogelijke duren (3600 s, de ``h``-duur) afgetrokken. Voor een echte ``q``-rij is dat 2700 s
      te veel, maar altijd aan de veilige kant.
    - een **kale datum zonder tijdzone** (de ``d``/``m``-rijen) is een *lokale* datum; er wordt
      altijd de EERSTE dag van diezelfde lokale maand gebruikt (de ``m``-regel). Voor een echte
      ``d``-rij is dat tot ~30 dagen te vroeg, ook altijd aan de veilige kant.

    **Dit ging eerder mis (§12.15).** De vorige versie las álles als UTC, met de redenering dat het
    voor een venstergrens "hooguit één uur" zou schelen. Dat klopte twee keer niet: het is de volle
    UTC-offset, dus **twee** uur in de zomertijd, en er werd nergens een marge op het venster
    toegepast. Omdat de eerste regel van een klantbestand vrijwel altijd een ``m``-rij is, viel de
    ondergrens van het weer-/gaskwaliteitvenster daardoor structureel te laat: op de volledige run
    begon ``weer.parquet`` exact 2 uur ná ``measurements.parquet``. Rijen in dat gat kregen stil
    ``ontbrekend_buiten_archief``. De hier gekozen conservatieve onderschatting is een structurele
    oplossing voor diezelfde klasse fout: bij twijfel te vroeg, nooit te laat.

    Middernacht is in Europe/Amsterdam nooit ambigu of niet-bestaand (de DST-overgang valt op
    02:00-03:00 lokaal), dus er is hier geen ``ambiguous``/``nonexistent``-keuze nodig.
    """
    tijd = pd.to_datetime(veld.strip().strip('"'), errors="coerce")
    if pd.isna(tijd):
        return None
    if tijd.tzinfo is None:
        eerste_van_maand = tijd.to_period("M").to_timestamp()
        return eerste_van_maand.tz_localize(TZ_LOKAAL).tz_convert("UTC")
    return tijd.tz_convert("UTC") - pd.Timedelta(seconds=3600)


def _tijden_uit_regels(eerste: bytes | None, laatste: bytes | None) -> list[pd.Timestamp]:
    tijden = []
    for regel in (eerste, laatste):
        if not regel:
            continue
        veld = regel.decode("utf-8", "replace").split(",", 1)[0]
        tijd = _parse_datetime_veld(veld)
        if tijd is not None:
            tijden.append(tijd)
    return tijden


class Bron(ABC):
    """Levert de ruwe IM3-bestanden als streams, ongeacht of ze los of gezipt op schijf staan."""

    #: Korte omschrijving voor de log, bv. ``"zip data/raw/dataset_openbaar.zip"``.
    omschrijving: str

    @abstractmethod
    def home_ids(self) -> list[str]:
        """Alle beschikbare ``home_id``'s, gesorteerd zoals de bestandsnamen sorteren."""

    @abstractmethod
    def bevat(self, home_id: str) -> bool: ...

    @abstractmethod
    def open_klantbestand(self, home_id: str) -> "AbstractContextManager[BinaryIO]":
        """Context manager over het ruwe klantbestand, als binaire stream."""

    @abstractmethod
    def open_metadata(self) -> "AbstractContextManager[BinaryIO]":
        """Context manager over ``00_IM_meta_data_openbaar.csv``, als binaire stream."""

    @abstractmethod
    def _kop_en_staart(self, home_id: str) -> tuple[bytes | None, bytes | None]:
        """Eerste en laatste **dataregel** (header overgeslagen) van één klantbestand."""

    def sluit(self) -> None:
        """Geef onderliggende handles vrij. Standaard een no-op."""

    def tijdbereik(self, home_ids: list[str]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        """Globaal ``(start, eind)`` over de opgegeven woningen.

        Nodig vóór de chunk-loop, want de weer- en gaskwaliteit-ingest gebeuren éénmalig voor het
        hele bereik. Er wordt uitsluitend naar de eerste en de laatste dataregel per bestand
        gekeken; dat leunt erop dat elk klantbestand op tijd gesorteerd is (geverifieerd op een
        steekproef van 8 bestanden, 26-aug-2026). Mocht dat ergens tóch niet gelden, dan valt dat
        later op als rijen buiten het opgehaalde weervenster vallen: die krijgen
        ``ontbrekend_buiten_archief`` in plaats van stilzwijgend een verkeerde waarde.
        """
        starts: list[pd.Timestamp] = []
        eindes: list[pd.Timestamp] = []
        for home_id in home_ids:
            tijden = _tijden_uit_regels(*self._kop_en_staart(home_id))
            if tijden:
                starts.append(min(tijden))
                eindes.append(max(tijden))
        if not starts:
            return None, None
        return min(starts), max(eindes)


class MapBron(Bron):
    """Een map met losse, al uitgepakte ``IM_customer_*.csv``-bestanden."""

    def __init__(self, map_pad: str | Path):
        self.map_pad = Path(map_pad)
        if not self.map_pad.is_dir():
            raise BronError(f"Geen map: {self.map_pad}")
        self.omschrijving = f"map {self.map_pad}"

    def home_ids(self) -> list[str]:
        return [home_id_van_bestandsnaam(p.name) for p in sorted(self.map_pad.glob("IM_customer_*.csv"))]

    def _pad(self, home_id: str) -> Path:
        return self.map_pad / bestandsnaam_van_home_id(home_id)

    def bevat(self, home_id: str) -> bool:
        return self._pad(home_id).exists()

    @contextmanager
    def open_klantbestand(self, home_id: str) -> Iterator[BinaryIO]:
        with open(self._pad(home_id), "rb") as f:
            yield f

    @contextmanager
    def open_metadata(self) -> Iterator[BinaryIO]:
        pad = self.map_pad / METADATA_BESTANDSNAAM
        if not pad.exists():
            raise BronError(f"Metadatabestand ontbreekt: {pad}")
        with open(pad, "rb") as f:
            yield f

    def _kop_en_staart(self, home_id: str) -> tuple[bytes | None, bytes | None]:
        """Alleen kop en staart lezen: een losse CSV is seekbaar, dus dit kost twee blokken I/O."""
        with open(self._pad(home_id), "rb") as f:
            f.readline()  # header
            eerste = f.readline().strip() or None

            # Vanaf het einde terugstappen, zodat ook een afsluitende newline geen lege laatste
            # regel oplevert.
            f.seek(0, 2)
            grootte = f.tell()
            blok = min(STAART_BYTES, grootte)
            f.seek(grootte - blok)
            regels = f.read(blok).strip().splitlines()
            laatste = regels[-1].strip() if regels else None
        return eerste, laatste


class ZipBron(Bron):
    """Het gedownloade ``dataset_openbaar.zip``, gelezen als stream en nooit uitgepakt naar schijf.

    Per thread wordt één eigen :class:`zipfile.ZipFile` aangehouden: een ``ZipFile`` deelt één
    onderliggende file-handle en is daarmee niet thread-safe, en de kop/staart-scan draait wél
    parallel (zie :meth:`tijdbereik`).
    """

    def __init__(self, zip_pad: str | Path, cache_map: str | Path | None = None, workers: int = 8):
        self.zip_pad = Path(zip_pad)
        if not self.zip_pad.is_file():
            raise BronError(f"Geen bestand: {self.zip_pad}")
        self.cache_map = Path(cache_map) if cache_map is not None else None
        self.workers = max(1, workers)
        self.omschrijving = f"zip {self.zip_pad}"
        self._lokaal = threading.local()
        self._alle_zips: list[zipfile.ZipFile] = []
        self._zips_lock = threading.Lock()

        namen = set(self._zip().namelist())
        if METADATA_BESTANDSNAAM not in namen:
            raise BronError(f"{self.zip_pad.name}: {METADATA_BESTANDSNAAM} ontbreekt in het archief")
        self._namen = namen

    def _zip(self) -> zipfile.ZipFile:
        z = getattr(self._lokaal, "zip", None)
        if z is None:
            z = zipfile.ZipFile(self.zip_pad)
            self._lokaal.zip = z
            with self._zips_lock:
                self._alle_zips.append(z)
        return z

    def sluit(self) -> None:
        with self._zips_lock:
            for z in self._alle_zips:
                z.close()
            self._alle_zips.clear()
        self._lokaal = threading.local()

    def home_ids(self) -> list[str]:
        namen = [
            n for n in self._namen if n.startswith(KLANT_PREFIX) and n.endswith(KLANT_SUFFIX)
        ]
        return [home_id_van_bestandsnaam(n) for n in sorted(namen)]

    def bevat(self, home_id: str) -> bool:
        return bestandsnaam_van_home_id(home_id) in self._namen

    @contextmanager
    def open_klantbestand(self, home_id: str) -> Iterator[BinaryIO]:
        with self._zip().open(bestandsnaam_van_home_id(home_id)) as f:
            yield f

    @contextmanager
    def open_metadata(self) -> Iterator[BinaryIO]:
        with self._zip().open(METADATA_BESTANDSNAAM) as f:
            yield f

    def _kop_en_staart(self, home_id: str) -> tuple[bytes | None, bytes | None]:
        """Streamend: een deflate-stream is niet seekbaar, dus het hele lid moet er doorheen.

        Er wordt niets van vastgehouden behalve de laatste :data:`STAART_BYTES`, dus het geheugen is
        dus constant, ook bij een klantbestand van tientallen MB.
        """
        with self.open_klantbestand(home_id) as f:
            f.readline()  # header
            eerste = f.readline().strip() or None
            staart = b""
            while True:
                blok = f.read(1 << 20)
                if not blok:
                    break
                staart = (staart + blok)[-STAART_BYTES:]
        regels = staart.strip().splitlines()
        laatste = regels[-1].strip() if regels else None
        return eerste, laatste

    # --- tijdbereik: parallel + gecachet ---------------------------------------------------

    def tijdbereik(self, home_ids: list[str]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        """Zelfde uitkomst als :meth:`Bron.tijdbereik`, maar parallel en met een cache op schijf.

        Anders dan bij losse CSV's kost dit een volledige decompressiepass (~105 s bij één thread,
        ~63 s bij acht). Dat is eenmalig per zip: de gevonden eerste/laatste tijdstempel per woning
        gaat naar een klein JSON-cachebestand in ``data/interim``, geldig zolang naam, grootte en
        wijzigingstijd van de zip niet veranderen. Een vervolgrun leest dat terug in milliseconden,
        ook met een andere selectie woningen.
        """
        cache = self._cache_lees()
        ontbrekend = [h for h in home_ids if h not in cache]

        if ontbrekend:
            log.info(
                "Tijdbereik-scan over %d klantbestand(en) in %s (deflate is niet seekbaar, dus "
                "één decompressiepass; het resultaat wordt gecachet)",
                len(ontbrekend), self.zip_pad.name,
            )
            with ThreadPoolExecutor(self.workers) as ex:
                for home_id, (eerste, laatste) in zip(
                    ontbrekend, ex.map(self._kop_en_staart, ontbrekend)
                ):
                    tijden = _tijden_uit_regels(eerste, laatste)
                    cache[home_id] = (
                        [min(tijden).isoformat(), max(tijden).isoformat()] if tijden else []
                    )
            self._cache_schrijf(cache)

        starts: list[pd.Timestamp] = []
        eindes: list[pd.Timestamp] = []
        for home_id in home_ids:
            paar = cache.get(home_id) or []
            if len(paar) == 2:
                starts.append(pd.Timestamp(paar[0]))
                eindes.append(pd.Timestamp(paar[1]))
        if not starts:
            return None, None
        return min(starts), max(eindes)

    def _cache_pad(self) -> Path | None:
        if self.cache_map is None:
            return None
        return self.cache_map / f"tijdbereik-{self.zip_pad.stem}.json"

    #: Ophogen zodra de betekenis van de gecachete waarden verandert. Een cache met een andere
    #: versie wordt genegeerd en opnieuw opgebouwd. Zonder dit zou een fix in
    #: :func:`_parse_datetime_veld` stilzwijgend geen effect hebben op een machine die de oude,
    #: foute waarden al gecachet had (§12.15) en pas na uren rekenen opvallen.
    #: 3: begin-van-interval-conventie (ontwerp-intervalsemantiek.md §4) -- de venstergrens is nu
    #: een conservatieve onderschatting i.p.v. een exacte match met resolve_timestamps.
    CACHE_VERSIE = 3

    def _cache_sleutel(self) -> dict:
        st = self.zip_pad.stat()
        return {
            "versie": self.CACHE_VERSIE,
            "naam": self.zip_pad.name,
            "bytes": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        }

    def _cache_lees(self) -> dict[str, list[str]]:
        pad = self._cache_pad()
        if pad is None or not pad.exists():
            return {}
        try:
            inhoud = json.loads(pad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Een kapotte cache is geen fout, hooguit een verloren optimalisatie.
            log.warning("Tijdbereik-cache %s onleesbaar; opnieuw scannen", pad)
            return {}
        if inhoud.get("zip") != self._cache_sleutel():
            log.info(
                "Tijdbereik-cache hoort bij een andere zip of een oudere cacheversie; opnieuw scannen"
            )
            return {}
        return inhoud.get("per_woning", {})

    def _cache_schrijf(self, per_woning: dict[str, list[str]]) -> None:
        pad = self._cache_pad()
        if pad is None:
            return
        try:
            pad.parent.mkdir(parents=True, exist_ok=True)
            pad.write_text(
                json.dumps({"zip": self._cache_sleutel(), "per_woning": per_woning}),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Tijdbereik-cache niet weggeschreven (%s): %s", pad, exc)


def maak_bron(
    raw_pad: str | Path, voorkeur: str = "auto", cache_map: str | Path | None = None
) -> Bron:
    """Kies de databron op basis van wat er staat.

    ``raw_pad`` mag een zip-bestand zijn of een map. Bij een map met ``voorkeur="auto"`` wint een
    zip van losse CSV's: de zip is het artefact zoals het gedownload is en dus de canonieke ruwe
    data (ontwerp §3, principe 7: ``raw`` wordt nooit overschreven). Losse CSV's ernaast zijn een
    eerdere handmatige uitpakstap die je gerust kunt weggooien.

    ``voorkeur="zip"`` of ``"csv"`` dwingt de keuze af, bv. om beide paden tegen elkaar te meten.
    """
    if voorkeur not in ("auto", "zip", "csv"):
        raise BronError(f"Onbekende bronvoorkeur {voorkeur!r}, verwacht 'auto', 'zip' of 'csv'")

    raw_pad = Path(raw_pad)

    if raw_pad.is_file():
        if voorkeur == "csv":
            raise BronError(f"--raw-bron csv gevraagd, maar {raw_pad} is een bestand, geen map")
        return ZipBron(raw_pad, cache_map=cache_map)

    if not raw_pad.is_dir():
        raise BronError(f"Ruwe databron bestaat niet: {raw_pad}")

    zips = sorted(raw_pad.glob("*.zip"))
    heeft_csv = any(raw_pad.glob("IM_customer_*.csv"))

    if voorkeur == "csv":
        if not heeft_csv:
            raise BronError(f"Geen IM_customer_*.csv gevonden in {raw_pad}")
        return MapBron(raw_pad)

    if voorkeur == "zip" or (voorkeur == "auto" and zips):
        if not zips:
            raise BronError(f"Geen *.zip gevonden in {raw_pad}")
        if len(zips) > 1:
            raise BronError(
                f"Meerdere zip-bestanden in {raw_pad}: {[z.name for z in zips]}. Wijs er expliciet "
                "één aan met --raw-dir <pad naar .zip>"
            )
        if heeft_csv:
            log.info(
                "Zowel %s als losse IM_customer_*.csv gevonden in %s; de zip wordt gebruikt "
                "(de losse CSV's zijn overbodig en mogen weg). Forceer met --raw-bron csv.",
                zips[0].name, raw_pad,
            )
        return ZipBron(zips[0], cache_map=cache_map)

    if not heeft_csv:
        raise BronError(f"Geen *.zip en geen IM_customer_*.csv gevonden in {raw_pad}")
    return MapBron(raw_pad)
