#!/usr/bin/env bash
# Container entrypoint: prepares /workspace, generates the token and proxy config,
# then hands over to supervisord.
set -euo pipefail
LOG_TAG=entrypoint
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh

projects="${WORKSPACE}/projects"
mkdir -p /var/log/sandburg /run/sandburg "${WORKSPACE}/.sandburg"
for d in blender freecad kicad build123d inkscape browser audio; do
    mkdir -p "${projects}/${d}"
done

# --- Token (MCP proxy and file server) ---------------------------------------
token_file="${WORKSPACE}/.sandburg-token"
if [ -z "${SANDBURG_TOKEN:-}" ]; then
    if [ -s "${token_file}" ]; then
        SANDBURG_TOKEN="$(< "${token_file}")"
    else
        SANDBURG_TOKEN="$(openssl rand -hex 24)"
        (umask 077 && printf '%s' "${SANDBURG_TOKEN}" > "${token_file}")
        log "Generated a new token and saved it to ${token_file}"
    fi
fi
# The token also ends up in the file server's access rule (user:pass@/path),
# so characters with a special meaning there are not allowed.
if [[ ! "${SANDBURG_TOKEN}" =~ ^[A-Za-z0-9._~-]{16,}$ ]]; then
    log "ERROR: SANDBURG_TOKEN must be at least 16 characters long and may only contain A-Z, a-z, 0-9 and . _ ~ -"
    exit 1
fi
export SANDBURG_TOKEN

# --- ComfyUI -----------------------------------------------------------------
# Inputs and outputs live under projects/comfyui so the file server serves
# them. Models and user data stay under /workspace/comfyui.
if enabled ENABLE_COMFYUI; then
    comfy_dir=/opt/ComfyUI
    declare -A targets=(
        [input]="${projects}/comfyui/input"
        [output]="${projects}/comfyui/output"
        [models]="${WORKSPACE}/comfyui/models"
        [user]="${WORKSPACE}/comfyui/user"
    )
    for d in "${!targets[@]}"; do
        target="${targets[$d]}"
        mkdir -p "${target}"
        if [ -L "${comfy_dir}/${d}" ]; then
            continue
        fi
        if [ -d "${comfy_dir}/${d}" ]; then
            # Keep the bundled structure (e.g. models/checkpoints), don't overwrite anything
            cp -a -n "${comfy_dir}/${d}/." "${target}/" 2> /dev/null || true
            rm -rf "${comfy_dir:?}/${d}"
        fi
        ln -s "${target}" "${comfy_dir}/${d}"
    done
fi

# --- Proxy config: replace disabled services with a placeholder -------------
# The Claude Code plugin always connects all services. This way a disabled service
# doesn't show up as an error there, but explains how to enable it.
declare -A service_flags=(
    [blender]=ENABLE_BLENDER [freecad]=ENABLE_FREECAD [kicad]=ENABLE_KICAD
    [comfyui]=ENABLE_COMFYUI [build123d]=ENABLE_BUILD123D [inkscape]=ENABLE_INKSCAPE
    [browser]=ENABLE_BROWSER [voice]=ENABLE_VOICE
)
filter='.'
for service in "${!service_flags[@]}"; do
    flag="${service_flags[$service]}"
    if ! enabled "${flag}"; then
        filter+=" | .mcpServers.${service} = {\"command\": \"/usr/local/bin/sandburg-disabled-mcp\", \"args\": [\"${service}\", \"${flag}\"]}"
    fi
done
jq "${filter}" /opt/sandburg/mcp-proxy.template.json > /run/sandburg/mcp-proxy.json
mcp-proxy -config /run/sandburg/mcp-proxy.json -check-config

# --- Summary in the container log --------------------------------------------
host="${TS_HOSTNAME:-sandburg}"
servers="$(jq -r '.mcpServers | to_entries[] | select(.value.command != "/usr/local/bin/sandburg-disabled-mcp") | .key' /run/sandburg/mcp-proxy.json | sort | tr '\n' ' ')"
{
    echo "=================================================================="
    echo " Sandburg"
    echo "------------------------------------------------------------------"
    if [ -z "${TS_AUTHKEY:-}" ]; then
        echo " Tailscale: OFF (TS_AUTHKEY not set)"
    else
        echo " Tailscale hostname: ${host}"
    fi
    echo " Token: ${token_file} (or env SANDBURG_TOKEN)"
    echo
    echo " Active services: ${servers}"
    echo
    echo " Connect Claude Code (run locally, asks for host and token):"
    echo "   claude plugin install sandburg --marketplace <github-user>/sandburg"
    echo
    if enabled ENABLE_FILES; then
        echo " Files (browser/WebDAV): http://${host}:8090  user: sandburg, password: token"
    fi
    if enabled ENABLE_VNC; then
        echo " Desktop (noVNC): http://${host}:6080/vnc.html"
    fi
    if enabled ENABLE_COMFYUI; then
        echo " ComfyUI web UI: http://${host}:8188"
    fi
    if enabled ENABLE_VOICE; then
        echo " Voice: set up on first start (log: /var/log/sandburg/voice-setup.log)"
    fi
    echo "=================================================================="
}

exec /usr/bin/supervisord -n -c /opt/sandburg/supervisord.conf
