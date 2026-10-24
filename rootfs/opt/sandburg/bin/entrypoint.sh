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

# --- Catch typos in variable names -------------------------------------------
# A misspelled name such as SANDBURG_TOKN is otherwise silently ignored and the
# container falls back to its defaults, e.g. a generated token.
known_vars=" SANDBURG_TOKEN SANDBURG_PROJECTS TS_AUTHKEY TS_HOSTNAME TS_EXTRA_ARGS TS_STATE_DIR
    ENABLE_BLENDER ENABLE_FREECAD ENABLE_KICAD ENABLE_BUILD123D ENABLE_INKSCAPE ENABLE_BROWSER
    ENABLE_COMFYUI ENABLE_COMFYUI_3D ENABLE_VNC ENABLE_FILES ENABLE_VOICE
    VOICE_IDLE_MINUTES VOICE_WHISPER_MODEL VOICE_VENV
    VOICE_TORCH_VERSION VOICE_TORCH_INDEX "
known_vars="${known_vars//$'\n'/ }"
while IFS= read -r name; do
    case "${known_vars}" in *" ${name} "*) continue ;; esac
    case "${name}" in TS_DEBUG_*) continue ;; esac # Tailscale's own debug switches
    log "WARNING: environment variable ${name} is not used by Sandburg – typo?"
done < <(compgen -e | grep -iE '^(SANDBURG|TS|ENABLE|VOICE)_|SANDB' | grep -viE 'SANDBOX' || true)

# --- Token (MCP proxy and file server) ---------------------------------------
token_file="${WORKSPACE}/.sandburg-token"
if [ -z "${SANDBURG_TOKEN:-}" ]; then
    if [ -s "${token_file}" ]; then
        SANDBURG_TOKEN="$(< "${token_file}")"
        log "SANDBURG_TOKEN not set – using the token from ${token_file}"
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

# --- Warn about listen addresses that are never needed on a pod --------------
is_loopback() {
    case "$1" in
        127.* | localhost | ::1) return 0 ;;
        *) return 1 ;;
    esac
}
if [ -n "${TS_AUTHKEY:-}" ] && ! is_loopback "${BIND_ADDR}"; then
    log "WARNING: BIND_ADDR=${BIND_ADDR} while Tailscale is active. Tailscale already forwards to 127.0.0.1, so this only makes the MCP proxy and file server reachable outside the tailnet. Leave BIND_ADDR at 127.0.0.1."
fi
if ! is_loopback "${UI_BIND_ADDR:-127.0.0.1}"; then
    log "WARNING: UI_BIND_ADDR=${UI_BIND_ADDR}: noVNC and ComfyUI listen beyond localhost, and ComfyUI has no authentication. Only meant for local docker compose; never expose ports 6080 or 8188."
fi

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
    echo "   claude plugin marketplace add trn84/sandburg"
    echo "   claude plugin install sandburg@sandburg"
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
