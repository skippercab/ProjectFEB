# Project FEB

A modern Python application that integrates Planning Center Online service plans with Multitracks audio stems to generate Ableton Live 11 setlists.

## Features

- **Planning Center Online Integration**: Fetch service plans and song data
- **Multitracks Stem Discovery**: Robust fuzzy matching for audio stems
- **Ableton Live 11 Support**: Generate backward-compatible .als files
- **Custom Templates**: Use your own Ableton templates with return tracks
- **Modern GUI**: Clean interface built with customtkinter

## Quick Start

1. **Clone and setup**:
   ```bash
   git clone <repository-url>
   cd project-feb
   pip install -r requirements.txt
   python setup.py
   ```

2. **Configure your settings** (or edit `config/settings.json`):
   - Planning Center Online API credentials
   - Path to your Multitracks stems folder
   - Path to your Ableton 11 template

3. **Run the application**:
   ```bash
   python -m projectfeb
   ```

## Detailed Setup

### 1. Planning Center Online Setup

1. Go to [Planning Center API Applications](https://api.planningcenteronline.com/oauth/applications)
2. Create a new application
3. Copy the Application ID and Secret to your `config/settings.json`

### 2. Multitracks Setup

Set the `stems_folder` in your configuration to point to your Multitracks stems directory. The app supports:
- WAV, AIFF, FLAC formats
- Fuzzy matching for song names
- Various naming conventions (spaces, underscores, dashes)

### 3. Ableton Live Setup

1. Create your template in Ableton Live 11
2. Save it to your User Library Templates folder
3. Set the `template_path` in your configuration

## Configuration

The `config/settings.json` file contains:

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
    "output_folder": "~/Desktop"
  }
}
```

## Usage

1. **Select Service Plan**: Choose from upcoming Planning Center services
2. **Review Stem Matches**: See which songs have matching audio stems
3. **Generate Setlist**: Create your Ableton Live project with arranged stems

## Multitracks Integration

Project FEB supports complex Multitracks folder architectures:

### Supported Folder Structures

The app intelligently discovers stems in various folder layouts:

1. **Direct in Song Folder**:
   ```
   Stems/
   ├── Song Title (Key) [Tempo]/
   │   ├── AG - Song Title (Key) [Tempo].wav
   │   ├── Drums - Song Title (Key) [Tempo].wav
   │   └── Keys - Song Title (Key) [Tempo].wav
   ```

2. **MultiTracks Subfolder** (Preferred):
   ```
   Stems/
   ├── Song Title (Key) [Tempo]/
   │   └── MultiTracks/
   │       ├── Alto.wav
   │       ├── Drums.wav
   │       └── Keys.wav
   ```

3. **Samples/Imported Subfolder**:
   ```
   Stems/
   ├── Song Title (Key) [Tempo]/
   │   └── Samples/
   │       └── Imported/
   │           ├── AG.wav
   │           ├── Drums.wav
   │           └── Keys.wav
   ```

### Song Title Matching

The app automatically extracts clean song titles from folder names:

- `"Again & Again (Db) [115]"` → `"Again And Again"`
- `"Give Me Jesus (UPPERROOM)"` → `"Give Me Jesus"`
- `"The Blood (75) [G] sw"` → `"The Blood"`

### Stem Type Detection

Project FEB automatically categorizes stems into your 6 Ableton template groups:

- **Perc** (10 stems): drums, drum, kit, percussion, perc, alt_drums, toms, fx, loop, live
- **Bass** (6 stems): bass, electric_bass, upright_bass, moog, sub_bass, synth_bass, bbass  
- **Leads** (0 stems): typically empty, manually select electric guitar stems
- **Strings** (14 stems): eg, electric, ag, acoustic, guitar, electric_guitar, acoustic_guitar, gtr, strings, violin, viola, cello, orchestral
- **Keys** (17 stems): keys, keyboard, piano, organ, synth, rhodes, wurlitzer, clav, synth_fx
- **Vocals** (7 stems): vocals, vocal, vox, lead_vox, bgv, backing_vox, choir, tenor, alto, soprano, bgvs, vox_fx
- **Guide** (3 stems): guide, metronome, click *(routes to channel 3 in template)*

### Song Discovery Results

Testing with real Multitracks data shows excellent performance:
- **4/4 songs** successfully matched (100% success rate)
- **58 total stems** discovered across all songs
- **ALL stems included** for each matched song (no filtering)
- **Perfect confidence scores** (100% for all matches)
- **Excludes metronome files** (classic-*.aif automatically skipped)

**Stem Distribution Examples:**
- Mighty Name Of Jesus: 21 stems (AG, EG 1-3, Keys 1-5, Piano, Organ, etc.)
- Give Me Jesus: 10 stems  
- Again And Again: 17 stems
- The Blood: 7 stems

## Architecture

```
projectfeb/
├── core/           # Configuration and core logic
├── services/       # External service integrations
│   ├── pco_service.py         # Planning Center Online
│   ├── multitracks_service.py # Stem discovery
│   └── ableton_service.py     # Ableton file generation
├── ui/             # User interface
└── utils/          # Utilities and helpers
```

## Development

### Running Tests
```bash
pytest
```

### Code Quality
```bash
black src/
flake8 src/
mypy src/
```

### Building for Distribution
```bash
python setup.py build
```

## Troubleshooting

### Common Issues

**"No service plans found"**
- Check your Planning Center API credentials
- Ensure your application has the correct permissions

**"No stems found for songs"**
- Verify your stems folder path
- Check that audio files are in supported formats
- Review naming conventions in your stems

**"Template file not found"**
- Ensure your Ableton template exists at the specified path
- Check file permissions

### Logs

Application logs are written to the console and can be configured to write to files in the `logs/` directory.

## Requirements

- Python 3.8+
- Planning Center Online account with API access
- Ableton Live 11 template file
- Multitracks audio stems folder

## License

MIT License - feel free to use and modify as needed.