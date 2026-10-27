# Contributing to Cuss-Censor

First off, thank you for considering contributing to Cuss-Censor! Contributions from the community help make this tool better for everyone.

---

## 🛠️ Development Setup

### 1. Prerequisites
- **Python 3.10+**
- **FFmpeg** installed and accessible in your system `PATH`:
  - **Windows**: `winget install Gyan.FFmpeg` or download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
  - **macOS**: `brew install ffmpeg`
  - **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install -y ffmpeg`
- **Git**

### 2. Fork and Clone
```bash
# Clone your fork
git clone https://github.com/<your-username>/Music-censor-and-download.git
cd Music-censor-and-download

# Set up upstream remote
git remote add upstream https://github.com/JIYAAD-GldTON/Music-censor-and-download.git
```

### 3. Create a Virtual Environment
```bash
python -m venv .venv

# Activate environment:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (CMD):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e ".[dev]"
```

---

## 🧪 Running Tests

Always ensure existing and new tests pass before submitting a pull request:

```bash
# Run unit tests
python -m unittest discover -s tests

# Or with pytest
pytest tests/
```

---

## 📐 Coding Standards & Guidelines

- **Style**: Follow PEP 8 guidelines. Line length limit is 120 characters.
- **Type Hints**: Annotate function and method arguments and return values wherever practical.
- **Logging**: Use Python's standard `logging` framework rather than arbitrary `print()` statements for diagnostic information.
- **Error Handling**: Avoid silent `except Exception: pass`. Always log warnings or handle exceptions gracefully.
- **Cross-Platform**: Ensure code works across Windows, macOS, and Linux (e.g. use `pathlib.Path`, avoid hardcoded Windows-only API assumptions without fallbacks).

---

## 🔄 Pull Request Workflow

1. **Branch**: Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b fix/audio-export-format
   ```
2. **Commit**: Write clear, concise commit messages explaining *why* a change was made:
   ```bash
   git commit -m "fix(censor): map container format for m4a and opus exports"
   ```
3. **Test**: Run tests locally and verify nothing broke.
4. **Push & Open PR**:
   ```bash
   git push origin fix/audio-export-format
   ```
   Open a Pull Request on GitHub against the `main` branch. Provide a brief summary of changes, motivation, and test results.

---

## 💬 Community & Help

If you encounter a bug, have an idea, or want to discuss improvements, feel free to open an [Issue](https://github.com/JIYAAD-GldTON/Music-censor-and-download/issues).
