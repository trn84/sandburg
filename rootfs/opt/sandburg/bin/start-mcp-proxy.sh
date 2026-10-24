#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=mcp-proxy
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh

# Briefly wait for the applications so the first tool calls don't go nowhere.
# Not critical: the MCP servers only connect on the first tool call.
check() {
    local name="$1" port="$2"
    if wait_for_port "${port}" "${STARTUP_WAIT:-180}"; then
        log "${name} ready (port ${port})"
    else
        log "WARNING: ${name} is not listening on port ${port} – see /var/log/sandburg/${name}.log"
    fi
}
enabled ENABLE_BLENDER && check blender 9876
enabled ENABLE_FREECAD && check freecad 9875
enabled ENABLE_COMFYUI && check comfyui 8188

exec /usr/local/bin/mcp-proxy -config /run/sandburg/mcp-proxy.json
