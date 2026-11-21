#!/bin/sh
# Optima AI Browser installer for macOS and Linux.
#   sh install.sh            normal install, then the first-run window
#   sh install.sh --cli      first run in the terminal instead of a window
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
OPTIMA_HOME="${OPTIMA_HOME:-$HOME/.optima}"
mkdir -p "$OPTIMA_HOME"

# Copy the program into ~/.optima so it keeps working if this folder moves.
APP="$OPTIMA_HOME/app"
rm -rf "$APP"
mkdir -p "$APP"
cp -R "$HERE/src" "$APP/"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +
export PYTHONPATH="$APP/src"

say() { printf '\033[1;36m==>\033[0m %s\n' "$1"; }

case "$(uname -s)" in
  Darwin)
    say "macOS: building the native engine (system WebKit, nothing downloaded)"
    if ! command -v swiftc >/dev/null 2>&1; then
      echo "The Swift compiler is missing. Run: xcode-select --install  (then run this script again)"
      exit 1
    fi
    sh "$HERE/src/optima/macos/build.sh" "$OPTIMA_HOME/engine" >/dev/null
    # Double-click it to browse yourself (e.g. log in to your sites).
    mkdir -p "$HOME/Applications"
    ln -sfn "$OPTIMA_HOME/engine/Optima.app" "$HOME/Applications/Optima AI Browser.app"
    PY="$(command -v python3)"
    ;;
  Linux)
    say "Linux: preparing Python + Playwright in $OPTIMA_HOME/venv"
    command -v python3 >/dev/null 2>&1 || { echo "python3 is required"; exit 1; }
    python3 -m venv "$OPTIMA_HOME/venv"
    PY="$OPTIMA_HOME/venv/bin/python"
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r "$HERE/requirements.txt"
    if command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1; then
      say "Using your installed Google Chrome"
    else
      say "Downloading Playwright's Chromium (one time)"
      "$PY" -m playwright install chromium
      echo "If the browser fails to start, install its system libraries with:"
      echo "  sudo $PY -m playwright install-deps chromium"
    fi
    ;;
  *)
    echo "Unsupported system. On Windows run install.ps1 in PowerShell."
    exit 1
    ;;
esac

say "First run"
"$PY" -m optima setup "$@"
