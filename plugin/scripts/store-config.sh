#!/usr/bin/env bash
# SessionStart hook: stores host and token from the plugin settings for the
# "sandburg" command. Claude Code only passes the settings to hooks, not to
# commands that Claude runs; hence this detour via a file that only the
# current user can read.
# Prints nothing: the output of a SessionStart hook ends up in the context.
set -u

host="${CLAUDE_PLUGIN_OPTION_HOST:-}"
token="${CLAUDE_PLUGIN_OPTION_TOKEN:-}"
[ -n "${host}${token}" ] || exit 0

dir="${XDG_CONFIG_HOME:-${HOME}/.config}/sandburg"
file="${dir}/config"
content="$(printf 'host=%q\ntoken=%q\n' "${host}" "${token}")"

if [ -f "${file}" ] && [ "$(cat "${file}")" = "${content}" ]; then
    exit 0
fi
mkdir -p "${dir}" 2> /dev/null || exit 0
chmod 700 "${dir}" 2> /dev/null || true
(umask 077 && printf '%s\n' "${content}" > "${file}") 2> /dev/null || true
exit 0
