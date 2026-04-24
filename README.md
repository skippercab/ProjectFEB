# Rider

Rider: The Final Editing Bridge is a desktop app that turns Planning Center service plans and Multitracks stems into ready-to-open Ableton Live setlists. It pulls the songs for a service, finds the matching audio stems, builds grouped tracks from your template, and generates marker clips and timing data so the set is usable with minimal manual cleanup.

## Features

- Planning Center Online plan and song import
- Multitracks stem discovery with fuzzy song matching
- Unknown-stem review and remembered stem-type overrides
- Ableton `.als` generation from a user-supplied template
- Guide-aware marker clip generation with song-structure alignment
- Meter-aware behavior for 4/4 and 6/8 songs
- Regenerated exports use numbered `Regen` filenames instead of overwriting older sets
- Generated tracks inside groups are ordered naturally by stem name

## Requirements

- Python 3.12 recommended
- A Planning Center account with API credentials
- A local Multitracks stems folder
- An Ableton Live template `.als` file

## Installation

```bash
git clone <repository-url>
cd ProjectFEB
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
```

You can also run the app with an existing compatible virtual environment if you already have one configured.

## Configuration

Rider reads its settings from `config/settings.json`.

Example:

```json
{
   "planning_center": {
      "application_id": "your_app_id",
      "secret": "your_secret"
   },
   "multitracks": {
      "stems_folder": "/path/to/your/stems"
   },
   "ableton": {
      "template_path": "/path/to/your/template.als",
      "output_folder": "/path/to/output/folder"
   }
}
```

You will need:

- Planning Center API credentials from https://api.planningcenteronline.com/oauth/applications
- A valid local path to your Multitracks stems directory
- A valid local path to the Ableton template you want to duplicate and populate

## Usage

1. Launch the app.
2. Select a Planning Center folder, service type, and plan.
3. Review the matched stems.
4. Resolve any unknown stems if prompted.
5. Generate the setlist.

Run it with either of these:

```bash
python run.py
```

```bash
python -m projectfeb
```

## Output

Generated Ableton sets are written to the configured `output_folder`.

- The first export uses the base service name and date.
- Later exports use ` - Regen N` suffixes.
- Guide tracks and marker clips are generated from the matched stems and song arrangements.
- Audio tracks are created under grouped song folders using the routing structure from the template.

## Stem Discovery

Rider supports several common Multitracks folder structures, including direct song folders, `MultiTracks/`, and `Samples/Imported/` layouts.

It categorizes stems into the template groups used by the app:

- `perc`
- `bass`
- `leads`
- `strings`
- `keys`
- `vocals`
- `guide`

Song titles are normalized before matching, so common folder modifiers like key, tempo, and switch suffixes do not prevent a match.

## Development

Run tests:

```bash
pytest
```

Common local quality commands:

```bash
black src/
flake8 src/
mypy src/
```

Build the package:

```bash
python setup.py build
```

## Troubleshooting

**No service plans found**

- Verify your Planning Center credentials.
- Confirm the selected folder and service type are correct.

**No stems found**

- Verify the `stems_folder` path.
- Confirm the song folders and filenames are present locally.
- Review any unknown-stem prompts and save overrides when needed.

**Template file not found**

- Verify `template_path` points to an existing `.als` file.
- Confirm the file is readable from this machine.

**Generated set looks stale**

- Check the configured output folder for the newest `Regen` export.

## Project Layout

```text
src/projectfeb/
   core/
   services/
   ui/
```

## License

MIT License.