#!/usr/bin/env bash
# Sets up ComfyUI's venv on the volume (PyTorch with CUDA, several GB, hence not
# in the image); /opt/ComfyUI/.venv points there. The first start takes a few
# minutes. After that, only changed requirements of a newer ComfyUI are installed.
set -euo pipefail
LOG_TAG=comfyui-setup
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh

venv="${WORKSPACE}/.sandburg/comfyui-venv"
stamp="$(torch_stamp)"
lock_torch_venvs
use_torch_cache

if [ -f "${venv}/.sandburg-stamp" ] && [ "$(< "${venv}/.sandburg-stamp")" = "${stamp}" ]; then
    log "ComfyUI environment present (${venv})"
else
    log "Setting up the ComfyUI environment with PyTorch ${TORCH_VERSION}, this takes a few minutes …"
    rm -rf "${venv}"
    uv venv --python /usr/bin/python3 "${venv}"
    uv pip install --python "${venv}/bin/python" --index-url "${TORCH_INDEX}" \
        "torch==${TORCH_VERSION}" torchvision torchaudio
fi
# Fast and offline when nothing has changed. torch from requirements.txt is
# already satisfied by the CUDA build above.
uv pip install --python "${venv}/bin/python" -r /opt/ComfyUI/requirements.txt "comfy-cli>=1.14"
printf '%s' "${stamp}" > "${venv}/.sandburg-stamp"
ln -sfn "${venv}" /opt/ComfyUI/.venv
# Removes leftovers of aborted downloads, which can be several GB.
uv cache prune --quiet
log "ComfyUI environment ready"
