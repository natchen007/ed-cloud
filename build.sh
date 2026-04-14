#!/usr/bin/env bash
set -e

echo "=== EDCloud Builder ==="

cd "$(dirname "$0")"

if ! python3 -m PyInstaller --version > /dev/null 2>&1; then
    echo "PyInstaller non trouve. Installation..."
    pip3 install pyinstaller
fi

python3 -m PyInstaller EDCloud.spec --distpath dist --noconfirm

echo ""
echo "=== Build termine : dist/EDCloud ==="
