# SPDX-License-Identifier: EUPL-1.2
"""Tests voor im3_preprocessing.opmaak: Nederlandse getalopmaak voor de gegenereerde rapporten
(komma als decimaalteken, punt per duizendtal vanaf 10.000, vaste spatie voor het procentteken --
zie de module-docstring van ``opmaak`` voor de volledige uitleg).
"""

from __future__ import annotations

from im3_preprocessing import opmaak


# --------------------------------------------------------------------------------------------
# getal()
# --------------------------------------------------------------------------------------------


def test_getal_nul():
    assert opmaak.getal(0) == "0"


def test_getal_negatief():
    assert opmaak.getal(-1924.16, 2) == "-1924,16"


def test_getal_negatief_boven_de_groepeergrens():
    assert opmaak.getal(-12345) == "-12.345"


def test_getal_nan():
    assert opmaak.getal(float("nan")) == "-"


def test_getal_none():
    assert opmaak.getal(None) == "-"


def test_getal_inf():
    assert opmaak.getal(float("inf")) == "-"


def test_getal_precies_9999_geen_scheidingsteken():
    # Onder de groepeergrens (10.000): geen punt, ook al zijn het al vier cijfers.
    assert opmaak.getal(9999) == "9999"


def test_getal_precies_10000_wel_scheidingsteken():
    assert opmaak.getal(10000) == "10.000"


def test_getal_jaartal_blijft_ongegroepeerd():
    # De hele reden voor de groepeergrens: 2022 mag nooit "2.022" worden.
    assert opmaak.getal(2022) == "2022"


def test_getal_groot_getal_met_meerdere_scheidingstekens():
    assert opmaak.getal(8637833) == "8.637.833"


def test_getal_met_decimalen_gebruikt_komma():
    assert opmaak.getal(3.75, 2) == "3,75"


def test_getal_aangepaste_lege_waarde():
    assert opmaak.getal(None, leeg="n.v.t.") == "n.v.t."


# --------------------------------------------------------------------------------------------
# percentage()
# --------------------------------------------------------------------------------------------


def test_percentage_fractie_naar_percentage():
    # Dit is de kernvalkuil uit de opdracht: percentage() verwacht een FRACTIE, geen percentage.
    assert opmaak.percentage(0.246) == "24,6" + opmaak.VASTE_SPATIE + "%"


def test_percentage_nul():
    assert opmaak.percentage(0.0) == "0,0" + opmaak.VASTE_SPATIE + "%"


def test_percentage_negatief():
    assert opmaak.percentage(-0.0002, 2) == "-0,02" + opmaak.VASTE_SPATIE + "%"


def test_percentage_nan():
    assert opmaak.percentage(float("nan")) == "-"


def test_percentage_none():
    assert opmaak.percentage(None) == "-"


def test_percentage_gebruikt_vaste_spatie_niet_een_gewone():
    resultaat = opmaak.percentage(0.5)
    # Vóór het procentteken hoort een vaste spatie (U+00A0) te staan, geen gewone spatie (die zou
    # over een regeleinde kunnen breken).
    assert resultaat == "50,0" + opmaak.VASTE_SPATIE + "%"
    assert " %" not in resultaat


# --------------------------------------------------------------------------------------------
# aandeel()
# --------------------------------------------------------------------------------------------


def test_aandeel_basis():
    verwacht = "2.120.529 van 8.637.503 (24,6" + opmaak.VASTE_SPATIE + "%)"
    assert opmaak.aandeel(2120529, 8637503) == verwacht


def test_aandeel_noemer_nul():
    assert opmaak.aandeel(0, 0) == "0 van 0"


def test_aandeel_noemer_none():
    assert opmaak.aandeel(5, None) == "-"


def test_aandeel_kleine_getallen_geen_scheidingsteken():
    verwacht = "1 van 3 (33,3" + opmaak.VASTE_SPATIE + "%)"
    assert opmaak.aandeel(1, 3) == verwacht
