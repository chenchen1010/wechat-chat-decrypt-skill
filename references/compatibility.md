# Compatibility

## Verified Matrix

| Component | Verified value |
| --- | --- |
| Platform | Apple Silicon macOS (`arm64`) |
| macOS | 26.3.1 or newer, following upstream's published requirement |
| WeChat app | 4.1.8, build 37261 |
| Common DMG label | `xWeChatMac_universal_4.1.8.100_37261.dmg` |
| Tencent CDN DMG | `https://dldir1v6.qq.com/weixin/Universal/Mac/xWeChatMac_universal_4.1.8.100_37261.dmg` |
| Bundle ID | `com.tencent.xinWeChat` |
| Tencent Team ID | `5A4RE8SF68` |
| Upstream | `https://github.com/huohuoer/wechat-cli.git` |
| Pinned commit | `a3789232d4f79bf0b30634d9dadbce71e4acd601` |
| Upstream package version | 0.2.4 |

## Windows Matrix

| Component | Supported value |
| --- | --- |
| Platform | Windows 10/11, x64 or ARM64 Python |
| WeChat app | Verified `Weixin.exe` 4.1.8.101; classic fallback `WeChat.exe` 3.9.11.25 |
| Data location | Modern `xwechat_files/*/db_storage`; classic `Documents\WeChat Files\*/Msg` |
| Database format | Modern SQLCipher v4; classic SQLCipher v3 |
| Scanner | Bundled pure-Python `scanner_windows.py`; classic mode follows WeChatWin.dll pointer references |
| Elevation | Same integrity level as WeChat; Administrator only when Windows denies process-memory reads |

The Windows path is intentionally validated at runtime with database-page HMACs and SQLite `quick_check`. A successful memory scan with zero matched message databases is a failure, not a usable result. The modern 4.1.8.101 path has been run on a logged-in Windows machine and returned 20 matched databases with `quick_check=ok`.

### Windows version caveat

The modern scanner expects the legacy `x'<64-hex-key><32-hex-salt>'` representation. Weixin builds that do not expose it must stop and report the exact detected version; the Skill must not guess keys or weaken HMAC validation. Classic 3.9.x uses a separate SQLCipher v3 pointer scanner and must be fully logged in.

The upstream README states WeChat for Mac 4.1.8.100 or earlier. This Skill reports older 4.x builds as `upstream_compatible_unverified` rather than claiming they were tested here.

## Why Newer WeChat Is Blocked

The successful workflow depended on the 4.1.8 process-memory key representation and the pinned scanner. A newer app may move or transform key material, and treating a failed scan as a valid empty result is unsafe. Do not weaken the version gate without a fresh end-to-end test that proves:

1. scanner output is structurally valid;
2. database-page HMACs match;
3. at least one message database fully decrypts;
4. SQLite `quick_check` returns `ok`;
5. chat queries return expected local data;
6. all temporary plaintext is removed.

## Updating The Upstream Snapshot

When updating `vendor/wechat-cli`:

1. Review upstream code and license changes.
2. Update the pinned commit in `README.md`, `SKILL.md`, `wechat_decrypt.py`, and `THIRD_PARTY_NOTICES.md`.
3. Recalculate the bundled scanner SHA-256 and update `SCANNER_SHA256`.
4. Re-run unit tests, preflight, key verification, a safe query, and cache cleanup.
5. Never copy a local `~/.wechat-cli` directory into the package.

## Unsupported In V1

- Intel macOS
- Linux automated orchestration
- iPhone backups
- voice-message transcription
- OCR of image messages
- recovery of content already removed from the local database
