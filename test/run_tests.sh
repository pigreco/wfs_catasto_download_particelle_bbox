#!/usr/bin/env bash
# =============================================================================
# run_tests.sh — Suite di test pre-release
# WFS Catasto Download Particelle BBox
# =============================================================================
# Uso:
#   bash test/run_tests.sh            # test unitari + release (no rete)
#   bash test/run_tests.sh --network  # aggiunge test di rete (WFS/WMS live)
#   bash test/run_tests.sh --all      # sinonimo di --network
#
# Tutti i test usano la stdlib Python, nessuna dipendenza esterna.
# =============================================================================

set -euo pipefail

# --- Trova la root del progetto (parent di test/) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# --- Parametri ---
RUN_NETWORK=false
for arg in "$@"; do
    case "$arg" in
        --network|--all) RUN_NETWORK=true ;;
    esac
done

# --- Colori ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

pass=0
fail=0
skip=0

header() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════${NC}"
}

run_test() {
    local label="$1"
    local script="$2"

    echo ""
    echo -e "${YELLOW}▶ $label${NC}"
    echo "  Script: $script"
    echo "  ──────────────────────────────────────────────────────"

    if python3 "$script"; then
        echo -e "  ${GREEN}✓ PASSATO${NC}"
        pass=$((pass + 1))
    else
        echo -e "  ${RED}✗ FALLITO${NC}"
        fail=$((fail + 1))
    fi
}

# =============================================================================
header "Test pre-release — WFS Catasto Download Particelle BBox"
echo "  Progetto: $PROJECT_ROOT"
echo "  Python:   $(python3 --version 2>&1)"
echo "  Data:     $(date '+%Y-%m-%d %H:%M:%S')"
# =============================================================================

# --- 1. Test unitari (pura logica Python, nessuna rete, nessun QGIS) ---
header "1/3  Test unitari (logica matematica e parsing)"
run_test "Matematica: area, UTM, tiling, parsing catastale" "test/test_unit.py"

# --- 2. Test pre-release (file, metadata, sintassi Python, SVG) ---
header "2/3  Test pre-release (file, metadata.txt, sintassi, SVG)"
run_test "Checklist release: file obbligatori + metadata.txt + sintassi" "test/test_release.py"

# --- 3. Test di rete (opzionale) ---
if $RUN_NETWORK; then
    header "3/3  Test di rete (WFS/WMS Agenzia delle Entrate — live)"
    echo -e "  ${YELLOW}Nota: richiede connessione internet.${NC}"
    echo -e "  ${YELLOW}       Effettua 1 query WFS su area ~0.1 km² in Basilicata.${NC}"
    run_test "Connettività WFS GetCapabilities, GetFeature, WMS GetCapabilities" "test/test_network.py"
else
    header "3/3  Test di rete (saltati)"
    echo -e "  ${YELLOW}Usa  bash test/run_tests.sh --network  per abilitarli.${NC}"
    skip=$((skip + 1))
fi

# =============================================================================
header "Riepilogo"
echo ""
echo -e "  ${GREEN}Passati : $pass${NC}"
echo -e "  ${RED}Falliti : $fail${NC}"
echo -e "  ${YELLOW}Saltati : $skip${NC}"
echo ""
# =============================================================================

if [ "$fail" -gt 0 ]; then
    echo -e "${RED}✗ RELEASE BLOCCATA — correggi i test falliti prima di procedere.${NC}"
    echo ""
    exit 1
else
    echo -e "${GREEN}✓ Tutti i test obbligatori sono passati.${NC}"
    if ! $RUN_NETWORK; then
        echo -e "${YELLOW}  Suggerimento: esegui anche i test di rete prima del rilascio:${NC}"
        echo -e "${YELLOW}  bash test/run_tests.sh --network${NC}"
    fi
    echo ""
    exit 0
fi
