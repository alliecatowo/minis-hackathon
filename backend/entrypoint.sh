#!/bin/sh
# Fix volume permissions — Fly.io mounts volumes as root,
# but we want to run as appuser for security.
chown -R appuser:appuser /data 2>/dev/null || true

exec gosu appuser "$@"
