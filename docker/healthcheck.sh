#!/bin/bash
# Container health for the Genesis Mesh image (HEALTHCHECK).
# The Network Authority is healthy when /readyz answers 200 on its port; a
# mesh node has no HTTP endpoint, so a running process is healthy. Plain bash
# (/dev/tcp), no interpreter start-up: it stays well inside the probe timeout
# on slow or CPU-limited hosts.
set -u
case "${SERVICE_ROLE:-na}" in
    na)
        exec 2>/dev/null 3<>"/dev/tcp/127.0.0.1/${PORT:-8443}" || exit 1
        printf 'GET /readyz HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n' >&3
        IFS= read -r -t 4 status <&3 || exit 1
        case "$status" in
            "HTTP/1."?" 200 "*) exit 0 ;;
        esac
        exit 1
        ;;
    *)
        exit 0
        ;;
esac
