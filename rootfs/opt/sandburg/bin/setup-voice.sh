#!/usr/bin/env bash
# On first start with ENABLE_VOICE=1, sets up a separate Python venv for the
# speech models on the volume (several GB, hence not in the image).
# After that, only the small Sandburg server inside it is updated.
set -euo pipefail
LOG_TAG=voice-setup
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_VOICE || { log "Voice disabled (ENABLE_VOICE=0)"; exit 0; }

venv="${VOICE_VENV:-${WORKSPACE}/.sandburg/voice-venv}"
stamp="chatterbox-tts==${CHATTERBOX_VERSION} torch==${VOICE_TORCH_VERSION} ${VOICE_TORCH_INDEX}"

if [ -f "${venv}/.sandburg-stamp" ] && [ "$(< "${venv}/.sandburg-stamp")" = "${stamp}" ]; then
    log "Speech model environment present (${venv})"
else
    log "Setting up the speech model environment, this takes a few minutes …"
    rm -rf "${venv}"
    mkdir -p "$(dirname "${venv}")"
    uv venv --python /usr/bin/python3 "${venv}"
    overrides="$(mktemp)"
    # chatterbox-tts pins an older torch without support for new GPUs
    # (e.g. RTX 50xx); we force a current CUDA 12.8 build.
    printf 'torch==%s\ntorchaudio==%s\n' "${VOICE_TORCH_VERSION}" "${VOICE_TORCH_VERSION}" > "${overrides}"
    uv pip install --python "${venv}/bin/python" \
        --override "${overrides}" \
        --extra-index-url "${VOICE_TORCH_INDEX}" \
        --index-strategy unsafe-best-match \
        "chatterbox-tts==${CHATTERBOX_VERSION}"
    rm -f "${overrides}"
    printf '%s' "${stamp}" > "${venv}/.sandburg-stamp"
fi

uv pip install --python "${venv}/bin/python" --reinstall-package sandburg-voice-mcp \
    /opt/sandburg/servers/voice-mcp
touch "${venv}/.sandburg-ready"
log "Voice ready. Models are loaded on the first call (including download the first time)."
