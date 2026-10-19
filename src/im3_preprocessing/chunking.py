# SPDX-License-Identifier: EUPL-1.2
"""Chunked, hervatbare verwerking van de woningen (ontwerp-preprocessing.md §12.9 introduceerde het
chunken zelf; deze module voegt HERVATTEN na een afbreking toe). Volgt het patroon van de
zusterrepo demoprojecthybride-dataset-preprocessing (``dph_preprocessing.chunking``, opgelost in
die repo een week eerder), hier aangepast aan wat IM3 werkelijk nodig heeft.

**Twee verschillen met de zusterrepo, allebei omdat IM3 er eenvoudiger vanaf komt:**

1. Geen ``interim/``-laag met een domeinbestand-per-chunk-split. Het knelpunt dat die laag daar
   oplost (één groot gedeeld bronbestand, tot 962 MB, dat anders per chunk opnieuw gelezen zou
   worden) speelt hier niet: ``im3_preprocessing.bron`` leest per woning een eigen klantbestand
   als stream (``bron.open_klantbestand(home_id)``), dus een chunk leest toch al alleen zijn eigen
   woningen, zonder gedeeld werk met andere chunks.
2. Drie contracttabellen per chunk (``measurements``, ``quality``, ``derived``), niet vijf.
   ``homes`` en ``weer`` worden in IM3 niet gechunkt: ``homes`` komt uit de (kleine, 6.283-rijen)
   metadata die toch al volledig in geheugen staat, en ``weer`` is een eenmalige, chunk-onafhankelijke
   KNMI-ingest die vóór de chunk-loop gebeurt (zie ``pipeline._run_met_bron``). Er is dus niets aan
   een van beide te hervatten.

   Daar staat een VIERDE, niet-contractueel deelbestand per chunk tegenover: ``rapport`` (JSON, geen
   Parquet). De rapportcijfers (``pipeline.RapportAccumulator``) hebben per chunk twee stukken
   brondata nodig die NERGENS in de drie contracttabellen staan: het door IM3 meegeleverde weer
   (``im3_weer``, bewust niet in ``weer.parquet`` opgenomen, zie ontwerp §12.8) en het aantal
   woningen zonder ``gas``-kolom in de bron (``n_zonder_gas``, een eigenschap van het ruwe
   klantbestand, niet van een afgeleide kolom). Zonder dit deelbestand zou een hervatte run de
   rapportbijdrage van een overgeslagen chunk stilzwijgend missen -- niet een foutmelding, een
   VERKEERD rapport, wat precies het probleem is dat hervatten niet mag veroorzaken. Anders dan
   ``measurements``/``quality``/``derived`` is dit deelbestand daarom WEL verplicht voor
   :func:`chunk_compleet`: een chunk waarvan de drie Parquet-delen compleet zijn maar het rapport-
   deel ontbreekt (het proces stierf ertussenin) telt hier bewust als "nog niet compleet".
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

#: Bovengrens aan de row-group-grootte in de samengevoegde output, losgekoppeld van
#: --chunk-grootte (ontwerp §12.9/§12.12): zonder deze grens zou een lezer van de output gedwongen
#: worden een hele chunk in één keer in te lezen, en zou de bestandsgrootte meeschalen met de
#: chunkgrootte in plaats van ongeveer constant te blijven.
ROW_GROUP_MAX = 1_000_000

#: De drie contract-tabellen die per chunk als apart Parquet-deelbestand geschreven worden. Zie de
#: module-docstring voor waarom ``homes``/``weer`` hier niet bij horen en waarom ``rapport`` (JSON,
#: niet Parquet) er apart naast staat als EXTRA verplicht deel.
PARTS_TABELLEN = ("measurements", "quality", "derived")

CHUNK_GROOTTE_STANDAARD = 25


def verdeel_in_chunks(home_ids: list[str], chunk_grootte: int) -> list[list[str]]:
    """Verdeel ``home_ids`` (in de gegeven volgorde) in opeenvolgende blokken van ``chunk_grootte``."""
    if chunk_grootte < 1:
        raise ValueError(f"chunk_grootte moet >= 1 zijn, kreeg {chunk_grootte}")
    return [home_ids[i : i + chunk_grootte] for i in range(0, len(home_ids), chunk_grootte)]


def chunk_pad(parts_dir: Path, tabel: str, chunk_idx: int) -> Path:
    """Het pad van het Parquet-deelbestand van ``tabel`` (zie :data:`PARTS_TABELLEN`) voor
    chunk ``chunk_idx``."""
    return parts_dir / tabel / f"chunk_{chunk_idx:03d}.parquet"


def rapport_pad(parts_dir: Path, chunk_idx: int) -> Path:
    """Het pad van het JSON-rapportdeel (niet-contractueel, zie module-docstring) voor
    chunk ``chunk_idx``."""
    return parts_dir / "rapport" / f"chunk_{chunk_idx:03d}.json"


def chunk_compleet(parts_dir: Path, chunk_idx: int) -> bool:
    """True als voor ``chunk_idx`` ALLE drie de contracttabellen ÉN het rapportdeel een
    (definitief, niet-``.tmp``) deelbestand hebben.

    Dit is de hervat-check: alleen als dit True is, mag een chunk overgeslagen worden. Eén
    ontbrekend deel (bv. het proces stierf na ``quality`` maar vóór ``derived``, of na alle drie
    tabellen maar vóór het rapportdeel) is genoeg om de hele chunk als "nog te doen" te behandelen
    -- zie :func:`ruim_chunk_op`.
    """
    return all(chunk_pad(parts_dir, tabel, chunk_idx).is_file() for tabel in PARTS_TABELLEN) and rapport_pad(
        parts_dir, chunk_idx
    ).is_file()


def ruim_chunk_op(parts_dir: Path, chunk_idx: int) -> None:
    """Verwijder alle (mogelijk halve) deelbestanden van ``chunk_idx``, inclusief eventuele
    achtergebleven ``.tmp``-bestanden van een eerdere, afgebroken poging. Bedoeld om vooraf te
    draaien voor elke chunk die opnieuw (of voor het eerst) gedaan gaat worden, zodat een oude,
    inconsistente deelverzameling nooit blijft liggen naast de nieuwe."""
    paden = [chunk_pad(parts_dir, tabel, chunk_idx) for tabel in PARTS_TABELLEN]
    paden.append(rapport_pad(parts_dir, chunk_idx))
    for pad in paden:
        for kandidaat in (pad, pad.with_suffix(pad.suffix + ".tmp")):
            if kandidaat.exists():
                kandidaat.unlink()


def schrijf_part_atomisch(pad: Path, df: pd.DataFrame) -> None:
    """Schrijf ``df`` naar ``pad`` via een tijdelijk bestand + hernoeming, zodat een halverwege
    afgebroken schrijfactie nooit een bestand met de DEFINITIEVE naam achterlaat (de garantie
    waarop :func:`chunk_compleet` leunt). ``Path.replace`` is op één filesystem atomisch."""
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(pad)


def schrijf_json_atomisch(pad: Path, data: dict) -> None:
    """Zelfde atomiciteitsgarantie als :func:`schrijf_part_atomisch`, voor het JSON-rapportdeel."""
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pad)


def lees_rapport_deel(parts_dir: Path, chunk_idx: int) -> dict | None:
    """Lees het JSON-rapportdeel van ``chunk_idx`` terug, of ``None`` als het (nog) ontbreekt."""
    pad = rapport_pad(parts_dir, chunk_idx)
    if not pad.is_file():
        return None
    return json.loads(pad.read_text(encoding="utf-8"))


#: Naam van het bestandje waarin het chunkplan van een run wordt vastgelegd (:func:`plan_vingerafdruk`).
PLAN_BESTAND = "plan.json"

#: Versie van het UITVOERCONTRACT: kolomnamen, eenheden, tijdzone en de semantiek van de waarden.
#:
#: **Hoog dit op zodra de uitvoer van vorm of betekenis verandert.** De vingerafdruk van het
#: chunkplan alleen is niet genoeg. In de DPH-zusterrepo is dat op 05-09-2026 bijna misgegaan: na
#: een dag met een weercorrectie, een tijdzonewijziging en hernoemde kolommen stonden er nog
#: deelbestanden van de OUDE code. Dezelfde woningen, dezelfde chunkgrootte, dus dezelfde
#: planvingerafdruk -- de hervatting zou ze klakkeloos hebben geaccepteerd en de oude uitvoer
#: hebben samengevoegd. Zonder foutmelding. Hier weegt dat zwaarder dan daar: een IM3-run duurt
#: zeven uur, dus een stil verkeerde hervatting kost een werkdag.
#:
#: Bewust een HANDMATIGE teller: automatisch schema vergelijken vergt dat je eerst een chunk bouwt
#: om te weten wat de huidige code oplevert, en juist in het geval dat ertoe doet -- alle chunks al
#: "compleet" -- bouw je er geen. Een vergeten ophoging is zichtbaar in een diff, stille
#: schemadrift niet.
UITVOER_CONTRACT_VERSIE = "2026-09-06-tijdstip-start-flows-ghi-w-m2"


def plan_vingerafdruk(chunks: list[list[str]]) -> str:
    """Een vingerafdruk van het chunkplan: welke woningen in welke chunk, in welke volgorde.

    Hervatten mag alleen als de bestaande deelbestanden bij HETZELFDE plan horen. Zonder deze
    controle kijkt :func:`chunk_compleet` alleen of de bestanden bestaan, en dan wordt een
    ``chunk_000.parquet`` uit een eerdere proefrun met bv. 5 woningen klakkeloos hergebruikt als
    chunk 1 van een run met 25 woningen per chunk -- de uitvoer mist dan stilzwijgend 20 woningen.
    Dat is precies zo gebeurd in de zusterrepo (05-09-2026, zie ``dph_preprocessing.chunking``) en
    is de reden dat deze functie ook hier bestaat: een hervatting die ongemerkt het verkeerde
    antwoord geeft is erger dan geen hervatting.
    """
    ruw = json.dumps(
        {"chunks": chunks, "contract": UITVOER_CONTRACT_VERSIE},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(ruw).hexdigest()


def _lees_plan(parts_dir: Path) -> str | None:
    pad = parts_dir / PLAN_BESTAND
    if not pad.is_file():
        return None
    try:
        return json.loads(pad.read_text(encoding="utf-8")).get("vingerafdruk")
    except (json.JSONDecodeError, OSError):
        return None


def _schrijf_plan(parts_dir: Path, chunks: list[list[str]]) -> None:
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / PLAN_BESTAND).write_text(
        json.dumps(
            {
                "vingerafdruk": plan_vingerafdruk(chunks),
                "n_chunks": len(chunks),
                "n_woningen": sum(len(c) for c in chunks),
                "chunk_grootte": max((len(c) for c in chunks), default=0),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def herstel_run(out_dir: Path, chunks: list[list[str]], opnieuw: bool) -> tuple[Path, list[int]]:
    """Bepaal ``(parts_dir, te_doen)`` aan het begin van een run.

    ``--opnieuw`` gooit ``parts/`` helemaal weg en begint schoon (``te_doen`` = alle chunks).
    Anders wordt eerst gecontroleerd of de aanwezige deelbestanden bij HETZELFDE chunkplan horen
    (:func:`plan_vingerafdruk`); zo niet, dan worden ze weggegooid, want ze gaan dan over een
    andere woningselectie of een andere ``--chunk-grootte``. Pas daarna wordt per chunk gekeken of
    hij al compleet is (:func:`chunk_compleet`); zo ja, wordt hij overgeslagen (gelogd, niet
    stilzwijgend), zo nee, worden zijn eventuele halve deelbestanden eerst opgeruimd
    (:func:`ruim_chunk_op`) zodat hij schoon opnieuw gedaan wordt.
    """
    parts_dir = out_dir / "parts"

    if opnieuw:
        log.info("--opnieuw: parts/ wordt gewist, alle chunks worden (her)gedaan")
        shutil.rmtree(parts_dir, ignore_errors=True)
        _schrijf_plan(parts_dir, chunks)
        return parts_dir, list(range(len(chunks)))

    bestaand = _lees_plan(parts_dir)
    huidig = plan_vingerafdruk(chunks)
    if parts_dir.exists() and bestaand != huidig:
        log.warning(
            "De aanwezige deelbestanden horen bij een ANDER chunkplan (%s) dan dit (%s); ze worden "
            "weggegooid en alle chunks worden opnieuw gedaan. Hervatten is alleen geldig binnen "
            "hetzelfde plan: zelfde woningselectie, zelfde chunkgrootte.",
            bestaand or "geen plan vastgelegd",
            huidig[:12],
        )
        shutil.rmtree(parts_dir, ignore_errors=True)
        _schrijf_plan(parts_dir, chunks)
        return parts_dir, list(range(len(chunks)))
    _schrijf_plan(parts_dir, chunks)

    te_doen = []
    for i in range(len(chunks)):
        if chunk_compleet(parts_dir, i):
            log.info("chunk %d/%d: al compleet, wordt overgeslagen", i + 1, len(chunks))
        else:
            log.info("chunk %d/%d: (nog) niet compleet, wordt (opnieuw) gedaan", i + 1, len(chunks))
            ruim_chunk_op(parts_dir, i)
            te_doen.append(i)
    return parts_dir, te_doen


def voeg_samen_streamend(parts_dir: Path, tabel: str, n_chunks: int, uitvoer_pad: Path) -> int:
    """Voeg alle ``chunk_*.parquet``-delen van ``tabel`` samen tot ``uitvoer_pad``, STREAMEND
    (``pyarrow.parquet.ParquetWriter`` + rij-groep-voor-rij-groep lezen), zonder ooit de volledige
    tabel als pandas-DataFrame in geheugen te nemen -- op de volledige dataset (~536 M rijen) is dat
    precies het geheugengebruik dat het chunken zelf al probeert te vermijden (ontwerp §12.9).

    Retourneert het totaal aantal weggeschreven rijen.
    """
    schema = None
    writer: pq.ParquetWriter | None = None
    n_rijen = 0
    try:
        for i in range(n_chunks):
            pad = chunk_pad(parts_dir, tabel, i)
            if not pad.is_file():
                continue  # kan voorkomen als een chunk leeg was (geen woningen, of geen rijen)
            parquet_file = pq.ParquetFile(pad)
            for row_group_idx in range(parquet_file.num_row_groups):
                tabel_arrow = parquet_file.read_row_group(row_group_idx)
                if writer is None:
                    schema = tabel_arrow.schema
                    writer = pq.ParquetWriter(uitvoer_pad, schema, compression="snappy")
                else:
                    tabel_arrow = tabel_arrow.cast(schema)
                writer.write_table(tabel_arrow, row_group_size=ROW_GROUP_MAX)
                n_rijen += tabel_arrow.num_rows
    finally:
        if writer is not None:
            writer.close()
    return n_rijen
