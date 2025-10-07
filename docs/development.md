# Tempo Development Quick Start

## Development Without Hardware

The `--dev` flag enables development without requiring:

- Raspberry Pi hardware
- Physical e-ink displays
- Root privileges or GPIO access

Works on **macOS**, **Linux**, and **Windows** - no hardware needed!

## Setup

```bash
# 1. Install Chromium (used for taking screenshots of the calendar)

# macOS (using Homebrew with --no-quarantine - macOS's Gatekeeper must be disabled for Chromium to run)
brew install chromium --no-quarantine

# Ubuntu/Debian
sudo apt install chromium-browser

# Windows
# Download and install from https://www.chromium.org/getting-involved/download-chromium

# 2. Clone and setup
git clone https://github.com/<FIXME>/tempo.git
cd Tempo

# 3. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 4. Install dependencies and run
pip install -r install/requirements-dev.txt
python src/tempo.py --dev
```

**That's it!** Open http://localhost:8080 and start developing.