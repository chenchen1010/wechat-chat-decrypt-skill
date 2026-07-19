#!/bin/bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_ROOT="${WECHAT_CHAT_DECRYPT_RUNTIME:-$HOME/.local/share/wechat-chat-decrypt}"
VENV="$RUNTIME_ROOT/venv"

find_python() {
  local candidate
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidate="$PYTHON_BIN"
    if "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [[ -z "$PYTHON" ]]; then
  printf '%s\n' 'Python 3.10 or newer is required.' >&2
  printf '%s\n' 'Install Python first, then rerun scripts/bootstrap.sh.' >&2
  exit 1
fi

mkdir -p "$RUNTIME_ROOT"
chmod 700 "$RUNTIME_ROOT"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet \
  "$SKILL_ROOT/vendor/wechat-cli"

"$VENV/bin/python" - <<'PY'
from Crypto.Cipher import AES
import zstandard
import wechat_cli

assert AES.block_size == 16
assert zstandard.__version__
assert wechat_cli.__file__
PY

printf '{"ok":true,"runtime":"%s","wechat_cli":"%s"}\n' \
  "$RUNTIME_ROOT" "$VENV/bin/wechat-cli"
