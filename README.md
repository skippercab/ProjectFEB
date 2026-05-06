# Rider

**A magical bridge from plan to performance.**

Rider is a macOS desktop app that connects Planning Center and Ableton Live. Give it a service plan, point it at your Multitracks stems folder, and it builds a complete, ready-to-open Ableton setlist — grouped tracks, click clips, markers, routing, and all — in seconds.

---

## Download & Install (macOS — no coding required)

> **This is the only section you need if you just want to run Rider.**

### Step 1 — Download the DMG

1. Go to **[github.com/skippercab/ProjectFEB/releases](https://github.com/skippercab/ProjectFEB/releases)**
2. Under the latest release, click **`Rider-2.0.0.dmg`** to download it.

### Step 2 — Install the app

1. Open the downloaded **`Rider-2.0.0.dmg`** file (double-click it in your Downloads folder).
2. A window will appear showing the Rider icon and an Applications folder.
3. **Drag the Rider icon onto the Applications folder.**
4. Once copied, eject the DMG (drag it to the Trash or press ⌘E).

### Step 3 — Open Rider for the first time

Because Rider isn't distributed through the Mac App Store, macOS will show a security warning the first time.

1. Open your **Applications** folder (Finder → Go → Applications).
2. **Right-click** (or Control-click) on **Rider** and choose **Open**.
3. Click **Open** in the dialog that appears.

After that first launch you can open Rider normally by double-clicking it or keeping it in your Dock.

---

## First-time setup

When Rider opens for the first time it will ask you to configure a few things. You only need to do this once.

### Planning Center API credentials

Rider needs read access to your Planning Center account.

1. Go to [api.planningcenteronline.com/personal_access_tokens](https://api.planningcenteronline.com/personal_access_tokens) and sign in.
2. Create a new **Personal Access Token** in the upper right corner.
3. Copy the **Application ID** and **Secret** into Rider's Settings screen.

### Multitracks stems folder

Point Rider at the folder on your computer where your downloaded Multitracks stems live. Rider supports all common folder layouts (flat, `MultiTracks/`, `Samples/Imported/`, etc.).

### Ableton template

Point Rider at the `.als` template file you want every setlist to be built from. Rider copies this file and fills it in — your original is never modified.

### Output folder

Choose where Rider should save the finished Ableton project folders.

---

## How to generate a setlist

1. Launch Rider.
2. Choose your **Service Type** and **Plan date** from the dropdowns.
3. Rider fetches the song list from Planning Center and searches your stems folder.
4. Review the matched stems. Resolve any unknowns if prompted (Rider remembers your choices for next time).
5. Click **Generate**. Rider builds the `.als` file and opens the output folder when done.
6. Open the project in Ableton Live.

---

## What Rider builds

- **Song markers** at the correct beat positions — including sets with more than 4 songs
- **Click track clips** with the correct meter (4/4 or 6/8) and song color for every song
- **Grouped track hierarchy** that mirrors your configured return bus layout — if you have 3 return buses (Perc / Bass / Lead) you get 3 sub-groups per song; if you have 6, you get 6
- **Stem routing on the group**, not on individual tracks — move a guitar from Strings to Lead in Ableton and it automatically inherits the new routing
- **Lead Guitar placeholder** in every song so the slot is always visible even when no stems are present
- **Regen exports** use numbered suffixes (`- Regen 1`, `- Regen 2`, …) so older sets are never overwritten

---

## Return bus layout

Rider's track grouping adapts to however you have your return buses configured in Settings. The default layout is:

| Slot | Name | Handles |
|------|------|---------|
| A | Perc | Drums, loops, percussion |
| B | Bass | Bass |
| C | Lead | Lead lines, guitars |
| D | Strings | Strings, orchestra, guitars |
| E | Keys | Keys, piano, synth, pads |
| F | Vocals | Lead vocal, BGVs |
| G | Click | Click track |
| H | Guide | Guide / scratch track |

You can add, remove, or rename buses in Settings and Rider will build the session to match.

---

## Rebuilding from source (developers only)

```bash
git clone https://github.com/skippercab/ProjectFEB.git
cd ProjectFEB
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Rebuild the distributable app

```bash
# Build the .app
source .venv_build/bin/activate
pyinstaller --clean --noconfirm Rider.spec

# Package as DMG
dmgbuild -s dmg_settings.py -D app=dist/Rider.app "Rider" dist/Rider-2.0.0.dmg
```

Or run the convenience script which does both and offers to install to `/Applications`:

```bash
bash build_app.sh
```

---

## Troubleshooting

**"Rider is damaged and can't be opened"**
Open Terminal and run:
```
xattr -dr com.apple.quarantine /Applications/Rider.app
```
Then try opening again.

**No service plans found**
Verify your Planning Center API credentials in Settings and confirm the selected service type has plans.

**No stems found for a song**
Check that the song folder exists inside your configured stems folder and that the folder name is close to the Planning Center song title. Rider uses fuzzy matching but a very different name may not match.

**Generated set looks wrong / I already generated this plan**
Rider auto-increments the filename (`- Regen 1`, `- Regen 2`, …). Open the latest Regen file in your output folder.

**App opens but shows a blank window**
Check `output.log` in the ProjectFEB source folder (if running from source) for error details.

---

## Project layout

```
src/projectfeb/
  core/        configuration, data models
  services/    Ableton generation, Planning Center API, stem discovery
  ui/          CustomTkinter interface
config/        settings.json, preferences.json
template/      base Ableton template
img/           app icon and DMG assets
font/          Gotham Narrow typeface
```

---

## License

MIT License.