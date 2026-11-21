#!/bin/sh
# Builds the native macOS engine with the Swift compiler that comes with
# Xcode or the Command Line Tools. Output: build/Optima.app
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/build}"
APP="$OUT/Optima.app"

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc not found. Install the Command Line Tools with: xcode-select --install" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
if [ -f "$HERE/AppIcon.icns" ]; then cp "$HERE/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"; fi

swiftc -O -o "$APP/Contents/MacOS/OptimaEngine" "$HERE/main.swift" \
  -framework Cocoa -framework WebKit

# Ad-hoc signature: enough to run an app you built yourself on your own Mac.
codesign --force --sign - "$APP" >/dev/null 2>&1 || true

echo "$APP"
