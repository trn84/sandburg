#!/usr/bin/env bash
# With ENABLE_COMFYUI_3D=1, downloads the Hunyuan3D 2.1 model (about 7.4 GB) to the
# volume once. ComfyUI supports it natively; template in the workflow catalog: "3d_hunyuan3d-v2.1".
set -euo pipefail
LOG_TAG=comfyui-3d
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
if ! enabled ENABLE_COMFYUI || ! enabled ENABLE_COMFYUI_3D; then
    log "ComfyUI 3D disabled (ENABLE_COMFYUI_3D=0)"
    exit 0
fi

target_dir="${WORKSPACE}/comfyui/models/checkpoints"
target="${target_dir}/hunyuan_3d_v2.1.safetensors"
url="${HUNYUAN3D_URL:-https://huggingface.co/Comfy-Org/hunyuan3D_2.1_repackaged/resolve/main/hunyuan_3d_v2.1.safetensors}"
mkdir -p "${target_dir}"

if [ -s "${target}" ]; then
    log "Hunyuan3D 2.1 present"
    exit 0
fi
log "Downloading Hunyuan3D 2.1 (about 7.4 GB) to ${target} …"
# -C - resumes an interrupted download
curl -fL --retry 5 --retry-delay 10 -C - -o "${target}.part" "${url}"
mv "${target}.part" "${target}"
log "Hunyuan3D 2.1 ready"
