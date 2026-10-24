#!/usr/bin/env bash
# File server (dufs) for /workspace/projects: browser, curl and WebDAV.
set -euo pipefail
LOG_TAG=files
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
enabled ENABLE_FILES || idle "File server disabled (ENABLE_FILES=0)"

root="${WORKSPACE}/projects"
mkdir -p "${root}"

# Permissions via the environment instead of an argument so the token doesn't
# show up in the process list. User "sandburg" may do everything, anonymous nothing.
export DUFS_AUTH="sandburg:${SANDBURG_TOKEN}@/:rw"

exec /usr/local/bin/dufs "${root}" \
    --bind "${BIND_ADDR}" \
    --port 8090 \
    --allow-all \
    --hidden '.*'
