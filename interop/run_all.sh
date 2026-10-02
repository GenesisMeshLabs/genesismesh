#!/usr/bin/env bash
# Run the cross-language interoperability scenario end to end:
# start a local Network Authority, run the Python, Go, TypeScript and C# legs
# in order, and fail if any two implementations disagree.
#
# SDK checkouts default to siblings of this repository; override with
# GM_SDK_GO_DIR, GM_SDK_TS_DIR and GM_SDK_DOTNET_DIR. PYTHON, GO, NODE, NPM and
# DOTNET select the toolchains.
#
#   interop/run_all.sh --published 0.62.0
#
# runs every leg from the released packages instead: genesis-mesh from PyPI
# (in a fresh virtualenv), genesis-mesh-sdk from npm, genesismesh-sdk-dotnet
# from NuGet and sdk-go from the Go module proxy, all at that version.
# GM_PUBLISHED_CORE=source keeps the core from this checkout (released SDKs
# against an unreleased core).
set -euo pipefail

PUBLISHED=""
if [[ "${1:-}" == "--published" ]]; then
  PUBLISHED="${2:?--published needs a version}"
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
if [[ -z "$PUBLISHED" ]]; then
  GM_SDK_GO_DIR="$(cd "${GM_SDK_GO_DIR:-$ROOT/../sdk-go}" && pwd)"
  GM_SDK_TS_DIR="$(cd "${GM_SDK_TS_DIR:-$ROOT/../sdk-typescript}" && pwd)"
  GM_SDK_DOTNET_DIR="$(cd "${GM_SDK_DOTNET_DIR:-$ROOT/../sdk-dotnet}" && pwd)"
fi
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then PYTHON="$ROOT/.venv/bin/python"; else PYTHON=python3; fi
fi
GO="${GO:-go}"
NODE="${NODE:-node}"
NPM="${NPM:-npm}"
DOTNET="${DOTNET:-dotnet}"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1

FIXTURES="$HERE/fixtures"
WORK="$(mktemp -d)"
NA_PID=""
cleanup() {
  if [[ -n "$NA_PID" ]] && kill -0 "$NA_PID" 2>/dev/null; then
    kill "$NA_PID"
    wait "$NA_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

step() { printf '\n== %s ==\n' "$1"; }

rm -rf "$FIXTURES"
mkdir -p "$FIXTURES/results"

if [[ -n "$PUBLISHED" && "${GM_PUBLISHED_CORE:-pypi}" != "source" ]]; then
  step "Installing the released genesis-mesh $PUBLISHED from PyPI"
  "$PYTHON" -m venv "$WORK/venv"
  PYTHON="$WORK/venv/bin/python"
  "$PYTHON" -m pip install -q "genesis-mesh==$PUBLISHED"
  "$PYTHON" -c "import genesis_mesh; assert genesis_mesh.__version__ == '$PUBLISHED', genesis_mesh.__version__"
fi

step "Network Authority"
"$PYTHON" "$HERE/python/na_server.py" >"$WORK/na.log" 2>&1 &
NA_PID=$!
for _ in $(seq 1 120); do
  [[ -s "$FIXTURES/na.json" ]] && break
  if ! kill -0 "$NA_PID" 2>/dev/null; then cat "$WORK/na.log"; exit 1; fi
  sleep 0.25
done
[[ -s "$FIXTURES/na.json" ]] || { echo "the Network Authority did not start"; cat "$WORK/na.log"; exit 1; }
cat "$WORK/na.log"

step "Leg 1: Python (agreement, boundary decisions, license policy)"
"$PYTHON" "$HERE/python/setup.py"

if [[ -n "$PUBLISHED" ]]; then
  step "Leg 2: Go verifier (github.com/GenesisMeshLabs/sdk-go@v$PUBLISHED)"
  cp "$HERE/go/go.mod" "$WORK/go.mod"
  cp "$HERE/go/go.sum" "$WORK/go.sum"
  (cd "$HERE/go" && "$GO" mod edit -modfile="$WORK/go.mod" -dropreplace=github.com/GenesisMeshLabs/sdk-go \
    -require="github.com/GenesisMeshLabs/sdk-go@v$PUBLISHED" \
    && GOFLAGS=-mod=mod "$GO" run -modfile="$WORK/go.mod" . "$FIXTURES")
else
  step "Leg 2: Go verifier ($GM_SDK_GO_DIR)"
  cp "$HERE/go/go.mod" "$WORK/go.mod"
  cp "$HERE/go/go.sum" "$WORK/go.sum"
  (cd "$HERE/go" && "$GO" mod edit -modfile="$WORK/go.mod" -replace="github.com/GenesisMeshLabs/sdk-go=$GM_SDK_GO_DIR" \
    && "$GO" run -modfile="$WORK/go.mod" . "$FIXTURES")
fi

if [[ -n "$PUBLISHED" ]]; then
  step "Leg 3: TypeScript SDK (genesis-mesh-sdk@$PUBLISHED from npm)"
  (cd "$HERE/typescript" && "$NPM" install --no-save --no-package-lock --no-audit --no-fund "genesis-mesh-sdk@$PUBLISHED" >/dev/null \
    && "$NODE" --experimental-strip-types --no-warnings submit_intent.ts "$FIXTURES")
else
  step "Leg 3: TypeScript SDK ($GM_SDK_TS_DIR)"
  (cd "$GM_SDK_TS_DIR" && { [[ -d node_modules ]] || "$NPM" ci --no-audit --no-fund; } && "$NPM" run build >/dev/null \
    && "$NPM" pack --silent --pack-destination "$WORK" >/dev/null)
  (cd "$HERE/typescript" && "$NPM" install --no-save --no-package-lock --no-audit --no-fund "$WORK"/genesis-mesh-sdk-*.tgz >/dev/null \
    && "$NODE" --experimental-strip-types --no-warnings submit_intent.ts "$FIXTURES")
fi

if [[ -n "$PUBLISHED" ]]; then
  step "Leg 4: C# SDK (genesismesh-sdk-dotnet $PUBLISHED from NuGet)"
  "$DOTNET" run --project "$HERE/csharp/VerifyIntent" -c Release -p:GmSdkDotnetVersion="$PUBLISHED" -- "$FIXTURES"
else
  step "Leg 4: C# SDK ($GM_SDK_DOTNET_DIR)"
  "$DOTNET" run --project "$HERE/csharp/VerifyIntent" -c Release -p:GmSdkDotnetDir="$GM_SDK_DOTNET_DIR" -- "$FIXTURES"
fi

step "All implementations agree"
"$PYTHON" "$HERE/assert_results.py"
