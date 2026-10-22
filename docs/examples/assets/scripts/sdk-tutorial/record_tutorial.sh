#!/usr/bin/env bash
# Records a real run of the SDK tutorial against a fresh governed local NA.
# Usage: record_tutorial.sh <empty-workdir> <this-folder> <out.txt>
set -u
W="$1"; T="$2"; OUT="$3"
# genesis-mesh, node, go and dotnet must be on PATH. Set up each program once, as docs/tutorial.md shows:
#   ts/: npm init -y && npm pkg set type=module && npm install genesis-mesh-sdk
#   go/: go mod init tutorial && go get github.com/GenesisMeshLabs/sdk-go/genesismesh@latest
#   cs/: dotnet new console --framework net8.0 && dotnet add package genesismesh-sdk-dotnet
# Render: python ../render_terminal_gif.py out.txt genesis-mesh-sdk-tutorial.gif --title "Genesis Mesh -- SDK Tutorial"
rm -rf "$W" && mkdir -p "$W" && cd "$W"
: > "$OUT"
say() { printf '%s\n' "$*" >> "$OUT"; }
run() { # run <display> <style-filter> -- cmd...
  local disp="$1"; shift
  say "\$ $disp"
  "$@" 2>&1 | tr -d '\r' | while IFS= read -r l; do
    case "$l" in
      *invalid_verdict*) say "!no $l";;
      OK*|*'"status":"ok"'*|true|True|accepted) say "!ok $l";;
      "") ;;
      *) say "$l";;
    esac
  done
}
say "==> Set up a governed local NA (port 18455)"
run "genesis-mesh init --config local/genesis-mesh.toml --home local/.genesis-mesh --network-name MY-PROJECT-DEV --na-endpoint http://127.0.0.1:18455 --na-port 18455 --env-file local/na.env" \
  genesis-mesh init --config local/genesis-mesh.toml --home local/.genesis-mesh --network-name MY-PROJECT-DEV --na-endpoint http://127.0.0.1:18455 --na-port 18455 --env-file local/na.env
run "genesis-mesh keygen operator --output local/.genesis-mesh/keys/controller --key-id controller --tier standard --env-file local/na.env" \
  genesis-mesh keygen operator --output local/.genesis-mesh/keys/controller --key-id controller --tier standard --env-file local/na.env
say "==> Start the NA"
say "\$ genesis-mesh na start --env-file local/na.env &"
genesis-mesh na start --env-file local/na.env > na.log 2>&1 &
NAPID=$!
for i in $(seq 1 30); do curl -s -m 1 http://127.0.0.1:18455/healthz >/dev/null && break; sleep 1; done
grep -E '^(Settings|  )' na.log | tr -d '\r' | while IFS= read -r l; do say "$l"; done
run "curl http://127.0.0.1:18455/healthz" curl -s http://127.0.0.1:18455/healthz
say "==> Export the controller key (standard tier)"
say "\$ export GM_NA_URL=http://127.0.0.1:18455 GM_ADMIN_KEY_ID=controller"
say "\$ export GM_ADMIN_KEY_B64=\$(grep -v '^#' local/.genesis-mesh/keys/controller.key)"
export GM_NA_URL=http://127.0.0.1:18455 GM_ADMIN_KEY_ID=controller
export GM_ADMIN_KEY_B64=$(grep -v '^#' local/.genesis-mesh/keys/controller.key | grep -v '^$' | head -1)
say "==> TypeScript: build, verify, refuse a bad verdict"
( cd "$T/ts" && run "node tutorial.ts" node tutorial.ts )
say "==> Go"
( cd "$T/go" && run "go run ." go run . )
say "==> C#"
( cd "$T/cs" && run "dotnet run -c Release" dotnet run -c Release )
kill $NAPID 2>/dev/null
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 18455 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }" >/dev/null 2>&1
