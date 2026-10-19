#!/usr/bin/env bash
# SPDX-License-Identifier: EUPL-1.2
# De volledige IM3-verwerking, onbeheerd en hervatbaar.
#
# Sinds 06-09-2026 slaat de pijplijn per chunk deelbestanden op en slaat hij bij een herstart over
# wat al klaar is. Daarom mag deze wrapper een mislukte stap gewoon opnieuw proberen: hij begint dan
# niet vooraan, maar bij het eerste stuk dat nog niet af was. Bij een run van ~7 uur is dat het
# verschil tussen een tegenvaller en een verloren dag.
#
# Gebruik:  bash draai_volledig.sh
# Log:      data/run-<datum>-<tijd>.log

set -u
cd "$(dirname "$0")" || exit 1

POGINGEN=${POGINGEN:-5}
WACHT__s=${WACHT__s:-60}
CHUNK=${CHUNK:-25}

mkdir -p data
LOG="data/run-$(date +%Y%m%d-%H%M%S).log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "Start. Python: $(python -V 2>&1). Werkmap: $(pwd)"
log "Vrije schijfruimte: $(df -h . | tail -1 | awk '{print $4}')"
log "Chunkgrootte: ${CHUNK}"

for poging in $(seq 1 "$POGINGEN"); do
    log "== verwerking: poging ${poging} van ${POGINGEN}"
    if python -m im3_preprocessing.pipeline \
            --out-dir data/processed --docs-dir docs \
            --chunk-grootte "$CHUNK" -v >>"$LOG" 2>&1; then
        log "== verwerking: klaar"
        log "ALLES KLAAR. Uitvoer: data/processed/*.parquet, docs/data-quality.md"
        log "De accumulator staat als data/processed/rapport_accumulator.json -- daarmee is het"
        log "rapport voortaan te herbouwen zonder deze run over te doen:"
        log "  python -m im3_preprocessing.report --out-dir data/processed --docs-dir docs"
        exit 0
    fi
    log "== verwerking: MISLUKT; over ${WACHT__s} s hervatten vanaf het laatste voltooide stuk"
    sleep "$WACHT__s"
done

log "== OPGEGEVEN na ${POGINGEN} pogingen. Zie hierboven in ${LOG} wat er misging."
exit 1
