#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=novnc
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_VNC || idle "noVNC disabled (ENABLE_VNC=0)"
wait_for_port 5900 120 || { log "x11vnc not reachable"; exit 1; }
# Only protected by the VNC password, so it follows UI_BIND_ADDR, not BIND_ADDR
exec websockify --web /usr/share/novnc "${UI_BIND_ADDR:-127.0.0.1}:6080" 127.0.0.1:5900
