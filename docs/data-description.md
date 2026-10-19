# Data-beschrijving: bron en afwijkingen t.o.v. RVO's datadictionary

Zie `ontwerp-preprocessing.md` voor het volledige ontwerp. Dit document is de korte,
naslagwerk-versie: wat de bron zegt, en waar de praktijk daarvan afwijkt.

## Bronbestanden (`data/raw/`, niet in git; zie GEBRUIKSVOORWAARDEN.md)

De dataset wordt gedownload als één `dataset_openbaar.zip` (3,20 GB; 23,91 GB uitgepakt, 6.286
leden, plat). Uitpakken hoeft niet: de pipeline streamt de bestanden hieronder rechtstreeks uit het
archief (ontwerp §12.11). De namen in de tabel zijn dus zowel bestandsnamen in `data/raw/` als
namen van leden in de zip.

| Bestand | Inhoud |
|---|---|
| `00_IM_meta_data_openbaar.csv` | 6.283 woningen × 18 kenmerken (statisch). Rij 2 is een eenheden-toelichting, geen data. |
| `00_Informatie document IM dataset - <datum>.pdf` | RVO's gebruiksvoorwaarden + datadictionary. |
| `IM_customer_<id>.csv` | Eén tabel per woning: `datetime,elec,interval,gas,wind,temp,sun`. Alle vier granulariteiten (`q`/`h`/`d`/`m`) door elkaar, onderscheiden via `interval`. |

## RVO's intervalsemantiek (klopt met q/h/d, niet met m; zie hieronder)

| interval | dekt | timestamp op regel |
|---|---|---|
| `q` (kwartier) | 12:00–12:15 | einde van het interval |
| `h` (uur) | 12:00–13:00 | einde van het interval |
| `d` (dag) | 00:00–23:59 | begin van de dag zelf |
| `m` (maand) | 1e t/m laatste dag | laatste dag van de maand, 00:00 |

`q`/`h` zijn tz-aware UTC-tijdstippen; `d`/`m` zijn kale lokale datums (Europe/Amsterdam). Zie
`ontwerp-preprocessing.md` §1 en `src/im3_preprocessing/timestamps.py`.

**De output wijkt hier bewust van af.** Deze bronsemantiek is intern inconsistent (drie
verschillende dingen voor `tijdstip`) en voor `m` ronduit onbruikbaar. De output-kolom
`tijdstip_start` (§ Datamodel hieronder) staat daarom altijd op het **begin** van het interval, voor
alle vier de typen: zie `ontwerp-intervalsemantiek.md` §1/§4 voor de volledige onderbouwing en de
terugrekenregels naar deze bronconventie.

## Vijf geverifieerde afwijkingen van wat het informatiedocument suggereert

1. **`m`-rijen zijn geen maandtotaal.** Het is het gemiddelde dagverbruik van die maand (ontwerp
   §2.1). In `measurements.parquet` gelabeld als `granulariteit__cat = "maand_gemiddeld_per_dag"`,
   nooit `"..._totaal"`.
2. **`Woningtype` is bij 29% van de woningen afgekapt** in de bron-export (`'Rijwoning (tussen'`,
   `'Rijwoning (hoek'`), hersteld naar de volledige waarde, met een
   `woningtype_bron_afgekapt__bool`-vlag (ontwerp §2.2).
3. **`d`/`m` beginnen aantoonbaar eerder dan `h`/`q`** (tot ~1 jaar) en hebben zelf nooit
   gevuld weer. De eigen KNMI-ingest (`weer.parquet`, `bron="eigen_ingest"`) dekt daarom het
   hele verbruiksbereik, niet alleen de periode die IM3's `h`-rijen toevallig dekken (ontwerp §2.3).
4. **Zomertijdovergangen**: een lokale kalenderdag is niet altijd 24 uur. `interval_duur__s` voor
   `d`-rijen wordt daarom altijd berekend uit het echte lokale-tijdvenster, nooit hardcoded
   (ontwerp §2.4, `src/im3_preprocessing/intervals.py`).
5. **707 van de 6.283 woningen (11,3%) hebben geen `gas`-kolom** in hun bronbestand: all-electric
   woningen zonder gasaansluiting, geverifieerd over de volle dataset (niet een steekproef).
   Behandeld als optionele kolom, aangevuld met NaN (nooit 0), zie ontwerp §12.1.

## Datamodel

Zie `ontwerp-preprocessing.md` §5 en `docs/variable-dictionary.md` voor de volledige
ruw→standardized-mapping.

```
homes.parquet          : één rij per woning
measurements.parquet   : home_id__str, tijdstip_start (Europe/Amsterdam, begin v/h interval),
                          interval_type__cat, interval_duur__s, granulariteit__cat, e_net__W
weer.parquet           : weerstation_nr, tijdstip (uur, Europe/Amsterdam), temp_buiten__degC,
                          wind__m_s_1, ghi__W_m_2, bron__cat
quality.parquet        : home_id__str, tijdstip_start, interval_type__cat, <veld>__flag
derived.parquet        : home_id__str, tijdstip_start, interval_type__cat, g_gebruik__m3_s_1,
                          g_gebruik__W, actual_gas_std_hhv__J_m_3, gas_hhv_bron__cat,
                          weerkoppeling_methode__cat, temp_buiten__degC, wind__m_s_1, ghi__W_m_2
```

Alleen vermogen (`__W`), geen energie (`__kWh`/`__m3`) meer in de output (ontwerp-intervalsemantiek.md
§3): een flow is intervalonafhankelijk, dus `q`/`h`/`d`/`m` zijn direct vergelijkbaar zonder eerst
door de duur te delen, en energie is verliesvrij terug te rekenen zolang `interval_duur__s` in de
tabel blijft (`E = P x interval_duur__s`, voor `m`-rijen `x 86.400`, zie `docs/variable-dictionary.md`).

Zie `docs/data-quality.md` voor het gegenereerde kwaliteitsrapport van de laatst gedraaide run
(steekproef of volledige dataset).
