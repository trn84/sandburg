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
spacy_model="https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
stamp="kokoro==${KOKORO_VERSION} torch==${VOICE_TORCH_VERSION} ${VOICE_TORCH_INDEX} ${spacy_model##*/}"

if [ -f "${venv}/.sandburg-stamp" ] && [ "$(< "${venv}/.sandburg-stamp")" = "${stamp}" ]; then
    log "Speech model environment present (${venv})"
else
    log "Setting up the speech model environment, this takes a few minutes …"
    rm -rf "${venv}"
    mkdir -p "$(dirname "${venv}")"
    uv venv --python /usr/bin/python3 "${venv}"
    # torch from the CUDA 12.8 index, so new GPUs (e.g. RTX 50xx) are supported.
    # misaki would download the spaCy model with pip at the first call, which the
    # uv venv doesn't have, so it is installed here.
    uv pip install --python "${venv}/bin/python" \
        --extra-index-url "${VOICE_TORCH_INDEX}" \
        --index-strategy unsafe-best-match \
        "torch==${VOICE_TORCH_VERSION}" \
        "kokoro==${KOKORO_VERSION}" "misaki[en,zh]==${KOKORO_VERSION}" soundfile \
        "en_core_web_sm @ ${spacy_model}"
    printf '%s' "${stamp}" > "${venv}/.sandburg-stamp"
fi

# preshed 3.0.14 breaks loading the spaCy model ("OverflowError: Python int too
# large to convert to C ssize_t"). Outside the stamp, so existing venvs get it too.
uv pip install --python "${venv}/bin/python" --reinstall-package sandburg-voice-mcp \
    "preshed==3.0.13" /opt/sandburg/servers/voice-mcp
touch "${venv}/.sandburg-ready"
log "Voice ready. Models are loaded on the first call (including download the first time)."
