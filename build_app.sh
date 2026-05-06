#!/usr/bin/env bash
# build_app.sh — Builds Rider.app and installs it to /Applications
set -euo pipefail

APP_NAME="Rider"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"
ICON_SRC="$PROJECT_DIR/img/icon.icns"
BUILD_DIR="$PROJECT_DIR/build"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"

# ── Sanity checks ────────────────────────────────────────────────────────────
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "ERROR: venv not found at $PROJECT_DIR/.venv — run 'python3 -m venv .venv && pip install -r requirements.txt' first."
    exit 1
fi
if [[ ! -f "$ICON_SRC" ]]; then
    echo "ERROR: icon.icns not found at $ICON_SRC"
    exit 1
fi

# ── Create bundle structure ──────────────────────────────────────────────────
echo "→ Building $APP_NAME.app …"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# ── Launcher script ──────────────────────────────────────────────────────────
LAUNCHER="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
# Resolve the real project directory regardless of symlinks or where the app lives.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_CONTENTS="$(dirname "$SCRIPT_DIR")"
APP_BUNDLE="$(dirname "$APP_CONTENTS")"

# The project dir is stored in a companion file so the app can be moved freely.
PROJECT_DIR_FILE="$APP_CONTENTS/Resources/project_dir"
if [[ -f "$PROJECT_DIR_FILE" ]]; then
    PROJECT_DIR="$(cat "$PROJECT_DIR_FILE")"
else
    echo "ERROR: project_dir file missing from Resources." >&2
    osascript -e 'display alert "Rider" message "Could not locate the Rider project folder. Please rebuild the app." as critical'
    exit 1
fi

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"
if [[ ! -f "$VENV_PYTHON" ]]; then
    osascript -e 'display alert "Rider" message "Python environment not found at '"'"'$PROJECT_DIR/.venv'"'"'. Please recreate the venv." as critical'
    exit 1
fi

# Redirect output to a log file so errors are visible if the app silently fails.
LOG="$PROJECT_DIR/output.log"
exec > >(tee -a "$LOG") 2>&1

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR/src:$PYTHONPATH"

exec "$VENV_PYTHON" "$PROJECT_DIR/run.py"
LAUNCHER_EOF

chmod +x "$LAUNCHER"

# ── Store the project directory so the launcher can find it after moving ─────
echo "$PROJECT_DIR" > "$APP_BUNDLE/Contents/Resources/project_dir"

# ── Copy icon ────────────────────────────────────────────────────────────────
cp "$ICON_SRC" "$APP_BUNDLE/Contents/Resources/$APP_NAME.icns"

# ── Info.plist ───────────────────────────────────────────────────────────────
PYTHON_VERSION="$("$VENV_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
cat > "$APP_BUNDLE/Contents/Info.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.projectfeb.rider</string>
    <key>CFBundleVersion</key>
    <string>2.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>
    <string>$APP_NAME</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
    <key>LSUIElement</key>
    <false/>
    <key>CFBundleSupportedPlatforms</key>
    <array>
        <string>MacOSX</string>
    </array>
    <key>NSHumanReadableCopyright</key>
    <string>© 2026 ProjectFEB</string>
</dict>
</plist>
PLIST_EOF

# ── Sign ad-hoc so macOS doesn't quarantine it ───────────────────────────────
echo "→ Signing bundle …"
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null && echo "  (ad-hoc signature applied)" || echo "  (codesign skipped — not critical)"

echo "→ Build complete: $APP_BUNDLE"

# ── Install to /Applications ──────────────────────────────────────────────────
read -rp "Install to /Applications? [y/N] " REPLY
if [[ "$(echo "$REPLY" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
    DEST="/Applications/$APP_NAME.app"
    if [[ -d "$DEST" ]]; then
        echo "→ Removing existing $DEST …"
        rm -rf "$DEST"
    fi
    cp -R "$APP_BUNDLE" "$DEST"
    # Clear quarantine flag just in case
    xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
    echo "✓ Installed to $DEST"
    echo "  You can now open Rider from Launchpad or drag it to the Dock."
else
    echo "  Skipped install. You can find the app at:"
    echo "  $APP_BUNDLE"
fi
