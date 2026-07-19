#!/bin/bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$SCRIPT_DIR/.." && pwd)"
PARENT="$(cd "$SOURCE/.." && pwd)"
DEFAULT_OUTPUT="$PARENT/wechat-chat-decrypt-skill.zip"
OUTPUT="${1:-$DEFAULT_OUTPUT}"

case "$OUTPUT" in
  /*) ;;
  *) OUTPUT="$PWD/$OUTPUT" ;;
esac
OUTPUT="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT")"

case "$OUTPUT" in
  "$SOURCE"/*)
    printf '%s\n' 'Output zip must be outside the skill directory.' >&2
    exit 1
    ;;
esac

TEMP_DIR="$(mktemp -d /private/tmp/wechat-chat-decrypt-package.XXXXXX)"
TEMP_ZIP="$TEMP_DIR/wechat-chat-decrypt-skill.zip"
trap 'find "$TEMP_DIR" -depth -delete 2>/dev/null || true' EXIT HUP INT TERM

(
  cd "$PARENT"
  zip -qr "$TEMP_ZIP" "$(basename "$SOURCE")" \
    -x '*/.git/*' \
    -x '*/__pycache__/*' \
    -x '*.pyc' \
    -x '*/vendor/wechat-cli/build/*' \
    -x '*/.DS_Store' \
    -x '*.zip'
)

mkdir -p "$(dirname "$OUTPUT")"
mv "$TEMP_ZIP" "$OUTPUT"
chmod 600 "$OUTPUT"
printf '{"ok":true,"package":"%s"}\n' "$OUTPUT"
