#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
mkdir -p "$DIST_DIR"

ARCHIVE="$DIST_DIR/Samar-Bot.zip"
rm -f "$ARCHIVE"

cd "$ROOT_DIR"
zip -r "$ARCHIVE" \
  . \
  -x ".git/*" \
  -x "dist/*" \
  -x "app/__pycache__/*" \
  -x "*.pyc" \
  -x ".env" \
  -x "data/*" \
  -x "bot.log"

echo "Created: $ARCHIVE"
