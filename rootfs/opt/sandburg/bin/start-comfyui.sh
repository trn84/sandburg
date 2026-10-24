#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=comfyui
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_COMFYUI || idle "ComfyUI disabled (ENABLE_COMFYUI=0)"

extra=()
if ! nvidia-smi -L > /dev/null 2>&1; then
    log "No NVIDIA GPU found – ComfyUI runs in CPU mode"
    extra+=(--cpu)
fi
cd /opt/ComfyUI
# shellcheck disable=SC2086
exec /opt/ComfyUI/.venv/bin/python main.py --listen "${BIND_ADDR}" --port 8188 \
    "${extra[@]}" ${COMFYUI_ARGS:-}
