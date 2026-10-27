#!/usr/bin/env bash
# Cuss-Censor GUI Launcher for macOS and Linux
set -e

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Detect virtual environment if present
if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
elif [ -f "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
else
    PYTHON="python3"
fi

echo "Launching Cuss-Censor GUI using $PYTHON..."
exec "$PYTHON" censor.py gui "$@"
