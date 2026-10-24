#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=tailscale
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
[ -n "${TS_AUTHKEY:-}" ] || idle "TS_AUTHKEY not set – Tailscale stays off"

state_dir="${TS_STATE_DIR:-${WORKSPACE}/.tailscale}"
sock=/var/run/tailscale/tailscaled.sock
mkdir -p "${state_dir}" /var/run/tailscale

# Userspace networking: needs no /dev/net/tun (RunPod and similar clouds usually
# don't have it). Incoming tailnet connections are forwarded to 127.0.0.1:<port>.
tailscaled --tun=userspace-networking --statedir="${state_dir}" --socket="${sock}" &
ts_pid=$!

for _ in $(seq 1 30); do
    [ -S "${sock}" ] && break
    sleep 1
done

# shellcheck disable=SC2086
tailscale --socket="${sock}" up \
    --auth-key="${TS_AUTHKEY}" \
    --hostname="${TS_HOSTNAME:-sandburg}" \
    --accept-dns=false \
    ${TS_EXTRA_ARGS:-}

log "In the tailnet as ${TS_HOSTNAME:-sandburg} ($(tailscale --socket="${sock}" ip -4 2> /dev/null | head -n1))"
wait "${ts_pid}"
