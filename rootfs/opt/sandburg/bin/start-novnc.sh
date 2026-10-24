#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=novnc
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_VNC || idle "noVNC disabled (ENABLE_VNC=0)"
wait_for_port 5900 120 || { log "x11vnc not reachable"; exit 1; }
exec websockify --web /usr/share/novnc "${BIND_ADDR}:6080" 127.0.0.1:5900
