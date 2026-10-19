# SPDX-License-Identifier: EUPL-1.2
"""Nederlandse getalopmaak voor de gegenereerde rapporten.

**In de code zelf verandert er niets.** Python parseert alleen een punt als decimaalteken, dus
getalliterals blijven `3.14`, en voor cijfergroepering blijft de underscore uit PEP 515 de
conventie (`3_600_000.0`). Locale hoort thuis op de grens naar de lezer, niet in de broncode.

Op die grens ging het wel mis. De rapporten gebruikten `{:,}`, wat `8,637,833` oplevert. Voor een
Nederlandse lezer is dat geen groot getal maar een getal met decimalen -- precies de verwarring die
een scheidingsteken hoort weg te nemen. Vandaar deze module:

- **komma** als decimaalteken;
- **punt** als duizendtalscheiding, en alleen vanaf vijf cijfers (`1000` blijft `1000`, `10.000`
  krijgt een punt). Dat volgt het Groene Boekje en voorkomt dat jaartallen als `2.022` verschijnen;
- percentages met een **vaste spatie** vóór het procentteken (`24,6 %`), zoals de SI-schrijfwijze en
  de Nederlandse typografie voorschrijven.

Voor uitvoer die door een *machine* gelezen wordt (CSV, Parquet, logregels met meetwaarden) hoort
deze module NIET gebruikt te worden: daar blijft de puntnotatie zonder groepering de veilige keuze.
"""

from __future__ import annotations

import math
from typing import Any

#: Vaste spatie (U+00A0). Voorkomt dat "24,6" en "%" over een regeleinde gescheiden raken.
VASTE_SPATIE = " "

#: Onder deze grens geen duizendtalscheiding, zodat jaartallen niet als "2.022" verschijnen.
GROEPEER_VANAF = 10_000


def _groepeer(geheel: str) -> str:
    """Zet punten in een reeks cijfers, van rechts naar links, per drie."""
    if len(geheel) <= 4 and int(geheel or "0") < GROEPEER_VANAF:
        return geheel
    stukken = []
    while len(geheel) > 3:
        stukken.append(geheel[-3:])
        geheel = geheel[:-3]
    stukken.append(geheel)
    return ".".join(reversed(stukken))


def getal(waarde: Any, decimalen: int = 0, leeg: str = "-") -> str:
    """Formatteer een getal Nederlands: komma als decimaalteken, punt per duizendtal.

    >>> getal(8637833)
    '8.637.833'
    >>> getal(3.75, 2)
    '3,75'
    >>> getal(2022)
    '2022'
    >>> getal(10000)
    '10.000'
    >>> getal(-1924.16, 2)
    '-1924,16'
    >>> getal(None)
    '-'
    """
    if waarde is None:
        return leeg
    try:
        f = float(waarde)
    except (TypeError, ValueError):
        return leeg
    if math.isnan(f) or math.isinf(f):
        return leeg
    teken = "-" if f < 0 else ""
    tekst = f"{abs(f):.{decimalen}f}"
    if "." in tekst:
        geheel, fractie = tekst.split(".")
        return f"{teken}{_groepeer(geheel)},{fractie}"
    return f"{teken}{_groepeer(tekst)}"


def percentage(waarde: Any, decimalen: int = 1, leeg: str = "-") -> str:
    """Formatteer een FRACTIE (0..1) als Nederlands percentage, met vaste spatie.

    >>> percentage(0.246)
    '24,6\\xa0%'
    >>> percentage(-0.0002, 2)
    '-0,02\\xa0%'
    >>> percentage(float("nan"))
    '-'
    """
    if waarde is None:
        return leeg
    try:
        f = float(waarde)
    except (TypeError, ValueError):
        return leeg
    if math.isnan(f) or math.isinf(f):
        return leeg
    return f"{getal(f * 100.0, decimalen)}{VASTE_SPATIE}%"


def aandeel(teller: Any, noemer: Any, decimalen: int = 1, leeg: str = "-") -> str:
    """``<teller> van <noemer> (<percentage>)``, alles Nederlands opgemaakt.

    >>> aandeel(2120529, 8637503)
    '2.120.529 van 8.637.503 (24,6\\xa0%)'
    """
    try:
        n = float(noemer)
    except (TypeError, ValueError):
        return leeg
    if not n:
        return f"{getal(teller)} van {getal(noemer)}"
    return f"{getal(teller)} van {getal(noemer)} ({percentage(float(teller) / n, decimalen)})"
