#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=mcp-proxy
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh

# Report in the log when the applications are ready, without holding up the
# proxy: the MCP servers only connect to them on the first tool call, so the
# services that don't need a GUI are usable right away.
check() {
    local name="$1" port="$2"
    if wait_for_port "${port}" "${STARTUP_WAIT:-180}"; then
        log "${name} ready (port ${port})"
    else
        log "WARNING: ${name} is not listening on port ${port} – see /var/log/sandburg/${name}.log"
    fi
}
# Detached via a synchronous subshell, so the checks are reparented to
# supervisord (which reaps them) instead of becoming zombies under mcp-proxy.
(
    {
        enabled ENABLE_BLENDER && check blender 9876 &
        enabled ENABLE_FREECAD && check freecad 9875 &
        enabled ENABLE_COMFYUI && check comfyui 8188 &
        wait
    } &
)

exec /usr/local/bin/mcp-proxy -config /run/sandburg/mcp-proxy.json
