#!/bin/bash
set -e
mkdir -p dist

# Compute a meaningful version string so the « connecté · macos vX.Y.Z »
# badge in the Settings UI reflects the actual code that's running.
# Format: « <base>+<git-short-sha>[+dirty] » — base comes from the
# package-level `var version` in main.go, git short sha is appended so
# we can tell at a glance which commit a running daemon was built from.
BASE_VERSION=$(awk -F\" '/^var version =/ { print $2; exit }' main.go)
GIT_SHA=$(git -C "$(dirname "$0")" rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=""
if [ "$GIT_SHA" != "unknown" ] && ! git -C "$(dirname "$0")" diff --quiet HEAD -- . 2>/dev/null; then
  GIT_DIRTY="+dirty"
fi
FULL_VERSION="${BASE_VERSION}+${GIT_SHA}${GIT_DIRTY}"
LDFLAGS="-s -w -X main.version=${FULL_VERSION}"

echo "Building ELY Desktop ${FULL_VERSION}…"
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags="${LDFLAGS}" -o dist/ely-desktop-linux-amd64 .
CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags="${LDFLAGS}" -o dist/ely-desktop-macos-amd64 .
CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags="${LDFLAGS}" -o dist/ely-desktop-macos-arm64 .
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="${LDFLAGS}" -o dist/ely-desktop-windows-amd64.exe .

# Copy installers into dist/ alongside binaries
cp install.sh  dist/install.sh
cp install.bat dist/install.bat
chmod +x dist/install.sh

echo "Done. Binaries + installers in dist/"
ls -lh dist/
