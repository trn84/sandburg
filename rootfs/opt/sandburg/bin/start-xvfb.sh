#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=xvfb
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
# Xvfb's GLX extension goes through glvnd's EGL as well. Without this, glvnd
# picks the NVIDIA EGL driver that the container toolkit mounts on GPU hosts,
# and Xvfb segfaults on startup (libnvidia-egl-gbm, seen on RunPod).
use_mesa_gl
n="${DISPLAY#:}"
rm -f "/tmp/.X${n}-lock" "/tmp/.X11-unix/X${n}"
exec Xvfb "${DISPLAY}" -screen 0 "${XVFB_RESOLUTION:-1920x1080x24}" \
    -nolisten tcp -noreset +extension GLX +extension RANDR +render
