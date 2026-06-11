#!/usr/bin/env bash
# Build Home Services.app from the Swift package.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MENUBAR_DIR="$ROOT/menubar"
BUILD_DIR="$MENUBAR_DIR/.build"
APP_DIR="$MENUBAR_DIR/dist/Home Services.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"

cd "$MENUBAR_DIR"
swift build -c release

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR"
cp "$BUILD_DIR/release/HomeServicesMenuBar" "$MACOS_DIR/HomeServicesMenuBar"
cp "$MENUBAR_DIR/Info.plist" "$CONTENTS_DIR/Info.plist"
codesign --force --sign - "$APP_DIR" >/dev/null

echo "$APP_DIR"
