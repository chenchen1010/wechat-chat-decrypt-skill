---
name: wechat-chat-decrypt
description: Safely decrypt and query the current user's own local WeChat for Mac chat databases with Codex. Use only when the user explicitly asks to decrypt, search, export, or summarize WeChat chat history stored on their Mac, or asks to diagnose wechat-cli setup, WeChat version compatibility, task_for_pid, key extraction, or temporary plaintext cleanup. This verified workflow targets Apple Silicon macOS and WeChat 4.1.8 build 37261. Never use it to access another person's account, device, backup, or data without explicit authorization.
---

# WeChat Chat Decrypt

Decrypt the current macOS user's local WeChat databases, verify the result without reading messages, and query through a short-lived plaintext cache. The workflow wraps the pinned Apache-2.0 `huohuoer/wechat-cli` snapshot with stricter version, signer, permission, key-handling, and cleanup checks.

## Hard Barriers

Proceed only when all are true:

1. The user explicitly asks to access their own local WeChat data, or data they are authorized to process.
2. The target account is logged in on the same Mac where Codex is running.
3. The work remains local. Do not upload databases, keys, exports, or chat content.

Stop when any are true:

- The request targets someone else's account, device, backup, or credentials without clear authorization.
- A supplied WeChat installer fails bundle ID, Tencent signer, version, build, architecture, or code-signature validation.
- The user declines the required backup before a downgrade.
- The machine is not Apple Silicon macOS. This v1 package has no verified automated path for Intel, Windows, or Linux.

Never print or paste `~/.wechat-cli/all_keys.json`. Never put keys, server passwords, API tokens, personal addresses, or full chat exports in git, project docs, or the final response.

## Locate The Skill

Set `SKILL_DIR` to the directory containing this `SKILL.md`. Use absolute paths in every command.

```bash
SKILL_DIR="$HOME/.codex/skills/wechat-chat-decrypt"
PY="$HOME/.local/share/wechat-chat-decrypt/venv/bin/python"
```

If the skill is running from a repository checkout, use that checkout as `SKILL_DIR`.

## Workflow

### 1. Bootstrap The Private Runtime

Run once:

```bash
bash "$SKILL_DIR/scripts/bootstrap.sh"
```

This installs the vendored, pinned `wechat-cli` into `~/.local/share/wechat-chat-decrypt/venv`. It does not install a global package.

### 2. Run A Read-Only Preflight

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" preflight
```

Use the JSON `next_actions`. Do not infer success from the app merely opening.

- `verified`: WeChat 4.1.8 build 37261, the tested version.
- `upstream_compatible_unverified`: an older 4.x build covered by upstream's stated range, but not verified by this skill. Tell the user before proceeding.
- `unsupported_newer`: do not attempt memory scanning. Follow the trusted-DMG branch.
- Multiple accounts: ask which currently logged-in account to use, then pass its exact `db_dir` to `prepare-probe`.
- No accounts: ask the user to launch WeChat, log in, and wait for local messages to sync.
- Data access failure: direct the user to System Settings -> Privacy & Security -> Full Disk Access, enable their terminal/Codex app, then restart it.

### 3. Newer WeChat: Download, Validate, And Install The DMG

Do not download an old WeChat build from an arbitrary mirror. This skill intentionally does not bundle Tencent's proprietary installer or download it in the background. After the user confirms the downgrade and data backup, direct them to the tested DMG on Tencent's CDN, or accept a local copy:

<https://dldir1v6.qq.com/weixin/Universal/Mac/xWeChatMac_universal_4.1.8.100_37261.dmg>

Treat the URL as a download entry point, not as proof of authenticity. The installer must still pass `inspect-dmg` before installation.

Ask the user to download `xWeChatMac_universal_4.1.8.100_37261.dmg` from the Tencent CDN above, or provide the same file from a trusted local source. Before downgrade, require a current Time Machine or separate copy backup of the local `xwechat_files` directory.

Validate without installing:

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" inspect-dmg --dmg "/absolute/path/to/file.dmg"
```

Continue only when `accepted` is `true`. The check requires:

- bundle ID `com.tencent.xinWeChat`
- version `4.1.8`, build `37261`
- Tencent Team ID `5A4RE8SF68`
- valid code signature
- `arm64` executable support

After the user confirms both the data backup and that WeChat is fully closed:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" install-dmg \
  --dmg "/absolute/path/to/file.dmg" \
  --confirm-data-backup \
  --confirm-wechat-closed
```

This backs up the existing app bundle separately. It does not modify the chat-data directory.

### 4. Re-Sign WeChat For Local Memory Access

Explain that this modifies the local app signature, not chat data. The official signature can be restored by reinstalling WeChat from Tencent.

Ask the user to quit WeChat completely, then run:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" resign
```

The script preserves current entitlements, adds only `com.apple.security.get-task-allow`, and verifies the resulting signature. The user must then reopen WeChat and log in. Never request or capture the user's administrator password in chat; let `sudo` collect it interactively.

### 5. Extract Keys Without Printing Them

Create a private mirror containing only the first 16 encrypted bytes of each database:

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" prepare-probe \
  --db-dir "/absolute/path/from/preflight/db_storage"
```

Read the returned `manifest` path, then run:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" extract-keys \
  --manifest "/private/tmp/wechat-chat-decrypt-probe-.../manifest.json"
```

The scanner's raw output contains keys, so the wrapper captures and discards it. Successful output reports counts only. Keys and config are written to `~/.wechat-cli/` with private permissions, and any previous state is backed up locally.

### 6. Verify Before Reading Messages

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" verify
```

Acceptance requires:

- one or more database keys saved
- HMAC verification for the matched encrypted pages
- at least one message database key
- SQLite `quick_check` equals `ok`
- temporary plaintext removed

This command does not read message rows or contact names.

To create a clean shareable archive from a checkout, run:

```bash
bash "$SKILL_DIR/scripts/package-skill.sh" "/absolute/path/to/wechat-chat-decrypt-skill.zip"
```

### 7. Block Automatic Upgrade When A Downgrade Was Required

Ask for explicit confirmation before changing update behavior. Then:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard block
```

Check later with:

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard status
```

Restore updater permissions before intentionally updating:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard unblock --enable-automatic-updates
```

### 8. Query Through The Safe Wrapper

Always use `wechat-cli-safe`; do not call a global `wechat-cli`. It gives each command a private temporary directory and removes plaintext databases when the command exits.

```bash
"$SKILL_DIR/scripts/wechat-cli-safe" sessions --limit 20 --format text
"$SKILL_DIR/scripts/wechat-cli-safe" history "联系人" --limit 50 --format text
"$SKILL_DIR/scripts/wechat-cli-safe" search "关键词" --chat "群名" --format text
"$SKILL_DIR/scripts/wechat-cli-safe" export "联系人" --format markdown --output "/private/local/path/chat.md"
```

Only read or summarize the date range and chats the user asked for. For broad requests, state the time range, separate private chats from groups, exclude passive broadcasts, and note that voice messages are not transcribed automatically.

### 9. Clean Up

After ordinary querying, the safe wrapper cleans itself. Audit and remove leftovers with:

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" cleanup --include-probes
```

Add `--include-persistent` only when the user explicitly asks to remove a persistent decrypted directory. This preserves keys and config.

## Reporting

Report only:

- app version/build and compatibility status
- number of encrypted databases, matched keys, and HMAC-verified databases
- SQLite verification result
- whether update blocking is active
- any unsupported media limits

Do not include key material, raw scanner output, complete personal identifiers, or credentials found inside messages. When summarizing chats, paraphrase sensitive content and redact addresses, phone numbers, passwords, API keys, remote-control codes, and subscription URLs.

## Troubleshooting

Read [references/troubleshooting.md](references/troubleshooting.md) for exact recovery branches. Read [references/compatibility.md](references/compatibility.md) before changing supported versions or the pinned upstream snapshot.
