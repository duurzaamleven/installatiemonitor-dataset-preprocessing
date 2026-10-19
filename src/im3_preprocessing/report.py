# SPDX-License-Identifier: EUPL-1.2
"""Genereert ``docs/data-quality.md`` uit de output van een pipeline-run (ontwerp §9: "gegenereerd,
niet handmatig bijgehouden").

Werkt op de :class:`im3_preprocessing.pipeline.RapportAccumulator` in plaats van op de volledige
tabellen: die passen bij een volledige run niet in geheugen (ontwerp §12.9), en alles wat dit
rapport nodig heeft is een aggregaat.

**Het rapport is herbouwbaar zonder de pijplijn opnieuw te draaien.** ``pipeline.run`` bewaart de
accumulator (en de paar kleine, verder nergens bewaarde stukjes rapportinvoer) altijd naar
``<out-dir>/rapport_accumulator.json`` (:func:`schrijf_accumulator`). Een latere wijziging aan
alleen de rapporttekst kost daardoor geen nieuwe run (tot wel enkele uren op de volledige dataset):

.. code-block:: bash

    python -m im3_preprocessing.report --out-dir data/processed --docs-dir docs

Zie :func:`herbouw` voor wat daarbij precies teruggelezen wordt.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from . import gaskwaliteit, opmaak
from .cleaning import UITSCHIETER_N_SIGMA
from .timestamps import TZ_LOKAAL
from .weer import GHI_MATCH_DREMPEL_W_m2, TEMP_MATCH_DREMPEL_degC, WIND_MATCH_DREMPEL_m_s_1

log = logging.getLogger(__name__)


def _fmt(x, digits=3):
    # Nederlandse opmaak (komma als decimaalteken): zie im3_preprocessing.opmaak. `getal` behandelt
    # None/NaN/inf al als "leeg"; hier met dezelfde "n.v.t."-tekst als voorheen, i.p.v. opmaak's
    # eigen standaard "-", om het rapport niet onnodig te laten veranderen.
    return opmaak.getal(x, digits, leeg="n.v.t.")


def build_report(
    *,
    acc,
    homes: pd.DataFrame,
    weer_consistentie: pd.DataFrame,
    weer_consistentie_geointerpoleerd: pd.DataFrame | None = None,
    im3_weer: pd.DataFrame | None = None,
    weer: pd.DataFrame | None = None,
    is_steekproef: bool = True,
    weer_venster_dagen: int | None = None,
) -> str:
    n_woningen = homes["home_id__str"].nunique()
    n_rijen = acc.n_rijen
    # In lokale tijd tonen, net als de weggeschreven tabellen (§12.10); de accumulator verzamelt
    # nog in UTC, omdat de omzetting pas vlak vóór het wegschrijven gebeurt.
    periode = (
        f"{acc.tijdstip_min.tz_convert(TZ_LOKAAL)} .. {acc.tijdstip_max.tz_convert(TZ_LOKAAL)}"
        if n_rijen
        else "n.v.t."
    )

    lines: list[str] = []
    lines.append("# Datakwaliteitsrapport")
    lines.append("")
    lines.append(
        "**Gegenereerd door** `im3_preprocessing.report`, niet handmatig bijgehouden (ontwerp §9)."
    )
    if is_steekproef:
        lines.append(
            f"\n> **Dit is een steekproef-run** ({n_woningen} woning(en)), geen run over de volle "
            "6.283 bestanden. De patronen hieronder zijn representatief voor de aanpak, maar de "
            "percentages/aantallen moeten herberekend worden op de volledige dataset vóór ze als "
            "eindconclusie gelden (ontwerp §11)."
        )
    lines.append("")

    lines.append("## Overzicht")
    lines.append("")
    lines.append(f"- Aantal woningen: {opmaak.getal(n_woningen)}")
    lines.append(f"- Aantal measurement-rijen: {opmaak.getal(n_rijen)}")
    lines.append(f"- Periode: {periode}")
    lines.append(
        "- Granulariteit-verdeling: "
        + ", ".join(f"{itv}={opmaak.getal(n)}" for itv, n in sorted(acc.interval_tellingen.items()))
    )
    lines.append("")

    lines.append("## §2.2 Woningtype-afkapping in de bron")
    lines.append("")
    n_afgekapt = int(homes["woningtype_bron_afgekapt__bool"].sum())
    lines.append(
        f"- {opmaak.getal(n_afgekapt)} van {opmaak.getal(n_woningen)} woningen "
        f"({opmaak.percentage(n_afgekapt / n_woningen)}) hadden een afgekapte `Woningtype`-waarde "
        "in de bron, hersteld naar de volledige categorie (`woningtype_bron_afgekapt__bool`-vlag)."
    )
    lines.append("")

    lines.append("## §12.1 Woningen zonder `gas`-kolom in de bron (all-electric)")
    lines.append("")
    lines.append(
        f"- {opmaak.getal(acc.n_zonder_gaskolom)} van {opmaak.getal(n_woningen)} woningen in deze "
        "run hadden geen `gas`-kolom in het bronbestand (geen gasaansluiting), aangevuld met NaN "
        "en nooit 0. Over de volle dataset was dit 707/6.283 (11,3%), geverifieerd 26-aug-2026 "
        "(ontwerp §12.1). `g_gebruik_ontbrekend__flag` is voor deze woningen structureel 100%, en "
        "dat is verwacht gedrag, geen datakwaliteitsprobleem."
    )
    lines.append("")

    lines.append("## Cleaning-vlaggen (`quality.parquet`)")
    lines.append("")
    for kolom, n in acc.vlag_tellingen.items():
        lines.append(
            f"- `{kolom}`: {opmaak.getal(n)} rijen ({opmaak.percentage(n / n_rijen)})"
            if n_rijen
            else f"- `{kolom}`: {opmaak.getal(n)}"
        )
    lines.append("")
    lines.append(
        "`*_constante_reeks__flag`: de HELE reeks van die woning+interval_type varieert nooit "
        "(std==0). Een tijdelijke reeks identieke waarden (ook exacte nullen, ook niet-nul) telt "
        "hier niet mee, want dat is op zichzelf geen bewijs van een kapotte sensor (ontwerp §3 "
        "principe 4; zelfde aanpak als `Preprocessor.filter_id_prop_with_std_zero` in "
        f"needforheat-diagnosis-software). `*_uitschieter__flag`: > {opmaak.getal(UITSCHIETER_N_SIGMA, 1)}σ van het "
        "(woning, interval_type)-gemiddelde (`Preprocessor.filter_static_outliers`), een "
        "voorlopige, niet extern gevalideerde drempel."
    )
    lines.append("")

    lines.extend(_meterwissel_sectie(acc))
    lines.extend(_gas_voor_koppeling_sectie(acc))

    lines.append("## §7.1 q/h-som versus dagwaarde")
    lines.append("")
    iets_vergeleken = False
    for prefix, label in (("kwartier", "kwartierrijen (q)"), ("uur", "uurrijen (h)")):
        aantal, mediaan, p95 = acc.dagcheck_statistiek(prefix)
        if aantal:
            iets_vergeleken = True
            lines.append(
                f"- Som van {label} vs. dagwaarde: {opmaak.getal(aantal)} dagen vergeleken, mediane "
                f"absolute afwijking {_fmt(mediaan)} kWh, 95e percentiel {_fmt(p95)} kWh."
            )
    if iets_vergeleken:
        lines.append(
            "\n  (Vergelijking gebruikt het lokale-dagvenster, niet een naïef UTC-etmaal; "
            "ontwerp §2.4.)"
        )
    else:
        lines.append("- Geen d-rijen in deze run om te vergelijken.")
    lines.append("")

    lines.append("## §2.4 Zomertijdovergangen: ontbrekende d-rijen op de transitiedatum")
    lines.append("")
    if acc.dst_totaal:
        afwezig = acc.dst_totaal - acc.dst_aanwezig
        lines.append(
            f"- Van de {opmaak.getal(acc.dst_totaal)} (woning × transitiedatum)-combinaties: "
            f"{opmaak.getal(afwezig)} zonder d-rij op exact die datum "
            f"({opmaak.percentage(afwezig / acc.dst_totaal)})."
        )
        lines.append(
            "  Ontwerp §2.4 verwacht hier **0%** aanwezig (dus 100% afwezig) over de volle dataset "
            "Dat is een patroon, geen toevallige uitval."
        )
    lines.append("")

    lines.append("## §10.3 Komt gas ooit negatief voor? (open vraag, alleen gerapporteerd)")
    lines.append("")
    lines.append(
        f"- {opmaak.getal(acc.gas_negatief_rijen)} rijen met negatieve `g_gebruik__m3_s_1`, "
        f"verspreid over {opmaak.getal(acc.n_gas_negatief_woningen)} woning(en) in deze run."
    )
    lines.append(
        "  Dit wordt pas een cleaning-regel na bevestiging over de volle dataset (§3 principe 5) "
        "Hier alleen geregistreerd."
    )
    lines.append("")

    lines.extend(
        _weer_sectie(
            weer_consistentie, weer_consistentie_geointerpoleerd, im3_weer, weer_venster_dagen
        )
    )
    lines.extend(_gaskwaliteit_sectie(acc))

    lines.append("## Bekende, nog niet extern bevestigde aannames")
    lines.append("")
    lines.append(
        "- Matchdrempels voor de weer-consistentiecheck (hierboven) zijn een voorlopige keuze, "
        "geen extern bevestigde norm (§10.4)."
    )
    lines.append(
        f"- `UITSCHIETER_N_SIGMA = {UITSCHIETER_N_SIGMA}` (z-score-drempel voor "
        "`*_uitschieter__flag`) is een voorlopige, statistisch gangbare keuze, niet extern "
        "gevalideerd voor déze dataset."
    )
    lines.append(
        "- De calorische-gaswaarde-API (`mijnenergiedata.nl`) is niet publiek gedocumenteerd, "
        "ontdekt via inspectie van de website zelf, kan zonder aankondiging wijzigen."
    )
    lines.append("")

    return "\n".join(lines)


def _meterwissel_sectie(acc) -> list[str]:
    lines = ["## §12.6 Hypothese: meterwissel + ontbrekend filter in de prepublicatiefase", ""]
    lines.append(
        "**Hypothese** (26-aug-2026, nog niet bevestigd door RVO/KITE): extreem negatieve "
        "waarden (vooral op `m`-rijen) worden veroorzaakt door een meterwissel (elektra en/of "
        "gas) waarbij RVO's eigen prepublicatieproces de knik tussen de oude en de nieuwe "
        "cumulatieve meterstand niet filtert vóór het verschillen/aggregeren."
    )
    uitschieters = acc.samengevoegde_uitschieters()
    if len(uitschieters):
        lines.append(
            f"\nDe meest extreme uitschieters in deze run (top {len(uitschieters)}, "
            "`beide_uitschieter__bool`=True betekent dat zowel `e_net__W` als `g_gebruik__m3_s_1` "
            "voor diezelfde woning+tijdstip als uitschieter zijn gevlagd: een sterkere aanwijzing "
            "voor een gelijktijdige meterwissel dan een uitschieter in slechts één signaal):"
        )
        lines.append("\n| woning | tijdstip_start | interval | veld | waarde | beide (e+g) uitschieter |")
        lines.append("|---|---|---|---|---|---|")
        for _, r in uitschieters.iterrows():
            lines.append(
                f"| {r['home_id__str']} | {r['tijdstip_start']} | {r['interval_type__cat']} | "
                f"`{r['veld']}` | {_fmt(r['waarde'], 2)} | {r['beide_uitschieter__bool']} |"
            )
    else:
        lines.append("\n- Geen uitschieters gevonden in deze run om te illustreren.")
    lines.append(
        "\n**Hoe `needforheat-diagnosis-software` dit deel** "
        "(`Preprocessor.property_filter`, `process_meter_reading=True`): werkt op de "
        "**cumulatieve** meterstand (niet op een al-verschilde reeks zoals IM3 publiceert), "
        "neemt het verschil tussen opeenvolgende standen, en zet elk **negatief** verschil "
        "expliciet op 0 (een cumulatieve meterstand kan nooit dalen; een negatief verschil is dus "
        "per definitie een meterwissel/-reset, geen gebruik) vóór de reeks weer op te cumuleren en "
        "opnieuw te verschillen. Dat gebeurt **vóór** de z-score-uitschieterdetectie; de laatste "
        "is bij hen een extra vangnet, niet de eerste verdedigingslijn."
    )
    lines.append(
        "\n**Waarom deze preprocessing dat zelf niet kan repareren:** IM3 publiceert alleen de "
        "al-verschilde reeks, niet de onderliggende cumulatieve meterstanden. De correctie die "
        "needforheat-diagnosis-software toepast is dus alleen mogelijk **vóór** publicatie, in "
        "RVO/KITE's eigen pijplijn. Deze preprocessing kan de symptomen alleen signaleren "
        "(`*_uitschieter__flag`), niet de oorzaak wegnemen; vandaar de aanbeveling hieronder."
    )
    lines.append(
        "\n**Aanbeveling voor de makers van de prepublicatiefase (RVO/KITE/BDH):** vóór het "
        "verschillen/aggregeren naar kwartier-/uur-/dag-/maandwaarden, controleer of de "
        "onderliggende cumulatieve meterstand ooit **daalt** tussen twee opeenvolgende "
        "aflezingen, en dat kan alleen bij een meterwissel/-reset, nooit bij normaal gebruik. Zet "
        "dat specifieke interval op 0 (of vlag het) in plaats van het als een geldig, extreem "
        "negatief verbruik te publiceren. Zie `needforheat-diagnosis-software`'s "
        "`Preprocessor.property_filter` voor een werkende implementatie van dit principe. Dit "
        "hoort meegenomen te worden in een volgend inhoudelijk overleg met RVO/KITE (§4/§10.1), niet als losse technische "
        "bug-report."
    )
    lines.append("")
    return lines


def _gas_voor_koppeling_sectie(acc) -> list[str]:
    lines = [
        "## §12.7 Gas op exact 0 vóór koppeling: waarschijnlijk 'nog niet gemeten', geen genuine nul",
        "",
    ]
    lines.append(
        "**Let op: dit is een ANDER punt dan §2.3/§12.6.** Dat `d`/`m`-rijen verder teruggaan dan "
        "`h`/`q` is zelf verwacht, gedocumenteerd gedrag (§2.3): een ODA kan via de netbeheerder "
        "historische dagstanden opvragen (zie "
        "[dsmr-info](https://github.com/energietransitie/dsmr-info) voor de achtergrond van het "
        "DSMR/P1-ecosysteem), dus dat verbruik vóór het live-monitoring-moment alsnog uit "
        "dag-/maandstanden gevuld wordt, is op zichzelf niet verkeerd. Dit punt gaat specifiek over "
        "de **waarde 0** die daarbij voor gas verschijnt waar dat niet aannemelijk is."
    )
    koppeling = acc.samengevoegde_gaskoppeling()
    if len(koppeling):
        n_verdacht = int(koppeling["verdacht__bool"].sum())
        lines.append(
            f"\n{len(koppeling)} woning(en) in deze run hadden de eerste 60 dagen met een "
            f"`d`-gasrij stuk voor stuk exact 0, waarvan {n_verdacht} met metadata die reëel "
            "gasgebruik verwacht (`Koken_op_gas` of een HR-ketel). Voor die woning(en) is "
            "permanent nul gas voor twee maanden niet aannemelijk, en is `NaN` (nog niet gekoppeld) "
            "logischer dan een genuine 0."
        )
        toon = koppeling.sort_values("verdacht__bool", ascending=False).head(15)
        lines.append(
            "\n| woning | eerste 60 dagen altijd 0 | kookt op gas | heeft HR-ketel | fractie 0 in latere periode | verdacht |"
        )
        lines.append("|---|---|---|---|---|---|")
        for _, r in toon.iterrows():
            lines.append(
                f"| {r['home_id__str']} | True | {r['kookt_op_gas__bool']} | {r['heeft_hr_ketel__bool']} | "
                f"{_fmt(r['frac_nul_latere_dagen'], 2)} | {r['verdacht__bool']} |"
            )
        if len(koppeling) > len(toon):
            lines.append(f"\n(Ingekort tot de eerste {len(toon)} van {len(koppeling)} rijen.)")
        lines.append(
            "\nEen woning die ook in de latere periode permanent op 0 blijft staan (en waarvoor "
            "geen gasgebruik verwacht wordt) is hier terecht **niet** als verdacht gemarkeerd; dat "
            "is zelf-consistent (bv. een all-electric woning met een letterlijke, niet-ontbrekende "
            "gaskolom vol nullen, in tegenstelling tot de woningen uit §12.1 die de kolom "
            "helemaal missen)."
        )
    else:
        lines.append("\n- Geen woningen in deze run met een leidende reeks exacte nullen om te tonen.")
    lines.append(
        "\n**Nog niet bevestigd, alleen gerapporteerd** (ontwerp §3 principe 5): dit is een "
        "hypothese op basis van steekproefbewijs, geen aangenomen regel, en zeker geen aanleiding "
        "om deze 0-waarden zelf naar NaN om te zetten zonder externe bevestiging. Hoort net als "
        "§12.6 meegenomen te worden in een volgend inhoudelijk overleg met RVO/KITE."
    )
    lines.append("")
    return lines


def _weer_sectie(
    weer_consistentie: pd.DataFrame,
    weer_consistentie_geointerpoleerd: pd.DataFrame | None,
    im3_weer: pd.DataFrame | None,
    weer_venster_dagen: int | None,
) -> list[str]:
    lines = ["## §7.2/§7.3 Consistentie IM3-weer vs. eigen KNMI-ingest", ""]
    lines.append(
        f"Voorlopige, vooraf vastgelegde matchdrempels (open vraag §10.4, nog niet extern "
        f"bevestigd): temperatuur < {opmaak.getal(TEMP_MATCH_DREMPEL_degC, 1)} °C, wind < "
        f"{opmaak.getal(WIND_MATCH_DREMPEL_m_s_1, 1)} m/s, ghi < {opmaak.getal(GHI_MATCH_DREMPEL_W_m2)} "
        "W/m² (mediane absolute afwijking)."
    )
    lines.append(
        "\n> RVO's `sun` is gesommeerde instraling in kWh/m² per interval; vóór de vergelijking is "
        "die omgerekend naar gemiddelde W/m² (x 1000 / duur in uren), dezelfde eenheid als KNMI's "
        "`Q` in de eigen ingest. Een mediaan over alle uren telt ook de nachturen mee (beide 0), "
        "dus bij instraling zegt een lage mediaan weinig over de uitschieters overdag."
    )
    lines.append(
        "\n> De IM3-geleverde reeks zelf staat **niet** in `weer.parquet` (§12.8): die wordt per "
        "woning gedupliceerd aangeleverd en is altijd terug te halen uit de bron. Hij wordt tijdens "
        "de run wel ingelezen om deze consistentiecheck te kunnen doen."
    )
    if weer_venster_dagen is not None:
        lines.append(
            f"\n> Eigen ingest in deze run beperkt tot de laatste {weer_venster_dagen} dagen van de "
            "IM3-h-periode (steekproef-snelheid), geen volledige-historie-vergelijking."
        )
    lines.append("")

    if len(weer_consistentie):
        lines.append(
            "| station | n overlap | temp mediane afw. (°C) | binnen drempel | wind mediane afw. (m/s) | binnen drempel | ghi mediane afw. (W/m²) | binnen drempel |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for _, r in weer_consistentie.iterrows():
            lines.append(
                f"| {r['weerstation_nr']} | {r['n_overlap']} | "
                f"{_fmt(r['temp_buiten__degC_mediane_abs_afwijking'])} | {r['temp_buiten__degC_binnen_drempel']} | "
                f"{_fmt(r['wind__m_s_1_mediane_abs_afwijking'])} | {r['wind__m_s_1_binnen_drempel']} | "
                f"{_fmt(r['ghi__W_m_2_mediane_abs_afwijking'], 1)} | {r['ghi__W_m_2_binnen_drempel']} |"
            )
        buiten_drempel = weer_consistentie.loc[
            ~weer_consistentie["temp_buiten__degC_binnen_drempel"].fillna(True)
            | ~weer_consistentie["wind__m_s_1_binnen_drempel"].fillna(True),
            "weerstation_nr",
        ].tolist()
        if buiten_drempel:
            lines.extend(
                _geointerpoleerd_vergelijking(
                    buiten_drempel, weer_consistentie, weer_consistentie_geointerpoleerd
                )
            )
    else:
        lines.append("- Geen eigen-ingest-vergelijking in deze run (weer overgeslagen of geen overlap).")

    if im3_weer is not None and not im3_weer.empty:
        alle_stations = set(im3_weer["weerstation_nr"].unique())
        vergeleken = set(weer_consistentie["weerstation_nr"].unique()) if len(weer_consistentie) else set()
        zonder_overlap = sorted(int(s) for s in (alle_stations - vergeleken))
        if zonder_overlap:
            lines.append(
                f"\n- Station(s) {zonder_overlap} hadden geen enkele overlappende tijdstip tussen "
                "IM3-weer en de eigen ingest **binnen dit venster** (niet: geen data beschikbaar) "
                "Vaak omdat de betreffende woning(en) eerder stopten met rapporteren dan het "
                "gekozen validatievenster. Geen bevinding over de kwaliteit van die stations, "
                "alleen over de venster-keuze in deze run."
            )
    lines.append("")
    return lines


def _geointerpoleerd_vergelijking(
    buiten_drempel: list,
    weer_consistentie: pd.DataFrame,
    weer_consistentie_geointerpoleerd: pd.DataFrame | None,
) -> list[str]:
    """Optionele diagnose-tabel: alleen gevuld met ``--weer-geointerpoleerd-diagnose`` (§12.13).

    ``weer_consistentie`` gebruikt de rauwe, niet-geïnterpoleerde stationswaarde
    (dat ís de standaard-bron); deze functie voegt er, indien opgehaald, de RBF-geïnterpoleerde
    variant naast toe om te zien of interpolatie de afwijking t.o.v. IM3 zou veranderen.
    """
    lines = [
        f"\n**Station(s) {buiten_drempel} vallen buiten de drempel.** Dit is een bevinding, geen "
        "cleaning-beslissing (§7.3 stap 3): eerst uitzoeken wat het verschil verklaart (ander "
        "station, ander KNMI-product, interpolatiemethode, tijdzone-offset) vóór te kiezen welke "
        "bron 'juist' is."
    ]
    if weer_consistentie_geointerpoleerd is None or not len(weer_consistentie_geointerpoleerd):
        return lines

    lines.append(
        "\n  Draaide met `--weer-geointerpoleerd-diagnose`: hieronder dezelfde vergelijking met de "
        'RBF-geospatiaal geïnterpoleerde stationswaarde (`bron="eigen_ingest_geointerpoleerd"`), '
        "puur voor deze stations."
    )
    lines.append(
        "\n  | station | temp mediane afw. rauw (°C) | temp mediane afw. geïnterpoleerd (°C) | conclusie |"
    )
    lines.append("  |---|---|---|---|")
    for stn in buiten_drempel:
        kol = "temp_buiten__degC_mediane_abs_afwijking"
        rauw = weer_consistentie.loc[weer_consistentie["weerstation_nr"] == stn, kol]
        geointerp = weer_consistentie_geointerpoleerd.loc[
            weer_consistentie_geointerpoleerd["weerstation_nr"] == stn, kol
        ]
        rauw_v = rauw.iloc[0] if len(rauw) else None
        geointerp_v = geointerp.iloc[0] if len(geointerp) else None
        if geointerp_v is None:
            conclusie = "geen overlap voor de geïnterpoleerde diagnose in dit venster"
        elif (rauw_v or 0) >= TEMP_MATCH_DREMPEL_degC > geointerp_v:
            conclusie = "geïnterpoleerd valt wél binnen de drempel, rauw niet: nader onderzoeken"
        else:
            conclusie = "interpolatie verandert de afwijking niet wezenlijk (bevestigt §12.4)"
        lines.append(f"  | {stn} | {_fmt(rauw_v)} | {_fmt(geointerp_v)} | {conclusie} |")
    return lines


def _gaskwaliteit_sectie(acc) -> list[str]:
    lines = ["## Calorische gaswaarde (`derived.actual_gas_std_hhv__J_m_3`)", ""]
    lines.append(
        "`g_gebruik__W` gebruikt zoveel mogelijk de **werkelijke**, per-uur "
        "gepubliceerde calorische waarde (NL-gemiddelde over netgebieden, via "
        "`mijnenergiedata.nl/calorische-gaswaarden`, zie `gaskwaliteit.py`) i.p.v. een vaste "
        "Groningen-gas-constante. IM3 levert geen netbeheerder/netgebied per woning, dus dit is "
        "een NL-breed gemiddelde, geen exacte per-woning-waarde."
    )
    if acc.gas_hhv_bron_tellingen:
        verdeling = ", ".join(f"`{bron}`={opmaak.getal(n)}" for bron, n in acc.gas_hhv_bron_tellingen.items())
        lines.append(
            f"\n- Bron van de gebruikte calorische waarde in deze run: {verdeling}. "
            "`vast_gemiddelde_fallback` gebruikt de publieke Gaswet-referentiewaarde "
            f"({opmaak.getal(gaskwaliteit.GAS_CALORISCHE_WAARDE_FALLBACK__J_M3 / 1e6, 2)} MJ/m³) en hoort in een "
            "volledige run een uitzondering te zijn, niet de meerderheid."
        )
    lines.append("")
    return lines


def write_report(path: str | Path, **kwargs) -> None:
    Path(path).write_text(build_report(**kwargs), encoding="utf-8")


# --- Taak: het rapport herbouwbaar maken zonder de pijplijn (tot ~7 uur op de volledige dataset) --
# --- opnieuw te draaien -------------------------------------------------------------------------


def schrijf_accumulator(
    pad: str | Path,
    *,
    acc,
    is_steekproef: bool,
    weer_venster_dagen: int | None,
    weer_consistentie: pd.DataFrame,
    weer_consistentie_geointerpoleerd: pd.DataFrame | None,
    im3_weer: pd.DataFrame | None,
) -> None:
    """Bewaar alles wat nodig is om :func:`build_report` later, ZONDER de pijplijn opnieuw te
    draaien, exact te kunnen herhalen -- naar ``<out-dir>/rapport_accumulator.json``.

    **Waarom JSON, niet pickle.** Pickle is Python/versie-specifiek: een gepickelde
    ``RapportAccumulator`` kan na een refactor van die klasse (een hernoemd veld, een ander type)
    niet meer betrouwbaar terug-unpickled worden, en is onleesbaar zonder Python erbij. JSON is
    leesbaar (``git diff`` op dit bestand toont letterlijk welke cijfers veranderden tussen twee
    runs), taal-onafhankelijk, en hier versiebestendig omdat
    ``RapportAccumulator.naar_json_dict``/``uit_json_dict`` een expliciet, met de hand onderhouden
    schema zijn -- geen automatische ``__dict__``-dump die stilzwijgend meeverandert bij een
    interne herstructurering van de klasse.

    **Wat hier WEL en NIET bewaard wordt** (de overige argumenten van ``build_report``):

    - ``homes``/``weer``: NIET hier. Die staan al compleet in ``homes.parquet``/``weer.parquet``
      (elke run schrijft ze toch al); nog een kopie hier zou pure duplicatie zijn. :func:`herbouw`
      leest ze van daar terug.
    - ``acc``: WEL, via :meth:`RapportAccumulator.naar_json_dict`.
    - ``is_steekproef``/``weer_venster_dagen``: WEL. Kale run-parameters die verder nergens
      vastliggen (geen tabel bewaart "was dit een steekproef").
    - ``weer_consistentie``/``weer_consistentie_geointerpoleerd``: WEL, als kleine tabellen (één
      rij per weerstation, in de praktijk hooguit enkele tientallen). Ze zijn niet uit de bewaarde
      Parquet-tabellen te herleiden: de vergelijking gebruikt het door IM3 meegeleverde weer, dat
      met opzet NIET in ``weer.parquet`` staat (ontwerp §12.8) en dus verder nergens bewaard blijft.
    - ``im3_weer``: NIET de volledige tabel (station × uur × velden, potentieel net zo groot als
      ``weer.parquet``: gemeten op de 20-woningen-steekproef 274.793 rijen). ``build_report``
      gebruikt er toch alleen de VERZAMELING ``weerstation_nr``-waarden van (welke stations kwamen
      voor in het IM3-weer, voor de "geen overlap"-bevinding in §7.2/§7.3) -- dus alleen die lijst
      wordt bewaard, niet de station-uur-metingen zelf. Vandaar ook
      ``acc.naar_json_dict(inclusief_im3_weer_ruw=False)`` hieronder: zonder die vlag zou ``acc``
      zijn eigen (identieke) kopie van diezelfde 274.793 rijen meeslepen, puur ballast (zie de
      docstring van die methode voor de meting die dit aan het licht bracht).
    """
    pad = Path(pad)
    data = {
        "acc": acc.naar_json_dict(inclusief_im3_weer_ruw=False),
        "is_steekproef": is_steekproef,
        "weer_venster_dagen": weer_venster_dagen,
        "weer_consistentie": (
            json.loads(weer_consistentie.to_json(orient="records"))
            if weer_consistentie is not None and not weer_consistentie.empty
            else []
        ),
        "weer_consistentie_geointerpoleerd": (
            json.loads(weer_consistentie_geointerpoleerd.to_json(orient="records"))
            if weer_consistentie_geointerpoleerd is not None and not weer_consistentie_geointerpoleerd.empty
            else []
        ),
        "im3_weer_stations": (
            sorted(int(s) for s in im3_weer["weerstation_nr"].unique())
            if im3_weer is not None and not im3_weer.empty
            else []
        ),
    }
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def lees_accumulator(pad: str | Path) -> dict:
    """De inverse van :func:`schrijf_accumulator`: een dict die, aangevuld met ``homes=``/
    ``weer=``, direct als ``**kwargs`` in :func:`build_report` past."""
    # Lokale import: pipeline.py importeert dit report-module al op moduleniveau (voor
    # `report.write_report`/`report.schrijf_accumulator`), dus een import hier bovenaan zou een
    # circulaire import geven. Op het moment dat déze functie draait, bestaat pipeline allang.
    from .pipeline import RapportAccumulator

    data = json.loads(Path(pad).read_text(encoding="utf-8"))
    return {
        "acc": RapportAccumulator.uit_json_dict(data["acc"]),
        "is_steekproef": data["is_steekproef"],
        "weer_venster_dagen": data["weer_venster_dagen"],
        "weer_consistentie": pd.DataFrame(data["weer_consistentie"]),
        "weer_consistentie_geointerpoleerd": pd.DataFrame(data["weer_consistentie_geointerpoleerd"]),
        "im3_weer": pd.DataFrame({"weerstation_nr": data["im3_weer_stations"]}),
    }


def herbouw(out_dir: str | Path, docs_dir: str | Path) -> Path:
    """Herbouw ``docs/data-quality.md`` uit een eerder weggeschreven ``rapport_accumulator.json``,
    ZONDER de pijplijn (tot wel enkele uren op de volledige dataset, zie README §Capaciteitseisen)
    opnieuw te draaien.

    Vereist een eerdere, complete run in ``out_dir``: ``homes.parquet`` en
    ``rapport_accumulator.json`` (``weer.parquet`` alleen als die run weer heeft opgehaald).
    """
    out_dir = Path(out_dir)
    docs_dir = Path(docs_dir)

    homes = pd.read_parquet(out_dir / "homes.parquet")
    weer_pad = out_dir / "weer.parquet"
    weer = pd.read_parquet(weer_pad) if weer_pad.is_file() else None

    kwargs = lees_accumulator(out_dir / "rapport_accumulator.json")

    docs_dir.mkdir(parents=True, exist_ok=True)
    pad = docs_dir / "data-quality.md"
    write_report(pad, homes=homes, weer=weer, **kwargs)
    return pad


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-dir", type=Path, default=Path("data/processed"), help="Map met een eerdere pipeline-run"
    )
    p.add_argument("--docs-dir", type=Path, default=Path("docs"), help="Waar data-quality.md heen moet")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    """``python -m im3_preprocessing.report --out-dir data/processed --docs-dir docs``: herbouw
    ``docs/data-quality.md`` uit een eerder bewaarde ``rapport_accumulator.json``, zonder de
    pijplijn opnieuw te draaien. Zie :func:`herbouw`."""
    args = _parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    pad = herbouw(args.out_dir, args.docs_dir)
    log.info("data-quality.md herbouwd zonder de pijplijn te draaien: %s", pad)


if __name__ == "__main__":
    main()
