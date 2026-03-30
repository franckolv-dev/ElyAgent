#!/bin/bash
set -e
mkdir -p dist
echo "Building ELY Desktop..."
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags="-s -w" -o dist/ely-desktop-linux-amd64 .
CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags="-s -w" -o dist/ely-desktop-macos-amd64 .
CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags="-s -w" -o dist/ely-desktop-macos-arm64 .
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o dist/ely-desktop-windows-amd64.exe .

# Copy installers into dist/ alongside binaries
cp install.sh  dist/install.sh
cp install.bat dist/install.bat
chmod +x dist/install.sh

echo "Done. Binaries + installers in dist/"
ls -lh dist/
