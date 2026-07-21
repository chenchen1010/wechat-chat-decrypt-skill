# Troubleshooting

## Windows: no key found

Run `preflight` and record `windows_app.version`, the account directory, database format, and encrypted database count. The bundled scanner only accepts candidates that match a database-page HMAC. The only verified Windows client is Weixin 4.1.8.101. A zero-key result is a compatibility stop, not a reason to brute-force or print memory.

If the error says `OpenProcess` or `ReadProcessMemory`, start WeChat and Codex/PowerShell at the same integrity level. Use Administrator PowerShell only when Windows denies access. Never disable Defender, CFG, or other kernel protections.

If extraction succeeds, always run `verify` before querying. It performs HMAC checks and SQLite `quick_check` without reading message rows.

## Windows: prevent automatic upgrade

After installing the verified client, run `update-guard status`. To block only the Weixin updater's outbound connections, open an elevated PowerShell and run `update-guard block`. This replaces old rules, targets the exact current `WeixinUpdate.exe` path, and stops a running updater process; it does not block the main Weixin client. Run it again after every reinstall or upgrade.

## `task_for_pid failed`

1. Confirm the app version is supported.
2. Quit WeChat completely.
3. Run `sudo ... wechat_decrypt.py resign`.
4. Reopen WeChat and log in.
5. Run `preflight` and confirm `get_task_allow: true`.
6. Prepare a new probe; never reuse an old manifest.

Do not disable SIP. The verified route uses an ad-hoc app signature with one added entitlement.

## No WeChat Data Directory

Open WeChat, log in, and wait for recent chats to appear locally. Then rerun preflight. The expected root is:

```text
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files
```

Do not point the Skill at an arbitrary copied directory unless the user clearly owns and authorizes that data; v1 intentionally restricts extraction to the current user's live local container.

## Full Disk Access Failure

Open System Settings -> Privacy & Security -> Full Disk Access. Enable the application actually running commands, such as Codex, Terminal, or iTerm. Quit and reopen that application before retrying.

## Multiple Accounts

Preflight sorts account directories by recent database activity. Ask the user which account is currently logged in, then pass its exact `db_dir` to `prepare-probe`. Do not merge keys from different accounts.

## Scanner Matches Fewer Databases Than Found

This is not automatically a failure. Small ancillary databases may not have a live key candidate. Require all of the following instead:

- at least one matched `message/` database;
- HMAC verification for saved keys;
- a successful full message-database decrypt;
- SQLite `quick_check: ok`.

## `verify` Says Dependencies Are Missing

Run:

```bash
  # Windows PowerShell:
  & (Join-Path $SKILL_DIR 'scripts\bootstrap.ps1')
  # macOS/Linux:
  bash "$SKILL_DIR/scripts/bootstrap.sh"
```

Then retry with the runtime Python at:

```text
~/.local/share/wechat-chat-decrypt/venv/bin/python
```

## WeChat Updated Again

Do not scan the newer process. Run preflight, restore/provide the supported app, repeat re-signing and key extraction, then enable the update guard after verification.

## Restore Normal WeChat Updating

Windows PowerShell (管理员):

```powershell
& $Py (Join-Path $SkillDir 'scripts\wechat_decrypt.py') update-guard unblock
```

macOS:

```bash
sudo "$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" update-guard unblock --enable-automatic-updates
```

Then reinstall the current official WeChat release from Tencent to restore its official signature. Local keys/config may remain, but new database keys can require extraction again.

## Remove Plaintext Leftovers

Run:

```bash
"$PY" "$SKILL_DIR/scripts/wechat_decrypt.py" cleanup --include-probes
```

Use `--include-persistent` only with explicit user approval. It does not delete `config.json` or `all_keys.json`.
