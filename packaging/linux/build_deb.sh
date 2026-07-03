#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${SNAPMATCH_VERSION:-1.0.4}"
ARCH="${SNAPMATCH_ARCH:-amd64}"
APP_BINARY="$ROOT_DIR/dist/SnapMatch"
PACKAGE_ROOT="$ROOT_DIR/dist/deb/snapmatch_${VERSION}_${ARCH}"
OUTPUT_DEB="$ROOT_DIR/dist/SnapMatch_${VERSION}_${ARCH}.deb"

if [ ! -f "$APP_BINARY" ]; then
  echo "Build failed: $APP_BINARY was not found."
  exit 1
fi

rm -rf "$PACKAGE_ROOT" "$OUTPUT_DEB"

install -D -m 0755 "$APP_BINARY" "$PACKAGE_ROOT/opt/snapmatch/SnapMatch"
install -D -m 0644 "$ROOT_DIR/LICENSE" "$PACKAGE_ROOT/usr/share/doc/snapmatch/copyright"
install -D -m 0644 "$ROOT_DIR/packaging/linux/snapmatch.desktop" "$PACKAGE_ROOT/usr/share/applications/snapmatch.desktop"

if [ -f "$ROOT_DIR/assets/icon3.png" ]; then
  install -D -m 0644 "$ROOT_DIR/assets/icon3.png" "$PACKAGE_ROOT/usr/share/icons/hicolor/256x256/apps/snapmatch.png"
fi

mkdir -p "$PACKAGE_ROOT/usr/local/bin"
ln -s /opt/snapmatch/SnapMatch "$PACKAGE_ROOT/usr/local/bin/snapmatch"

mkdir -p "$PACKAGE_ROOT/DEBIAN"
cat > "$PACKAGE_ROOT/DEBIAN/control" <<CONTROL
Package: snapmatch
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: WETQV
Depends: ffmpeg, libc6, libegl1, libxcb-cursor0, libxkbcommon-x11-0
Homepage: https://github.com/WETQV/SnapMatch
Description: Desktop Telegram bot manager with AI models and MCP tools
 SnapMatch is a desktop application for managing a Telegram bot with AI models,
 MCP tools, voice processing, message history and secretary mode.
CONTROL

dpkg-deb --build --root-owner-group "$PACKAGE_ROOT" "$OUTPUT_DEB"
echo "Created $OUTPUT_DEB"
