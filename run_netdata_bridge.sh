#!/usr/bin/env bash
# run_netdata_bridge.sh — Start HSP in external mode and poll Netdata for metrics.
# Requires: Netdata running on localhost:19999, HSP venv bootstrapped.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NETDATA_URL="${NETDATA_URL:-http://localhost:19999}"
INGEST_URL="${INGEST_URL:-ws://127.0.0.1:8001/ingest}"
INTERVAL="${INTERVAL:-1.0}"
LOG_FILE="/tmp/netdata_bridge_hsp.log"

# Verify Netdata is reachable
if ! curl -sf "${NETDATA_URL}/api/v1/info" >/dev/null 2>&1; then
    echo "[netdata-bridge] ERROR: Netdata not reachable at ${NETDATA_URL}"
    echo "                  Install with:  bash <(curl -Ss https://my-netdata.io/kickstart.sh)"
    exit 1
fi

# Bootstrap and start HSP backend in external mode
METRICS_SOURCE=external bash "$SCRIPT_DIR/run_web.sh"

echo "[netdata-bridge] Starting Netdata bridge (log: ${LOG_FILE})"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/netdata_bridge.py" \
    --netdata-url "$NETDATA_URL" \
    --ingest-url  "$INGEST_URL" \
    --interval    "$INTERVAL" \
    >> "$LOG_FILE" 2>&1 &

BRIDGE_PID=$!
echo "[netdata-bridge] Bridge PID ${BRIDGE_PID}. Tail log: tail -f ${LOG_FILE}"
echo "[netdata-bridge] Open http://localhost:8001/"
