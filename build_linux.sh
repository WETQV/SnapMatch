#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 --version
python3 -m pip install -r requirements.txt
rm -rf build dist
pyinstaller --noconfirm --clean snapmatch.spec

if [ ! -f "dist/SnapMatch" ]; then
  echo "Build failed: dist/SnapMatch was not created."
  exit 1
fi

echo "Build complete: dist/SnapMatch"
