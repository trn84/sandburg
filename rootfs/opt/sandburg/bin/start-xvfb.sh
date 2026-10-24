#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=xvfb
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
n="${DISPLAY#:}"
rm -f "/tmp/.X${n}-lock" "/tmp/.X11-unix/X${n}"
exec Xvfb "${DISPLAY}" -screen 0 "${XVFB_RESOLUTION:-1920x1080x24}" \
    -nolisten tcp -noreset +extension GLX +extension RANDR +render
