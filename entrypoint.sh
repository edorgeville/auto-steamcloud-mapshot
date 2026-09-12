#!/bin/sh
# Root-only setup, then hand over to the Python entrypoint as an unprivileged
# user. Everything else lives in the app package.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
APP_USER=mapshot
APP_HOME=/data/home

log() { printf '%s %-7s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "ENTRY" "$*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    # Started with --user; nothing to set up, just run.
    export HOME="${HOME:-/tmp}"
    exec python3 -m app "$@"
fi

if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" "$APP_USER"
fi
if ! getent passwd "$PUID" >/dev/null 2>&1; then
    useradd -u "$PUID" -g "$PGID" -M -d "$APP_HOME" -s /bin/sh "$APP_USER"
fi

# A recursive chown of /data can mean tens of thousands of files, so only do it
# when the directory is not already ours - that is, on first run or after a
# PUID change.
for dir in /config /data /output "$APP_HOME"; do
    mkdir -p "$dir"
    owner="$(stat -c '%u:%g' "$dir")"
    if [ "$owner" != "$PUID:$PGID" ]; then
        log "taking ownership of $dir (was $owner, now $PUID:$PGID)"
        chown -R "$PUID:$PGID" "$dir"
    fi
done

export HOME="$APP_HOME"
exec gosu "$PUID:$PGID" python3 -m app "$@"
