#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

log() {
  printf '[systemd-install] %s\n' "$*"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[systemd-install] missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd systemctl
need_cmd bash

TELEGRAF_BIN="$(command -v telegraf || true)"
if [[ -z "$TELEGRAF_BIN" ]]; then
  TELEGRAF_BIN="/usr/bin/telegraf"
fi

mkdir -p "$UNIT_DIR"

cat >"$UNIT_DIR/hsp-web-local.service" <<EOF
[Unit]
Description=HSP Web Backend (Local Collectors)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=HOST=0.0.0.0
Environment=PORT=8001
Environment=METRICS_SOURCE=local
ExecStart=$ROOT_DIR/serve_web.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

cat >"$UNIT_DIR/hsp-web-external.service" <<EOF
[Unit]
Description=HSP Web Backend (External Ingest)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=HOST=0.0.0.0
Environment=PORT=8001
Environment=METRICS_SOURCE=external
Environment=EXTERNAL_MAX_AGE_S=5
ExecStart=$ROOT_DIR/serve_web.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

cat >"$UNIT_DIR/hsp-telegraf.service" <<EOF
[Unit]
Description=Telegraf Producer for HSP External Ingest
After=network-online.target hsp-web-external.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$TELEGRAF_BIN --config $ROOT_DIR/telegraf_hsp.conf
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

cat >"$UNIT_DIR/hsp-netdata-bridge.service" <<EOF
[Unit]
Description=Netdata Bridge for HSP External Ingest
After=network-online.target hsp-web-external.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=NETDATA_URL=http://localhost:19999
Environment=INGEST_URL=ws://127.0.0.1:8001/ingest
Environment=INTERVAL=1.0
ExecStart=$ROOT_DIR/venv/bin/python $ROOT_DIR/netdata_bridge.py \
    --netdata-url \${NETDATA_URL} \
    --ingest-url \${INGEST_URL} \
    --interval \${INTERVAL}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

log "installed units in $UNIT_DIR"
log "enable local mode:       systemctl --user enable --now hsp-web-local.service"
log "enable external mode:    systemctl --user enable --now hsp-web-external.service"
log "start telegraf bridge:   systemctl --user enable --now hsp-telegraf.service"
log "start netdata bridge:    systemctl --user enable --now hsp-netdata-bridge.service"
log "check status:            systemctl --user status hsp-web-local.service"
log "view logs:               journalctl --user -u hsp-web-local.service -f"
