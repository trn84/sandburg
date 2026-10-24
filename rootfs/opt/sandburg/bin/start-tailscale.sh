#!/usr/bin/env bash
set -euo pipefail
LOG_TAG=tailscale
# shellcheck source=common.sh
source /opt/sandburg/bin/common.sh
[ -n "${TS_AUTHKEY:-}" ] || idle "TS_AUTHKEY not set – Tailscale stays off"

sock=/var/run/tailscale/tailscaled.sock
mkdir -p /var/run/tailscale

# By default the state lives in memory only: the node is then always ephemeral,
# and tailscaled logs out when the container stops, so the pod disappears from
# the tailnet at once instead of 30–60 minutes later. TS_STATE_DIR keeps the
# node (and its IP) across restarts instead; it then never re-authenticates
# with TS_AUTHKEY and stays in the tailnet after the pod is gone.
if [ -n "${TS_STATE_DIR:-}" ]; then
    mkdir -p "${TS_STATE_DIR}"
    state=(--statedir="${TS_STATE_DIR}")
else
    state=(--state=mem:)
fi

# Userspace networking: needs no /dev/net/tun (RunPod and similar clouds usually
# don't have it). Incoming tailnet connections are forwarded to 127.0.0.1:<port>.
tailscaled --tun=userspace-networking "${state[@]}" --socket="${sock}" &
ts_pid=$!

# On stop: log out first (removes the ephemeral node at once), then stop
# tailscaled. Logged to the volume, since the container log is gone afterwards.
shutdown_log="${WORKSPACE}/.sandburg/shutdown.log"
note() {
    log "$*"
    mkdir -p "$(dirname "${shutdown_log}")"
    printf '%s %s\n' "$(date -Is)" "$*" >> "${shutdown_log}"
}
leave() {
    note "Stop received, leaving the tailnet"
    if [ -z "${TS_STATE_DIR:-}" ]; then
        if timeout 5 tailscale --socket="${sock}" logout; then
            note "Logged out of the tailnet"
        else
            note "WARNING: logout failed – the node disappears only after 30–60 minutes"
        fi
    fi
    kill -TERM "${ts_pid}" 2> /dev/null || true
    wait "${ts_pid}" || true
    note "tailscaled stopped"
    exit 0
}
trap leave TERM INT

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
