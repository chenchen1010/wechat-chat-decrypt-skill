#!/bin/bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$SCRIPT_DIR/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
DESTINATION="$CODEX_HOME/skills/wechat-chat-decrypt"

mkdir -p "$CODEX_HOME/skills"

if [[ "$SOURCE" != "$DESTINATION" ]]; then
  STAGING="$(mktemp -d "$CODEX_HOME/skills/.wechat-chat-decrypt.XXXXXX")"
  rsync -a \
    --exclude '.git' \
    --exclude '*.zip' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'vendor/wechat-cli/build' \
    --exclude '.DS_Store' \
    "$SOURCE/" "$STAGING/"
  if [[ -e "$DESTINATION" ]]; then
    BACKUP="$CODEX_HOME/skills/wechat-chat-decrypt.backup.$(date +%Y%m%d-%H%M%S)"
    mv "$DESTINATION" "$BACKUP"
  fi
  mv "$STAGING" "$DESTINATION"
fi

chmod 755 "$DESTINATION/scripts/bootstrap.sh" \
  "$DESTINATION/scripts/install-skill.sh" \
  "$DESTINATION/scripts/package-skill.sh" \
  "$DESTINATION/scripts/wechat-cli-safe" \
  "$DESTINATION/scripts/wechat_decrypt.py"

"$DESTINATION/scripts/bootstrap.sh"

printf '{"ok":true,"skill":"%s"}\n' "$DESTINATION"
