#!/usr/bin/env bash
# Shared helper functions for all startup scripts.

WORKSPACE="${WORKSPACE:-/workspace}"
DISPLAY="${DISPLAY:-:99}"
export WORKSPACE DISPLAY

log() {
    printf '[%s] [%s] %s\n' "$(date +%H:%M:%S)" "${LOG_TAG:-sandburg}" "$*"
}

# true if the variable is 1/true/yes/on (unset = on)
enabled() {
    case "${!1:-1}" in
        1 | true | TRUE | yes | on) return 0 ;;
        *) return 1 ;;
    esac
}

# For disabled services: keep the process alive so supervisord doesn't keep
# restarting it, but do nothing.
idle() {
    log "$*"
    exec sleep infinity
}

# Waits until a TCP port is listening locally. $1=port, $2=timeout in seconds
wait_for_port() {
    local port="$1" timeout="${2:-120}" i
    for ((i = 0; i < timeout; i++)); do
        if (exec 3<> "/dev/tcp/127.0.0.1/${port}") 2> /dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# Waits for the virtual X server
wait_for_x() {
    local n="${DISPLAY#:}" i
    n="${n%%.*}"
    for ((i = 0; i < 60; i++)); do
        if [ -S "/tmp/.X11-unix/X${n}" ] && xdpyinfo > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    log "X server ${DISPLAY} not reachable"
    return 1
}

# Forces Mesa (llvmpipe) for Xvfb and the GUIs running on it. GPU rendering
# (Cycles/CUDA/OptiX, PyTorch) is not affected by this.
use_mesa_gl() {
    export __GLX_VENDOR_LIBRARY_NAME=mesa
    if [ -f /usr/share/glvnd/egl_vendor.d/50_mesa.json ]; then
        export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json
    fi
    mkdir -p "${XDG_RUNTIME_DIR:-/tmp/runtime-root}"
    chmod 700 "${XDG_RUNTIME_DIR:-/tmp/runtime-root}"
}

# ComfyUI and Voice each have a venv with the same PyTorch on the volume. With a
# shared uv cache there, uv hardlinks the identical files (torch and the CUDA
# libraries, several GB) instead of storing them twice. There is one cache per
# PyTorch version, so an update doesn't leave the old version behind.
use_torch_cache() {
    local root="${WORKSPACE}/.cache/uv-torch" name="${TORCH_VERSION}-${TORCH_INDEX##*/}"
    mkdir -p "${root}"
    find "${root}" -mindepth 1 -maxdepth 1 ! -name "${name}" -exec rm -rf {} +
    export UV_CACHE_DIR="${root}/${name}" UV_LINK_MODE=hardlink
    # The CUDA wheels are several hundred MB each. On a slow line uv's default of
    # 30 s without data aborts the whole install, and every retry starts over.
    export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
}

# Takes the lock for the venvs on the volume until the calling script exits, so
# ComfyUI and Voice don't install into the shared cache at the same time.
lock_torch_venvs() {
    mkdir -p "${WORKSPACE}/.sandburg"
    exec 9> "${WORKSPACE}/.sandburg/torch.lock"
    flock 9
}

# Fingerprint of a venv's base. If it changes, the venv is rebuilt.
torch_stamp() {
    printf '%s torch==%s %s' "$(/usr/bin/python3 -V)" "${TORCH_VERSION}" "${TORCH_INDEX}"
}
