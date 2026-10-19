# SPDX-License-Identifier: EUPL-1.2
"""Inlezen en schema-valideren van de ruwe IM3-bestanden (ontwerp-preprocessing.md §1, §5).

Deze module doet uitsluitend **structurele** validatie (kolommen aanwezig, types parseerbaar,
``interval``-waarden bekend), geen semantische cleaning-checks (die horen in
:mod:`im3_preprocessing.quality` / :mod:`im3_preprocessing.cleaning`, zie ontwerp §3 principe 5).

Woningtype-herstel (§2.2) en de multi-select-tagsplitsing (§5) gebeuren hier wél, want dat is
naam/type-standaardisatie zonder analysebeslissing: geen aanname over wélke volledige waarde
bedoeld is (die is met zekerheid af te leiden), geen herindeling voor een specifieke analysevraag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import pandas as pd

from .bron import home_id_van_bestandsnaam

CUSTOMER_COLUMNS_VERPLICHT = ("datetime", "elec", "interval", "wind", "temp", "sun")
# `gas` is NIET altijd aanwezig: een all-electric woning (geen gasaansluiting) heeft in de bron
# geen `gas`-kolom, i.p.v. een kolom met louter NaN/0 (25-aug-2026 aangetroffen bij
# IM_customer_1011, een 'All-electric warmtepomp'-woning zonder Koken_op_gas). Dat is geen
# schemadefect, maar hier expliciet als optioneel behandeld, met een informationele issue, niet als
# harde fout.
CUSTOMER_COLUMNS_OPTIONEEL = ("gas",)
VALID_INTERVAL_TYPES = ("q", "h", "d", "m")


class SchemaError(ValueError):
    """Structureel schemaprobleem in een IM3-bestand. Hoort niet stil te falen."""


@dataclass
class CustomerFile:
    home_id__str: str
    df: pd.DataFrame
    issues: list[str] = field(default_factory=list)


def home_id_from_path(path: Path) -> str:
    """``IM_customer_1000.csv`` -> ``"1000"``."""
    from .bron import BronError

    try:
        return home_id_van_bestandsnaam(Path(path).name)
    except BronError as exc:
        raise SchemaError(str(exc)) from exc


def read_customer_file(path: str | Path) -> CustomerFile:
    """Lees één ``IM_customer_<id>.csv`` van schijf, met structurele schema-validatie."""
    path = Path(path)
    with open(path, "rb") as stream:
        return read_customer_stream(stream, home_id_from_path(path), herkomst=path.name)


def read_customer_stream(
    stream: IO[bytes], home_id__str: str, herkomst: str | None = None
) -> CustomerFile:
    """Lees één klantbestand uit een binaire stream, met structurele schema-validatie.

    Werkt zowel op een geopend CSV-bestand als op een ``zipfile.ZipExtFile``, en daardoor hoeft de
    dataset niet uitgepakt op schijf te staan (zie :mod:`im3_preprocessing.bron`). ``herkomst`` is
    alleen bedoeld voor leesbare foutmeldingen.

    Geeft de ruwe kolommen terug (``datetime, elec, interval, gas, wind, temp, sun``) plus
    ``home_id__str``. De standaardisatie naar ``e_net__kWh``/``g_gebruik__m3``/tijdstip-resolutie
    gebeurt bewust niet hier maar in de pipeline (:mod:`im3_preprocessing.pipeline`), die
    :mod:`im3_preprocessing.timestamps` en :mod:`im3_preprocessing.intervals` aanroept.
    """
    home_id = home_id__str
    naam = herkomst if herkomst is not None else f"IM_customer_{home_id}.csv"
    df = pd.read_csv(stream)

    ontbrekend = [c for c in CUSTOMER_COLUMNS_VERPLICHT if c not in df.columns]
    if ontbrekend:
        raise SchemaError(f"{naam}: ontbrekende kolommen {ontbrekend}")

    issues: list[str] = []

    for optionele_kolom in CUSTOMER_COLUMNS_OPTIONEEL:
        if optionele_kolom not in df.columns:
            df = df.copy()
            # float('nan'), niet pd.NA: anders wordt de kolom 'object'-dtype (gemengd met de
            # floats van bestanden die de kolom wél hebben na concat), en dat laat vergelijkingen
            # zoals `serie.ne(serie.shift())` in quality.stuck_sensor_flags struikelen op de
            # ambigue boolean-waarde van pd.NA.
            df[optionele_kolom] = float("nan")
            issues.append(
                f"kolom '{optionele_kolom}' ontbrak in het bronbestand (waarschijnlijk geen "
                f"gasaansluiting), aangevuld met NaN, niet met 0"
            )

    onbekende_intervallen = sorted(set(df["interval"].unique()) - set(VALID_INTERVAL_TYPES))
    if onbekende_intervallen:
        raise SchemaError(f"{naam}: onbekende interval-waarden {onbekende_intervallen}")

    if df["interval"].isna().any():
        raise SchemaError(f"{naam}: lege interval-waarde aangetroffen")

    if df["datetime"].isna().any():
        raise SchemaError(f"{naam}: lege datetime-waarde aangetroffen")

    # Informationele check, geen harde fout: RVO's document zegt niet expliciet dat weer alleen
    # op h-rijen staat, maar de steekproef (ontwerp §1) laat dat wel zien. Alleen registreren.
    niet_h = df["interval"] != "h"
    weer_buiten_h = int(df.loc[niet_h, ["wind", "temp", "sun"]].notna().any(axis=1).sum())
    if weer_buiten_h:
        issues.append(f"{weer_buiten_h} niet-h-rijen met een gevulde weerwaarde")

    df = df.copy()
    df.insert(0, "home_id__str", home_id)

    return CustomerFile(home_id__str=home_id, df=df, issues=issues)


def iter_customer_files(bron_of_map):
    """Yield :class:`CustomerFile` voor elke woning in een :class:`~im3_preprocessing.bron.Bron`.

    Accepteert ook een pad naar een map met losse CSV's; dat wordt dan als
    :class:`~im3_preprocessing.bron.MapBron` gelezen.
    """
    from .bron import Bron, maak_bron

    bron = bron_of_map if isinstance(bron_of_map, Bron) else maak_bron(bron_of_map)
    for home_id in bron.home_ids():
        with bron.open_klantbestand(home_id) as stream:
            yield read_customer_stream(stream, home_id)


# --- homes.parquet ---------------------------------------------------------------------------

# Grondig geverifieerd tegen de dataset (25-aug-2026): dit zijn ALLE voorkomende tokens in
# Verwarmingssysteem/Afgiftesysteem, geen open-eindige aanname, dus veilig als vaste taglijst.
VERWARMINGSSYSTEEM_TAGS: dict[str, str] = {
    "Airco voor verwarmen": "heeft_airco_verwarming__bool",
    "All-electric warmtepomp": "heeft_all_electric_wp__bool",
    "HR-ketel": "heeft_hr_ketel__bool",
    "Houtkachel/pelletkachel": "heeft_houtkachel__bool",
    "Hybride warmtepomp": "heeft_hybride_wp__bool",
    "Infrarood-panelen": "heeft_infrarood_panelen_verwarming__bool",
    "PVT-panelen": "heeft_pvt__bool",
    "Stadswarmte": "heeft_stadswarmte__bool",
    "Ventilatiewarmtepomp": "heeft_ventilatiewarmtepomp__bool",
    "Warmtepompboiler": "heeft_warmtepompboiler__bool",
    "Zonneboiler": "heeft_zonneboiler__bool",
}

AFGIFTESYSTEEM_TAGS: dict[str, str] = {
    "Convectoren": "heeft_convectoren__bool",
    "Convectorputten": "heeft_convectorputten__bool",
    "Elektrische verwarming": "heeft_elektrische_verwarming_afgifte__bool",
    "Infraroodpanelen": "heeft_infraroodpanelen_afgifte__bool",
    "Luchtverwarming": "heeft_luchtverwarming__bool",
    "Radiatoren": "heeft_radiatoren__bool",
    "Vloerverwarming": "heeft_vloerverwarming__bool",
}

# §2.2: 'Rijwoning (tussen' / 'Rijwoning (hoek' zijn met zekerheid te herstellen (afgekapt bij een
# leesteken in de bron-export), geen gok, wel een expliciete afkap-vlag.
WONINGTYPE_HERSTEL: dict[str, str] = {
    "Rijwoning (tussen": "Rijwoning (tussenwoning)",
    "Rijwoning (hoek": "Rijwoning (hoekwoning)",
}


def _split_multiselect(raw: pd.Series, tag_map: dict[str, str]) -> pd.DataFrame:
    """Zet een komma-gescheiden multi-select-kolom om in losse boolean-indicatoren.

    Onbekende tokens (niet in ``tag_map``) leveren een ``SchemaError`` op: een nieuw, ongezien
    token betekent dat de taglijst niet meer compleet is en stilzwijgend negeren zou een woning
    onterecht op "geen van de bekende systemen" laten staan.
    """
    columns = {col: pd.Series(False, index=raw.index) for col in tag_map.values()}
    for idx, value in raw.items():
        if pd.isna(value):
            continue
        for token in (t.strip() for t in value.split(",")):
            if not token:
                continue
            if token not in tag_map:
                raise SchemaError(f"Onbekend token in multi-select-veld: {token!r}")
            columns[tag_map[token]][idx] = True
    return pd.DataFrame(columns, index=raw.index)


def read_homes_metadata(path: str | Path | IO[bytes]) -> pd.DataFrame:
    """Lees ``00_IM_meta_data_openbaar.csv`` (18 kenmerken) naar een gestandaardiseerde ``homes``-tabel.

    Rij 2 van de bron-CSV is een eenheden-toelichting, geen data, en wordt hier overgeslagen.

    ``path`` mag ook een geopende binaire stream zijn, zodat het bestand rechtstreeks uit de zip
    gelezen kan worden (zie :mod:`im3_preprocessing.bron`).
    """
    raw = pd.read_csv(path, skiprows=[1])

    verwacht = {
        "Customer_id", "Installatiedatum_hp", "Heeft_thermosstaat", "Dag_temperatuur",
        "Nacht_temperatuur", "Koken_op_gas", "Weerstation_nr", "Weerstation naam",
        "Vloer_oppervlak", "EV_opgegeven", "ISDE vermogen", "Verwarmingssysteem",
        "Afgiftesysteem", "Woningtype", "Type_glas", "Isolatie_type", "Vloer_isolatie_type",
        "Dak_isolatie_type",
    }
    ontbrekend = verwacht - set(raw.columns)
    if ontbrekend:
        raise SchemaError(f"homes-metadata: ontbrekende kolommen {sorted(ontbrekend)}")

    homes = pd.DataFrame(index=raw.index)
    homes["home_id__str"] = raw["Customer_id"].astype(str)
    homes["installatiedatum_wp"] = pd.to_datetime(raw["Installatiedatum_hp"], format="%Y-%m")
    homes["heeft_thermostaat__bool"] = raw["Heeft_thermosstaat"].astype(bool)
    # int8: geverifieerd over de volle 6.283 rijen (26-aug-2026), Dag_temperatuur 15-25,
    # Nacht_temperatuur 10-23, ruim binnen int8 (-128..127), altijd geheel, nooit leeg.
    homes["temp_dag_ingesteld__degC"] = raw["Dag_temperatuur"].astype("int8")
    homes["temp_nacht_ingesteld__degC"] = raw["Nacht_temperatuur"].astype("int8")
    homes["kookt_op_gas__bool"] = raw["Koken_op_gas"].astype(bool)
    # int16: KNMI-stationscodes lopen 210-391 (28 unieke), ruim binnen int16; altijd aanwezig.
    homes["weerstation_nr"] = raw["Weerstation_nr"].astype("int16")
    homes["weerstation_naam__cat"] = raw["Weerstation naam"].astype("category")
    homes["vloeroppervlak_bin__cat"] = raw["Vloer_oppervlak"].astype("category")
    homes["heeft_ev_opgegeven__bool"] = raw["EV_opgegeven"].astype(bool)

    # ISDE vermogen: -1 is een sentinel voor 'onbekend', geen echte waarde (ontwerp §3 principe 4
    # geldt voor 0, niet voor een sentinel als -1) -> naar NaN + expliciete vlag. Nullable Int8:
    # geverifieerd over de volle dataset dat ISDE vermogen altijd een geheel getal is (0 van 6.277
    # niet-lege waarden had een decimaal) en binnen -1..19 valt, dus geheel getal + NaN nodig,
    # geen float64.
    isde_onbekend = raw["ISDE vermogen"] == -1
    homes["isde_vermogen__kW"] = raw["ISDE vermogen"].mask(isde_onbekend).astype("Int8")
    homes["isde_vermogen_onbekend__bool"] = isde_onbekend

    homes["verwarmingssysteem_ruw__cat"] = raw["Verwarmingssysteem"].astype("category")
    homes = pd.concat(
        [homes, _split_multiselect(raw["Verwarmingssysteem"], VERWARMINGSSYSTEEM_TAGS)], axis=1
    )
    homes["afgiftesysteem_ruw__cat"] = raw["Afgiftesysteem"].astype("category")
    homes = pd.concat(
        [homes, _split_multiselect(raw["Afgiftesysteem"], AFGIFTESYSTEEM_TAGS)], axis=1
    )

    homes["woningtype_bron_afgekapt__bool"] = raw["Woningtype"].isin(WONINGTYPE_HERSTEL)
    homes["woningtype__cat"] = raw["Woningtype"].replace(WONINGTYPE_HERSTEL).astype("category")

    homes["type_glas__cat"] = raw["Type_glas"].astype("category")
    homes["muurisolatie_type__cat"] = raw["Isolatie_type"].astype("category")
    homes["vloerisolatie__cat"] = raw["Vloer_isolatie_type"].astype("category")
    homes["dakisolatie_type__cat"] = raw["Dak_isolatie_type"].astype("category")

    return homes
