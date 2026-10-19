# SPDX-License-Identifier: EUPL-1.2
"""Structurele kwaliteitscontroles die uit de dataset zelf te doen zijn (ontwerp-preprocessing.md §7).

Dit produceert **bevindingen/rapportages**, geen cleaning-beslissingen (die horen in
:mod:`im3_preprocessing.cleaning`); zie ontwerp §3 principe 5: geen harde regel zonder
semantische onderbouwing.

Alles hier is vectorized over de hele ``measurements``-tabel in één keer (geen per-woning
Python-loop), want dit moet uiteindelijk over 6.283 bestanden / tientallen miljoenen rijen draaien
(ontwerp §11), niet alleen over een steekproef.
"""

from __future__ import annotations

import datetime as _dt

import numpy as np
import pandas as pd

from .intervals import J_PER_KWH
from .timestamps import TZ_LOKAAL

# §2.4: de acht zomertijddata 2022-2025 waarop een exhaustieve scan van de volle dataset géén
# enkele gevulde d-rij vond. Vast gecodeerd (geen algoritme voor "laatste zondag" nodig voor dit
# vaste, historische bereik) zodat het precies de geverifieerde data zijn, niet een generieke
# regel die toevallig ook DST-datums raakt.
DST_TRANSITIEDATA: tuple[_dt.date, ...] = (
    _dt.date(2022, 3, 27), _dt.date(2022, 10, 30),
    _dt.date(2023, 3, 26), _dt.date(2023, 10, 29),
    _dt.date(2024, 3, 31), _dt.date(2024, 10, 27),
    _dt.date(2025, 3, 30), _dt.date(2025, 10, 26),
)


def _lokale_dagbucket(tijdstip_start: pd.Series) -> pd.Series:
    """Datum van de lokale kalenderdag waarin ``tijdstip_start`` valt.

    Sinds ontwerp-intervalsemantiek.md §1/§4 is elke rij (q/h/d/m) getimestampt op het BEGIN van
    zijn interval, dus is de lokale kalenderdag van ``tijdstip_start`` direct de juiste dag: geen
    "-1 seconde"-correctie meer nodig voor het middernacht-edge-case van de laatste q/h van een
    dag (die had vóór deze omzetting tijdstip=volgende dag 00:00, nu tijdstip_start=diezelfde dag
    23:45/23:00).
    """
    return tijdstip_start.dt.tz_convert(TZ_LOKAAL).dt.date


def q_h_vs_dag_consistency(measurements: pd.DataFrame) -> pd.DataFrame:
    """Vergelijk, per woning en per dag, de som van q-rijen (en apart: h-rijen) met de d-waarde.

    Gebruikt het lokale-dagvenster (§2.4), niet een naïef UTC-etmaal; anders geeft de
    q-vs-d-check op de twee jaarlijkse overgangsdagen een **valse** afwijking.

    Verwacht een reeds gestandaardiseerde ``measurements``-tabel met kolommen ``home_id__str,
    tijdstip_start (UTC, begin van interval), interval_type__cat, e_net__W, interval_duur__s``,
    voor één of meer woningen.

    Sinds ontwerp-intervalsemantiek.md §3 bevat de tabel alleen nog vermogen, geen energie; de
    vergelijking wordt daarom ``som(P x duur)`` tegen ``P_dag x duur_dag``, wiskundig equivalent
    aan de oude kWh-som-vergelijking maar met een andere formule (energie = vermogen x duur).

    Retourneert één rij per (home_id, datum) waarvoor een d-rij bestaat.
    """
    dagbucket = _lokale_dagbucket(measurements["tijdstip_start"])
    energie__kWh = (measurements["e_net__W"] * measurements["interval_duur__s"]) / J_PER_KWH

    d_mask = measurements["interval_type__cat"] == "d"
    d_rows = pd.DataFrame(
        {
            "home_id__str": measurements.loc[d_mask, "home_id__str"],
            "datum": measurements.loc[d_mask, "tijdstip_start"].dt.tz_convert(TZ_LOKAAL).dt.date,
            "e_dag__kWh": energie__kWh[d_mask],
        }
    )

    def _som_per_dag(interval_type: str, prefix: str) -> pd.DataFrame:
        mask = measurements["interval_type__cat"] == interval_type
        subset = pd.DataFrame(
            {
                "home_id__str": measurements.loc[mask, "home_id__str"],
                "datum": dagbucket[mask],
                "e_net__kWh": energie__kWh[mask],
            }
        )
        grouped = subset.groupby(["home_id__str", "datum"])["e_net__kWh"].agg(["sum", "size"])
        grouped.columns = [f"e_som_{prefix}__kWh", f"n_{prefix}_in_venster"]
        return grouped.reset_index()

    result = d_rows.merge(_som_per_dag("q", "kwartier"), on=["home_id__str", "datum"], how="left")
    result = result.merge(_som_per_dag("h", "uur"), on=["home_id__str", "datum"], how="left")

    for prefix in ("kwartier", "uur"):
        n_col = f"n_{prefix}_in_venster"
        result[n_col] = result[n_col].fillna(0).astype(int)
        heeft_data = result[n_col] > 0
        som_col = f"e_som_{prefix}__kWh"
        result[f"e_dagcheck_{prefix}__kWh"] = np.where(
            heeft_data, result["e_dag__kWh"] - result[som_col], np.nan
        )
        result.loc[~heeft_data, som_col] = np.nan

    return result.reset_index(drop=True)


def dst_dag_rij_aanwezig(measurements: pd.DataFrame) -> pd.DataFrame:
    """Per woning en per DST-transitiedatum: is er een gevulde ``d``-rij op precies die datum?

    §2.4: een ontbrekende d-rij op exact deze datum is een voorspelbaar, jaarlijks terugkerend
    patroon (vermoedelijk RVO's eigen 24h-consistentiecheck die faalt op de 23-/25-uursdag), geen
    toevallige uitval. Dit onderscheidt dat patroon zichtbaar van gewone gaten.
    """
    d_rows = measurements.loc[measurements["interval_type__cat"] == "d", ["home_id__str", "tijdstip_start"]]
    datums = d_rows["tijdstip_start"].dt.tz_convert(TZ_LOKAAL).dt.date
    aanwezig_set = set(zip(d_rows["home_id__str"], datums))

    alle_homes = measurements["home_id__str"].unique()
    rows = [
        {
            "home_id__str": home_id,
            "transitiedatum": transitiedatum,
            "d_rij_aanwezig": (home_id, transitiedatum) in aanwezig_set,
        }
        for home_id in alle_homes
        for transitiedatum in DST_TRANSITIEDATA
    ]
    return pd.DataFrame(rows)


def gas_negatief_rapport(measurements: pd.DataFrame) -> dict:
    """Empirische check van open vraag §10.3: komt gas ooit negatief voor?

    Rapporteert alleen; dit wordt geen cleaning-regel totdat het over de volle dataset bevestigd
    is (ontwerp §3 principe 5). Werkt op ``g_gebruik__m3_s_1`` (vermogen/flow, sinds
    ontwerp-intervalsemantiek.md §3): delen door een positieve duur verandert het teken nooit, dus
    deze check blijft geldig op de flow-kolom (zie ontwerp-intervalsemantiek.md §3, "Wat de
    flow-conversie NIET verandert").
    """
    negatief = measurements["g_gebruik__m3_s_1"] < 0
    getroffen_woningen = sorted(measurements.loc[negatief, "home_id__str"].unique())
    return {
        "n_rijen_negatief": int(negatief.sum()),
        "n_woningen_getroffen": len(getroffen_woningen),
        "woningen_getroffen": getroffen_woningen,
    }


def constante_reeks_flags(measurements: pd.DataFrame, kolom: str) -> pd.Series:
    """Vlag alle rijen van een (woning, interval_type) waarvan de HELE gerapporteerde reeks voor
    ``kolom`` nooit varieert (standaarddeviatie exact 0): een dode/vastgelopen sensor over de
    volle looptijd, niet een tijdelijke rustperiode.

    Zelfde aanpak als ``Preprocessor.filter_id_prop_with_std_zero`` in
    ``needforheat-diagnosis-software`` (zie ``examples/REDUCEDHEATCARB_sanity_check.ipynb``), hier
    als **vlag** i.p.v. de waarden te vervangen door NaN (ontwerp §3 principe 3: niets verwijderen
    zonder vlag).

    Bewust geen eerdere, lokale "N opeenvolgende identieke waarden"-heuristiek meer (die zat hier
    tot 26-aug-2026): een tijdelijke reeks identieke waarden (ook niet-nul) is op zichzelf geen
    bewijs van een kapotte sensor. Bijvoorbeeld een warmtepomp die een tijd op een vast
    minimum-modulatieniveau draait, geeft een reëel, tijdelijk constant vermogen; en "geen
    gasverbruik in de zomer" geeft een reeks exacte nullen die evengoed geen storing is (§3
    principe 4). Een reeks die van begin tot eind, over de volle looptijd, nooit ook maar één keer
    afwijkt, is een veel zeldzamer en sterker signaal.

    Nullable ``boolean``: waar ``kolom`` zelf NaN is (bv. ``g_gebruik__m3_s_1`` bij een all-electric
    woning zonder gasaansluiting, §12.1) is dit niet met True/False te beantwoorden.
    """
    groep = measurements.groupby(["home_id__str", "interval_type__cat"], observed=True)[kolom]
    std = groep.transform("std")
    n_niet_leeg = groep.transform("count")

    # std() zelf is NaN bij < 2 niet-lege waarnemingen; dan is "nooit gevarieerd" niet te
    # beoordelen, dus expliciet niet als constant behandelen.
    is_constant = (std == 0) & (n_niet_leeg >= 2)

    resultaat = is_constant.astype("boolean")
    resultaat[measurements[kolom].isna()] = pd.NA
    return resultaat


def uitschieter_flags(measurements: pd.DataFrame, kolom: str, n_sigma: float = 3.0) -> pd.Series:
    """Vlag waarden die meer dan ``n_sigma`` standaarddeviaties van het (woning, interval_type)-
    gemiddelde afliggen.

    Zelfde eenvoudige aanpak als ``Preprocessor.filter_static_outliers`` in
    ``needforheat-diagnosis-software``. Informationeel: een uitschieter is niet per definitie fout
    (ontwerp §3 principe 5): een piek boven de ISDE-capaciteit kan bijverwarming of deellast zijn,
    dus hier alleen gevlagd, nooit gefilterd.

    ``n_sigma=3.0`` is een voorlopige, in de statistiek gangbare drempel, niet extern bevestigd
    voor déze dataset specifiek (net als de weer-matchdrempels, zie docs/data-quality.md).
    """
    groep = measurements.groupby(["home_id__str", "interval_type__cat"], observed=True)[kolom]
    gemiddelde = groep.transform("mean")
    std = groep.transform("std")
    z = (measurements[kolom] - gemiddelde) / std

    resultaat = (z.abs() > n_sigma).astype("boolean")
    # Bij std==0 (zie constante_reeks_flags) is een z-score niet betekenisvol; bij NaN-invoer
    # evenmin.
    resultaat[measurements[kolom].isna() | std.isna() | (std == 0)] = pd.NA
    return resultaat


def extreme_uitschieters_rapport(
    measurements: pd.DataFrame, quality: pd.DataFrame, top_n: int = 10
) -> pd.DataFrame:
    """Top-N meest extreme ``e_net``/``g_gebruik``-uitschieters, met een vlag of e_net én
    g_gebruik voor diezelfde (woning, tijdstip) **allebei** als uitschieter zijn gevlagd.

    Achtergrond (ontwerp §12.6): op de steekproef bleken de twee grootste uitschieters
    (`IM_customer_1018`, mei 2023: `elec=-2117`, `gas=-741`; `IM_customer_1027`, okt. 2023:
    `elec=-227`) allebei op een `m`-rij te staan, precies in de maand waar iets structureel mis
    lijkt te gaan. Bij 1018 zijn zowel elektra als gas gelijktijdig extreem negatief, wat een
    gelijktijdige meterwissel (elektra + gas in één huisbezoek, zoals Nederlandse netbeheerders
    vaak doen) waarschijnlijker maakt dan toeval. Dat is een **hypothese**, geen bevestigd feit:
    IM3 levert alleen de al-verschilde reeks, niet de onderliggende cumulatieve meterstanden, dus
    dit is met de beschikbare data niet met zekerheid vast te stellen (zie ook de kanttekening bij
    `needforheat-diagnosis-software`'s aanpak in het ontwerpdocument).
    """
    kolommen = ["home_id__str", "tijdstip_start", "interval_type__cat", "veld", "waarde", "abs_waarde", "beide_uitschieter__bool"]

    gekoppeld = measurements.merge(quality, on=["home_id__str", "tijdstip_start", "interval_type__cat"])
    gekoppeld["beide_uitschieter__bool"] = gekoppeld["e_net_uitschieter__flag"].fillna(False) & gekoppeld[
        "g_gebruik_uitschieter__flag"
    ].fillna(False)

    stukken = []
    for veld, vlagkolom in (
        ("e_net__W", "e_net_uitschieter__flag"),
        ("g_gebruik__m3_s_1", "g_gebruik_uitschieter__flag"),
    ):
        subset = gekoppeld[gekoppeld[vlagkolom].fillna(False)]
        stukken.append(
            pd.DataFrame(
                {
                    "home_id__str": subset["home_id__str"],
                    "tijdstip_start": subset["tijdstip_start"],
                    "interval_type__cat": subset["interval_type__cat"],
                    "veld": veld,
                    "waarde": subset[veld].astype("float64"),
                    "beide_uitschieter__bool": subset["beide_uitschieter__bool"],
                }
            )
        )

    alle = pd.concat(stukken, ignore_index=True)
    if alle.empty:
        return pd.DataFrame(columns=kolommen)

    alle["abs_waarde"] = alle["waarde"].abs()
    return alle.sort_values("abs_waarde", ascending=False).head(top_n).reset_index(drop=True)[kolommen]


def gas_voor_koppeling_verdacht_rapport(
    measurements: pd.DataFrame, homes: pd.DataFrame, venster_dagen: int = 60
) -> pd.DataFrame:
    """Per woning: zijn de EERSTE ``venster_dagen`` dagen met een ``d``-gasrij allemaal exact 0,
    terwijl de metadata reëel gasgebruik verwacht (`Koken_op_gas` of een gasgestookt
    verwarmingssysteem, i.e. een HR-ketel)?

    Achtergrond (ontwerp §12.7): op de steekproef bleek `IM_customer_1027`
    (`Koken_op_gas=True`, `Hybride warmtepomp, HR-ketel`) de eerste 60 dagen met een d-gasrij
    stuk voor stuk exact 0 te hebben, om daarna over te gaan op een reeks met normale variatie
    (~39% nul-dagen, plausibel voor een hybride warmtepomp die zelden de ketel nodig heeft maar
    wel gekookt wordt op gas). Permanent nul gasverbruik is voor zo'n woning niet aannemelijk;
    waarschijnlijker is dat de gasmeting nog niet gekoppeld was en de prepublicatiepijplijn dat
    als `0` i.p.v. `NaN` wegschrijft. **Dit is geen aanname over d/m vóór h/q an sich**: dat d/m
    verder teruggaat dan h/q is al gedocumenteerd en verwacht gedrag (§2.3, consistent met hoe een
    ODA via de netbeheerder historische dagstanden kan opvragen, zie
    https://github.com/energietransitie/dsmr-info). Het gaat hier specifiek om een gas-eigen gat: bij
    `IM_customer_1027` was er al wél `h`-data (elektra, weer) vanaf maart 2023, terwijl gas tot
    oktober 2023 op 0 bleef. Dus geen algemeen "nog niet aangemeld"-verschijnsel, maar een
    gas-specifieke koppeling die kennelijk later volgde.

    Ter contrast blijft een woning met `Koken_op_gas=False` en een all-electric warmtepomp
    (bv. `IM_customer_1001` in de steekproef) permanent op 0 staan over de HELE reeks, niet alleen
    de eerste periode; dat is zelf-consistent en wordt hier terecht niet als verdacht gemarkeerd.

    Retourneert alleen woningen waarvan de eerste ``venster_dagen`` dagen daadwerkelijk allemaal
    exact 0 waren; ``verdacht__bool`` is True als daarbovenop ook reëel gasgebruik verwacht werd.
    """
    kolommen = [
        "home_id__str", "n_vroege_dagen", "frac_nul_latere_dagen",
        "kookt_op_gas__bool", "heeft_hr_ketel__bool", "verdacht__bool",
    ]

    d_rows = measurements.loc[
        (measurements["interval_type__cat"] == "d") & measurements["g_gebruik__m3_s_1"].notna(),
        ["home_id__str", "tijdstip_start", "g_gebruik__m3_s_1"],
    ].sort_values(["home_id__str", "tijdstip_start"])

    if d_rows.empty:
        return pd.DataFrame(columns=kolommen)

    d_rows["volgnummer"] = d_rows.groupby("home_id__str").cumcount()
    vroeg = d_rows[d_rows["volgnummer"] < venster_dagen]
    laat = d_rows[d_rows["volgnummer"] >= venster_dagen]

    groep_vroeg = vroeg.groupby("home_id__str")["g_gebruik__m3_s_1"]
    rapport = pd.DataFrame(
        {
            "n_vroege_dagen": groep_vroeg.size(),
            "altijd_nul_vroeg__bool": groep_vroeg.apply(lambda s: bool((s == 0).all())),
        }
    )
    rapport = rapport[rapport["n_vroege_dagen"] >= venster_dagen]
    if laat.empty:
        rapport["frac_nul_latere_dagen"] = pd.NA
    else:
        rapport["frac_nul_latere_dagen"] = laat.groupby("home_id__str")["g_gebruik__m3_s_1"].apply(
            lambda s: (s == 0).mean()
        )
    rapport = rapport.reset_index()

    verwacht = homes[["home_id__str", "kookt_op_gas__bool", "heeft_hr_ketel__bool"]]
    rapport = rapport.merge(verwacht, on="home_id__str", how="left")
    rapport["verdacht__bool"] = rapport["altijd_nul_vroeg__bool"] & (
        rapport["kookt_op_gas__bool"].fillna(False) | rapport["heeft_hr_ketel__bool"].fillna(False)
    )

    return rapport.loc[rapport["altijd_nul_vroeg__bool"], kolommen].sort_values(
        "verdacht__bool", ascending=False
    ).reset_index(drop=True)
