#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=freecad
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_FREECAD || idle "FreeCAD disabled (ENABLE_FREECAD=0)"
wait_for_x
use_mesa_gl
export QT_QPA_PLATFORM=xcb
mkdir -p "${WORKSPACE}/projects/freecad"
cd "${WORKSPACE}/projects/freecad"
# The FreeCADMCP addon starts its XML-RPC server (localhost:9875) automatically.
# shellcheck disable=SC2086
exec /opt/freecad/AppRun ${FREECAD_ARGS:-}
