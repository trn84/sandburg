#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=vnc
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_VNC || idle "VNC disabled (ENABLE_VNC=0)"
wait_for_x

pw_file="${WORKSPACE}/.vnc-password"
if [ -z "${VNC_PASSWORD:-}" ]; then
    if [ -s "${pw_file}" ]; then
        VNC_PASSWORD="$(< "${pw_file}")"
    else
        VNC_PASSWORD="$(openssl rand -hex 4)"
        (umask 077 && printf '%s' "${VNC_PASSWORD}" > "${pw_file}")
        log "Generated VNC password: ${pw_file}"
    fi
fi
mkdir -p /root/.vnc
x11vnc -storepasswd "${VNC_PASSWORD}" /root/.vnc/passwd > /dev/null

# -localhost: local only; noVNC (and Tailscale) forward to it
exec x11vnc -display "${DISPLAY}" -rfbport 5900 -localhost -forever -shared \
    -rfbauth /root/.vnc/passwd -noxdamage -quiet
