# syntax=docker/dockerfile:1.7
#
# Sandburg: Blender, FreeCAD, KiCad, build123d, Inkscape, ComfyUI, a browser
# (Playwright) and optional speech output – with preconfigured MCP servers behind
# a shared HTTP endpoint (mcp-proxy), reachable via Tailscale. Intended for RunPod
# and similar clouds, but runs on any Docker host with the NVIDIA Container Toolkit
# (and even without a GPU if need be). Results are fetched back via the built-in
# file server (dufs).

ARG CUDA_BASE=nvidia/cuda:12.8.1-base-ubuntu24.04

# ---------------------------------------------------------------------------
# Stage 1: mcp-proxy (bundles all stdio MCP servers behind one HTTP port)
# ---------------------------------------------------------------------------
FROM golang:1.26 AS mcp-proxy
ARG MCP_PROXY_VERSION=latest
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/tbxark/mcp-proxy@${MCP_PROXY_VERSION}

# ---------------------------------------------------------------------------
# Stage 2: the Sandburg itself
# ---------------------------------------------------------------------------
FROM ${CUDA_BASE}

# --- Versions (all overridable via --build-arg) ------------------------------
ARG BLENDER_VERSION=5.2.3
ARG BLENDER_MCP_VERSION=2.2.4
ARG FREECAD_VERSION=1.1.4
ARG FREECAD_URL=https://github.com/FreeCAD/FreeCAD/releases/download/${FREECAD_VERSION}/FreeCAD_${FREECAD_VERSION}-Linux-x86_64-py311.AppImage
ARG FREECAD_MCP_REF=main
ARG KICAD_PPA=kicad-10.0-releases
ARG KICAD_3D_MODELS=false
ARG KICAD_MCP_REF=main
ARG COMFYUI_REF=master
ARG TORCH_CUDA=cu128
ARG COMFY_MCP_VERSION=0.10.0
ARG DUFS_VERSION=0.47.0
ARG BUILD123D_MCP_VERSION=0.3.91
ARG INKSCAPE_PPA=inkscape.dev/stable
ARG NODE_MAJOR=22
ARG PLAYWRIGHT_MCP_VERSION=0.0.83

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    WORKSPACE=/workspace \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/runtime-root \
    BIND_ADDR=127.0.0.1 \
    UI_BIND_ADDR=127.0.0.1 \
    TS_HOSTNAME=sandburg \
    ENABLE_BLENDER=1 \
    ENABLE_FREECAD=1 \
    ENABLE_KICAD=1 \
    ENABLE_COMFYUI=1 \
    ENABLE_VNC=1 \
    ENABLE_FILES=1 \
    ENABLE_BUILD123D=1 \
    ENABLE_INKSCAPE=1 \
    ENABLE_BROWSER=1 \
    ENABLE_VOICE=0 \
    ENABLE_COMFYUI_3D=0 \
    CHATTERBOX_VERSION=0.1.7 \
    VOICE_TORCH_VERSION=2.8.0 \
    VOICE_TORCH_INDEX=https://download.pytorch.org/whl/cu128 \
    VOICE_IDLE_MINUTES=10 \
    HF_HOME=/workspace/.cache/huggingface \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    BLENDER_MCP_SAFE_MODE=0 \
    BLENDERMCP_NO_UPDATE_CHECK=1 \
    DISABLE_TELEMETRY=true \
    DO_NOT_TRACK=1 \
    QTWEBENGINE_DISABLE_SANDBOX=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# --- Base: X server, VNC, Supervisor, GL/Qt libraries -------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git xz-utils unzip jq gnupg openssl iproute2 procps \
        software-properties-common \
        supervisor xvfb x11vnc novnc websockify openbox x11-utils xauth \
        python3 python3-venv python3-pip \
        libgl1 libegl1 libglx-mesa0 libgl1-mesa-dri libglu1-mesa libglvnd0 \
        libxi6 libxxf86vm1 libxfixes3 libxrender1 libxrandr2 libxinerama1 libxcursor1 \
        libxkbcommon0 libxkbcommon-x11-0 libsm6 libice6 libx11-xcb1 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxcb-xfixes0 libxcb-glx0 \
        libwayland-client0 libwayland-cursor0 libwayland-egl1 libdecor-0-0 \
        libfontconfig1 libfreetype6 libdbus-1-3 libnss3 libasound2t64 libpulse0 \
        fonts-dejavu-core ffmpeg potrace \
    && rm -rf /var/lib/apt/lists/*

# --- uv (Python package/tool manager) -----------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# --- dufs (file server: browser, curl, WebDAV) --------------------------------
RUN curl -fsSL "https://github.com/sigoden/dufs/releases/download/v${DUFS_VERSION}/dufs-v${DUFS_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin dufs \
    && dufs --version

# --- mcp-proxy ----------------------------------------------------------------
COPY --from=mcp-proxy /out/mcp-proxy /usr/local/bin/mcp-proxy

# --- Tailscale ----------------------------------------------------------------
RUN curl -fsSL https://tailscale.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/* \
    && tailscale version

# --- KiCad (only the CLI + Python module are used, no GUI needed) -------------
RUN add-apt-repository -y "ppa:kicad/${KICAD_PPA}" \
    && apt-get update \
    && extra=""; if [ "${KICAD_3D_MODELS}" = "true" ]; then extra="kicad-packages3d"; fi \
    && apt-get install -y --no-install-recommends \
        kicad kicad-symbols kicad-footprints kicad-templates ${extra} \
    && rm -rf /var/lib/apt/lists/* \
    && kicad-cli version \
    && python3 -c "import pcbnew; print('pcbnew', pcbnew.Version())"

# --- KiCad-MCP (Seeed Studio) -------------------------------------------------
# Runs on the system Python so that "import pcbnew" from the KiCad package works.
RUN git clone --depth 1 --branch "${KICAD_MCP_REF}" https://github.com/Seeed-Studio/kicad-mcp-server.git /opt/kicad-mcp/src \
    && uv venv --system-site-packages --python /usr/bin/python3 /opt/kicad-mcp/.venv \
    && uv pip install --python /opt/kicad-mcp/.venv/bin/python /opt/kicad-mcp/src \
    && /opt/kicad-mcp/.venv/bin/python -c "import kicad_mcp_server, pcbnew; print('kicad-mcp ok')"

# --- Blender ------------------------------------------------------------------
RUN series="${BLENDER_VERSION%.*}" \
    && curl -fL "https://download.blender.org/release/Blender${series}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /opt \
    && mv "/opt/blender-${BLENDER_VERSION}-linux-x64" /opt/blender \
    && ln -s /opt/blender/blender /usr/local/bin/blender \
    && blender --version

# --- MCP for Blender (server + addon from the same package) --------------------
RUN uv tool install --python /usr/bin/python3 "mcp-for-blender==${BLENDER_MCP_VERSION}" \
    && addon="$(find "${UV_TOOL_DIR}/mcp-for-blender" -path '*/blender_mcp/bundled/addon.py' | head -n1)" \
    && test -n "${addon}" \
    && dest="/root/.config/blender/${BLENDER_VERSION%.*}/scripts/addons" \
    && mkdir -p "${dest}" \
    && cp "${addon}" "${dest}/blender_mcp.py" \
    && blender -b --factory-startup --python-exit-code 1 --addons blender_mcp --python-expr \
        "import addon_utils; assert addon_utils.check('blender_mcp')[1], 'blender_mcp addon not loaded'; print('blender_mcp addon ok')"

# --- FreeCAD (AppImage, extracted -> no FUSE needed) ---------------------------
RUN curl -fL -o /tmp/FreeCAD.AppImage "${FREECAD_URL}" \
    && chmod +x /tmp/FreeCAD.AppImage \
    && cd /opt && /tmp/FreeCAD.AppImage --appimage-extract > /dev/null \
    && mv /opt/squashfs-root /opt/freecad \
    && rm /tmp/FreeCAD.AppImage \
    && test -x /opt/freecad/AppRun

# --- FreeCAD-MCP (neka-nat): addon into the system Mod directory, server via uv -
# The addon is patched so that the RPC server starts automatically on launch.
RUN git clone --depth 1 --branch "${FREECAD_MCP_REF}" https://github.com/neka-nat/freecad-mcp.git /tmp/freecad-mcp \
    && marker="$(find /opt/freecad -path '*/Mod/PartDesign/InitGui.py' | head -n1)" \
    && test -n "${marker}" \
    && moddir="$(dirname "$(dirname "${marker}")")" \
    && cp -r /tmp/freecad-mcp/addon/FreeCADMCP "${moddir}/" \
    && sed -i 's/"auto_start_rpc": False/"auto_start_rpc": True/' "${moddir}/FreeCADMCP/rpc_server/settings.py" \
    && grep -q '"auto_start_rpc": True' "${moddir}/FreeCADMCP/rpc_server/settings.py" \
    && uv tool install --python /usr/bin/python3 /tmp/freecad-mcp \
    && rm -rf /tmp/freecad-mcp \
    && echo "FreeCADMCP addon -> ${moddir}"

# --- build123d-MCP (CAD as Python code) ---------------------------------------
RUN uv tool install --python /usr/bin/python3 "build123d-mcp==${BUILD123D_MCP_VERSION}" \
    && build123d-mcp --version

# --- Inkscape (command line) + Python packages for the export extensions ------
RUN add-apt-repository -y "ppa:${INKSCAPE_PPA}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        inkscape python3-lxml python3-numpy python3-tinycss2 python3-cssselect \
    && rm -rf /var/lib/apt/lists/* \
    && inkscape --version

# --- Node.js + Playwright MCP with Chromium ------------------------------------
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
    && cd "$(npm root -g)/@playwright/mcp" \
    && npx playwright install --with-deps chromium \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/* \
    && playwright-mcp --version

# --- ComfyUI + comfy-cli + official Comfy MCP server --------------------------
RUN git clone --depth 1 --branch "${COMFYUI_REF}" https://github.com/Comfy-Org/ComfyUI.git /opt/ComfyUI \
    && uv venv --python /usr/bin/python3 /opt/ComfyUI/.venv \
    && uv pip install --python /opt/ComfyUI/.venv/bin/python \
        torch torchvision torchaudio --index-url "https://download.pytorch.org/whl/${TORCH_CUDA}" \
    && uv pip install --python /opt/ComfyUI/.venv/bin/python \
        -r /opt/ComfyUI/requirements.txt "comfy-cli>=1.14" \
    && /opt/ComfyUI/.venv/bin/comfy --skip-prompt set-default /opt/ComfyUI \
    && (/opt/ComfyUI/.venv/bin/comfy --skip-prompt tracking disable || true) \
    && uv tool install --python /usr/bin/python3 "comfy-mcp==${COMFY_MCP_VERSION}" \
    && uv cache clean

# --- Custom MCP servers (Inkscape built in, Voice is installed on the volume
#     on demand, see setup-voice.sh) -------------------------------------------
COPY servers/ /opt/sandburg/servers/
RUN uv tool install --python /usr/bin/python3 /opt/sandburg/servers/inkscape-mcp \
    && uv tool install --python /usr/bin/python3 /opt/sandburg/servers/disabled-mcp \
    && uv cache clean

# --- Custom scripts & configuration ------------------------------------------
COPY rootfs/ /
RUN chmod +x /opt/sandburg/bin/* \
    && ln -s /opt/sandburg/bin/sandburg-status /usr/local/bin/sandburg-status \
    && mkdir -p /var/log/sandburg /run/sandburg "${WORKSPACE}"

WORKDIR /workspace

# For documentation only – in normal operation everything goes through Tailscale.
# 9090 = MCP proxy, 8090 = file server, 6080 = noVNC, 8188 = ComfyUI web UI
EXPOSE 9090 8090 6080 8188

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9090/_healthz > /dev/null || exit 1

ENTRYPOINT ["/opt/sandburg/bin/entrypoint.sh"]

# Links the image to the repository on GitHub, also for locally pushed builds.
# Kept at the end so changing it doesn't invalidate the build cache.
LABEL org.opencontainers.image.source="https://github.com/trn84/sandburg" \
      org.opencontainers.image.description="Blender, FreeCAD, KiCad, build123d, Inkscape, ComfyUI and a browser with MCP servers for Claude Code" \
      org.opencontainers.image.licenses="MIT"
