"""
PyInstaller runtime hook for Rider.
Ensures all resource lookups point to the correct location whether
the app is running from source or from the bundled .app.
"""
import sys
import os
from pathlib import Path


def _get_bundle_dir() -> Path:
    """Return the root resources directory inside the bundle (or the project root when running from source)."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    # Running from source
    return Path(__file__).parent


_bundle_dir = _get_bundle_dir()

# ── Patch config / asset paths so the app finds its files ────────────────────
# Set an env var that the app can use to locate bundled resources.
os.environ.setdefault('RIDER_BUNDLE_DIR', str(_bundle_dir))

# Ensure the bundled config directory is available as a fallback.
bundled_config = _bundle_dir / 'config'
if bundled_config.exists():
    os.environ.setdefault('RIDER_DEFAULT_CONFIG_DIR', str(bundled_config))

# Make sure tkinter can find its Tcl/Tk libraries inside the bundle.
tcl_lib = _bundle_dir / '_tcl_data'
tk_lib = _bundle_dir / '_tk_data'
if tcl_lib.exists():
    os.environ['TCL_LIBRARY'] = str(tcl_lib)
if tk_lib.exists():
    os.environ['TK_LIBRARY'] = str(tk_lib)
