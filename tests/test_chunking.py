# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.chunking: chunk-partitionering, hervatten, en het samenvoegen van
deelbestanden (ontwerp §12.9: gechunkte, hervatbare verwerking van de volledige dataset).

Volgt hetzelfde patroon als de tests in de zusterrepo demoprojecthybride-dataset-preprocessing
(``tests/test_chunking.py`` daar), aangepast aan wat IM3 anders doet: drie contracttabellen i.p.v.
vijf, en een verplicht JSON-rapportdeel in plaats van een optioneel zesde Parquet-deel.
"""

from __future__ import annotations

import pandas as pd
import pytest

from im3_preprocessing import chunking


def test_verdeel_in_chunks():
    home_ids = [f"h{i}" for i in range(7)]
    chunks = chunking.verdeel_in_chunks(home_ids, 3)
    assert chunks == [["h0", "h1", "h2"], ["h3", "h4", "h5"], ["h6"]]


def test_verdeel_in_chunks_weigert_niet_positieve_grootte():
    with pytest.raises(ValueError):
        chunking.verdeel_in_chunks(["a"], 0)


def test_schrijf_part_atomisch_laat_geen_tmp_achter(tmp_path):
    pad = tmp_path / "measurements" / "chunk_000.parquet"
    df = pd.DataFrame({"a": [1, 2, 3]})
    chunking.schrijf_part_atomisch(pad, df)
    assert pad.is_file()
    assert not pad.with_suffix(".parquet.tmp").exists()
    terug = pd.read_parquet(pad)
    pd.testing.assert_frame_equal(terug, df)


def test_schrijf_json_atomisch_laat_geen_tmp_achter(tmp_path):
    parts_dir = tmp_path / "parts"
    pad = chunking.rapport_pad(parts_dir, 0)
    chunking.schrijf_json_atomisch(pad, {"a": 1})
    assert pad.is_file()
    assert not pad.with_suffix(".json.tmp").exists()
    assert chunking.lees_rapport_deel(parts_dir, 0) == {"a": 1}


def test_lees_rapport_deel_ontbrekend_geeft_none(tmp_path):
    assert chunking.lees_rapport_deel(tmp_path / "parts", 0) is None


def _schrijf_alle_delen(parts_dir, chunk_idx, met_rapport=True):
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, tabel, chunk_idx), pd.DataFrame({"a": [1]}))
    if met_rapport:
        chunking.schrijf_json_atomisch(chunking.rapport_pad(parts_dir, chunk_idx), {"a": 1})


def test_chunk_compleet_vereist_ook_het_rapportdeel(tmp_path):
    parts_dir = tmp_path / "parts"
    _schrijf_alle_delen(parts_dir, 0, met_rapport=False)
    assert chunking.chunk_compleet(parts_dir, 0) is False
    chunking.schrijf_json_atomisch(chunking.rapport_pad(parts_dir, 0), {"a": 1})
    assert chunking.chunk_compleet(parts_dir, 0) is True


def test_chunk_compleet_ziet_een_tmp_bestand_niet_als_compleet(tmp_path):
    parts_dir = tmp_path / "parts"
    _schrijf_alle_delen(parts_dir, 0)
    assert chunking.chunk_compleet(parts_dir, 0) is True
    # Simuleer een halverwege afgebroken herschrijving: alleen het .tmp-bestand van "derived".
    definitief = chunking.chunk_pad(parts_dir, "derived", 0)
    definitief.unlink()
    definitief.with_suffix(definitief.suffix + ".tmp").write_bytes(b"half geschreven, geen geldig parquet")
    assert chunking.chunk_compleet(parts_dir, 0) is False


def test_ruim_chunk_op_verwijdert_definitief_en_tmp_inclusief_rapportdeel(tmp_path):
    parts_dir = tmp_path / "parts"
    _schrijf_alle_delen(parts_dir, 0)
    tmp_extra = chunking.chunk_pad(parts_dir, "derived", 0).with_suffix(".parquet.tmp")
    tmp_extra.write_bytes(b"restant van een vorige, afgebroken poging")

    chunking.ruim_chunk_op(parts_dir, 0)

    for tabel in chunking.PARTS_TABELLEN:
        assert not chunking.chunk_pad(parts_dir, tabel, 0).exists()
    assert not chunking.rapport_pad(parts_dir, 0).exists()
    assert not tmp_extra.exists()


def test_herstel_run_slaat_complete_chunks_over_en_ruimt_incomplete_op(tmp_path):
    out_dir = tmp_path / "out"
    chunks = [["a"], ["b"], ["c"]]
    # Eerst een run beginnen, zodat het chunkplan vastligt.
    chunking.herstel_run(out_dir, chunks, opnieuw=False)
    # Chunk 0: helemaal compleet (incl. rapportdeel). Chunk 1: alleen de drie Parquet-delen, GEEN
    # rapportdeel -- dus niet compleet, moet opgeruimd worden.
    _schrijf_alle_delen(out_dir / "parts", 0)
    _schrijf_alle_delen(out_dir / "parts", 1, met_rapport=False)

    parts_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw=False)
    assert te_doen == [1, 2]
    for tabel in chunking.PARTS_TABELLEN:
        assert not chunking.chunk_pad(parts_dir, tabel, 1).exists()
    assert chunking.chunk_compleet(parts_dir, 0) is True


def test_herstel_run_opnieuw_wist_alles(tmp_path):
    out_dir = tmp_path / "out"
    chunks = [["a"]]
    _schrijf_alle_delen(out_dir / "parts", 0)

    parts_dir, te_doen = chunking.herstel_run(out_dir, chunks, opnieuw=True)
    assert te_doen == [0]
    assert not chunking.chunk_compleet(parts_dir, 0)
    assert list(parts_dir.glob("*/*.parquet")) == []
    assert (parts_dir / chunking.PLAN_BESTAND).is_file()


def test_voeg_samen_streamend_behoudt_alle_rijen_en_volgorde(tmp_path):
    parts_dir = tmp_path / "parts"
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "measurements", 0), pd.DataFrame({"home_id__str": ["a", "a"], "x": [1, 2]})
    )
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "measurements", 1), pd.DataFrame({"home_id__str": ["b"], "x": [3]})
    )
    uitvoer = tmp_path / "measurements.parquet"
    n = chunking.voeg_samen_streamend(parts_dir, "measurements", 2, uitvoer)
    assert n == 3
    resultaat = pd.read_parquet(uitvoer)
    assert resultaat["x"].tolist() == [1, 2, 3]


def test_voeg_samen_streamend_slaat_ontbrekende_chunks_over(tmp_path):
    # Chunk 1 heeft geen deelbestand (bv. een lege chunk); dat mag geen fout geven.
    parts_dir = tmp_path / "parts"
    chunking.schrijf_part_atomisch(
        chunking.chunk_pad(parts_dir, "quality", 0), pd.DataFrame({"home_id__str": ["a"]})
    )
    uitvoer = tmp_path / "quality.parquet"
    n = chunking.voeg_samen_streamend(parts_dir, "quality", 2, uitvoer)
    assert n == 1


def test_hervatten_weigert_deelbestanden_van_een_ander_chunkplan(tmp_path):
    """Deelbestanden van een ANDER plan mogen niet hergebruikt worden (chunking.plan_vingerafdruk).

    Zelfde regressie als in de zusterrepo (05-09-2026): een chunk_000 uit een proefrun met een
    kleinere chunkgrootte/woningselectie mag nooit stilzwijgend hergebruikt worden voor een groter
    plan -- de uitvoer zou dan woningen missen zonder foutmelding.
    """
    out_dir = tmp_path / "out"
    plan_klein = [["a", "b"]]
    parts_dir, te_doen = chunking.herstel_run(out_dir, plan_klein, opnieuw=False)
    assert te_doen == [0]

    _schrijf_alle_delen(parts_dir, 0)
    assert chunking.chunk_compleet(parts_dir, 0)

    # zelfde plan: chunk 0 mag overgeslagen worden
    _, te_doen = chunking.herstel_run(out_dir, plan_klein, opnieuw=False)
    assert te_doen == []

    # ANDER plan (meer woningen in dezelfde chunk): niets mag hergebruikt worden
    plan_groot = [["a", "b", "c", "d"]]
    parts_dir, te_doen = chunking.herstel_run(out_dir, plan_groot, opnieuw=False)
    assert te_doen == [0]
    assert not chunking.chunk_compleet(parts_dir, 0), "oude deelbestanden zijn niet opgeruimd"


def test_plan_vingerafdruk_onderscheidt_selectie_en_chunkgrootte():
    a = chunking.plan_vingerafdruk([["h1", "h2"], ["h3"]])
    assert a == chunking.plan_vingerafdruk([["h1", "h2"], ["h3"]])
    assert a != chunking.plan_vingerafdruk([["h1", "h2", "h3"]]), "andere chunkgrootte"
    assert a != chunking.plan_vingerafdruk([["h1", "h2"], ["h4"]]), "andere woningselectie"
    assert a != chunking.plan_vingerafdruk([["h3"], ["h1", "h2"]]), "andere volgorde"


def test_hervatten_weigert_deelbestanden_van_een_ander_uitvoercontract(tmp_path, monkeypatch):
    """Zelfde woningen en chunkgrootte, ander uitvoercontract: niet hergebruiken.

    De planvingerafdruk alleen dekt dit niet. In de DPH-zusterrepo leidde datzelfde gat bijna tot
    een stille fout: deelbestanden van vóór een weercorrectie, een tijdzonewijziging en hernoemde
    kolommen waren onder een identiek plan gewoon geaccepteerd. Hier kost dat zeven uur.
    """
    out_dir = tmp_path / "out"
    plan = [["a", "b"]]
    parts_dir, te_doen = chunking.herstel_run(out_dir, plan, opnieuw=False)
    assert te_doen == [0]
    for tabel in chunking.PARTS_TABELLEN:
        chunking.schrijf_part_atomisch(chunking.chunk_pad(parts_dir, tabel, 0), pd.DataFrame({"x": [1]}))
    # chunk_compleet eist naast de drie tabellen ook het rapportdeel
    rp = chunking.rapport_pad(parts_dir, 0)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("{}", encoding="utf-8")
    assert chunking.chunk_compleet(parts_dir, 0)
    assert chunking.herstel_run(out_dir, plan, opnieuw=False)[1] == []

    monkeypatch.setattr(chunking, "UITVOER_CONTRACT_VERSIE", "een-andere-versie")
    parts_dir, te_doen = chunking.herstel_run(out_dir, plan, opnieuw=False)
    assert te_doen == [0]
    assert not chunking.chunk_compleet(parts_dir, 0), "oude deelbestanden zijn niet opgeruimd"
