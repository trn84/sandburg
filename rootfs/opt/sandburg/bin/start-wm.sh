#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=openbox
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
wait_for_x
exec openbox
