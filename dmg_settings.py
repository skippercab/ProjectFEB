# dmgbuild settings for Rider.app installer
# Run with:
#   source .venv_build/bin/activate
#   dmgbuild -s dmg_settings.py "Rider" dist/Rider-2.0.0.dmg

import os

# ── Basics ────────────────────────────────────────────────────────────────────
application = defines.get('app', 'dist/Rider.app')
appname = os.path.basename(application)

# ── DMG layout ────────────────────────────────────────────────────────────────
format = defines.get('format', 'UDZO')
compression_level = 9
size = None   # auto-size

files = [application]
symlinks = {'Applications': '/Applications'}

# ── Window appearance ─────────────────────────────────────────────────────────
# background path — stored in hidden .background/ folder inside the DMG
background = 'img/dmg_background.png'

# Window rect: position on screen, then (width, height) of the content area only
# (excludes the Finder toolbar — so the background fills the full content area)
window_rect = ((200, 120), (660, 420))

# Icon size and label styling
icon_size = 128
text_size  = 12

# Icon positions (logical points = @2x pixel coords ÷ 2, origin = top-left of content area)
# Rider.app center: pixel 310,390 → logical 155,195
# Applications center: pixel 1010,390 → logical 505,195
icon_locations = {
    appname:        (155, 195),
    'Applications': (505, 195),
}
