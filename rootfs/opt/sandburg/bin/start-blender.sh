#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=blender
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_BLENDER || idle "Blender disabled (ENABLE_BLENDER=0)"
wait_for_x
use_mesa_gl
mkdir -p "${WORKSPACE}/projects/blender"
cd "${WORKSPACE}/projects/blender"
# The addon starts its socket server (localhost:9876) automatically once the
# GUI is ready. gpu_setup.py switches Cycles to OptiX/CUDA if available.
# shellcheck disable=SC2086
exec /opt/blender/blender --addons blender_mcp \
    --python /opt/sandburg/blender/gpu_setup.py ${BLENDER_ARGS:-}
