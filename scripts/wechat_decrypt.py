#!/usr/bin/env python3
"""Safe orchestration for decrypting the current user's local WeChat data.

This wrapper never prints database keys. It only supports the local macOS user
and keeps decrypted SQLite files in short-lived temporary directories.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

try:
    import pwd  # type: ignore
except ImportError:  # Windows
    pwd = None


SKILL_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = SKILL_ROOT / "vendor" / "wechat-cli"
SCANNER_PATH = VENDOR_ROOT / "wechat_cli" / "bin" / "find_all_keys_macos.arm64"
SCANNER_SHA256 = "17bbc697ce5e0a2715d2125514c21f6725526720d1d888609bef30337d5a2e8c"
UPSTREAM_COMMIT = "a3789232d4f79bf0b30634d9dadbce71e4acd601"

BUNDLE_ID = "com.tencent.xinWeChat"
TENCENT_TEAM_ID = "5A4RE8SF68"
VERIFIED_VERSION = "4.1.8"
VERIFIED_BUILD = "37261"
MIN_MACOS_VERSION = (26, 3, 1)
SQLITE_HEADER = b"SQLite format 3\x00"
PAGE_SIZE = 4096
RESERVED_SIZE = 80

APP_CANDIDATES = (
    Path("/Applications/WeChat.app"),
    Path.home() / "Applications" / "WeChat.app",
)

WINDOWS_PROCESS_NAMES = ("Weixin.exe", "WeChat.exe")
WINDOWS_VERIFIED_MODERN = ("4.1.8.101", "4.1.8.101")
WINDOWS_VERIFIED_CLASSIC = ("3.9.11.1000", "3.9.11.25")

SPARKLE_EXECUTABLES = (
    "Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate",
    "Contents/Frameworks/Sparkle.framework/Versions/B/Updater.app/Contents/MacOS/Updater",
    "Contents/Frameworks/Sparkle.framework/Versions/B/XPCServices/Installer.xpc/Contents/MacOS/Installer",
)


class SkillError(RuntimeError):
    """Expected, user-actionable workflow failure."""


def emit(payload: dict[str, object]) -> None:
    # Windows PowerShell 5 often decodes child-process stdout using the local
    # code page. ASCII-only JSON escapes keep paths and diagnostics lossless.
    print(json.dumps(payload, ensure_ascii=platform.system() == "Windows", indent=2, sort_keys=True))


def fail(message: str, *, code: int = 1, details: dict[str, object] | None = None) -> None:
    payload: dict[str, object] = {"ok": False, "error": message}
    if details:
        payload["details"] = details
    emit(payload)
    raise SystemExit(code)


def run(
    args: list[str],
    *,
    check: bool = False,
    timeout: int = 30,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    kwargs: dict[str, object] = {
        "check": check,
        "capture_output": True,
        "timeout": timeout,
        "env": env,
        "cwd": str(cwd) if cwd else None,
        "text": text,
    }
    if text and platform.system() == "Windows":
        kwargs.update({"encoding": "utf-8", "errors": "replace"})
    return subprocess.run(args, **kwargs)


def real_identity() -> tuple[int | None, int | None, str, Path]:
    """Return the non-root user, including when invoked through sudo."""
    if platform.system() == "Windows":
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        return None, None, user, home
    if os.geteuid() == 0:
        sudo_uid = os.environ.get("SUDO_UID")
        sudo_gid = os.environ.get("SUDO_GID")
        sudo_user = os.environ.get("SUDO_USER")
        if not (sudo_uid and sudo_gid and sudo_user and sudo_user != "root"):
            raise SkillError("Run privileged commands with sudo from the target user account")
        uid = int(sudo_uid)
        gid = int(sudo_gid)
        user = sudo_user
    else:
        uid = os.getuid()
        gid = os.getgid()
        user = pwd.getpwuid(uid).pw_name
    return uid, gid, user, Path(pwd.getpwuid(uid).pw_dir)


def require_root() -> tuple[int, int, str, Path]:
    if platform.system() == "Windows":
        raise SkillError("This command does not require elevation on Windows; run it without Administrator first")
    if os.geteuid() != 0:
        raise SkillError("This command requires sudo")
    return real_identity()


def parse_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(number) for number in numbers) if numbers else (0,)


def classify_wechat_version(version: str, build: str) -> str:
    parsed = parse_version(version)
    verified = parse_version(VERIFIED_VERSION)
    if version == VERIFIED_VERSION and build == VERIFIED_BUILD:
        return "verified"
    if parsed > verified or (parsed == verified and build.isdigit() and int(build) > int(VERIFIED_BUILD)):
        return "unsupported_newer"
    if (4, 0, 0) <= parsed <= verified:
        return "upstream_compatible_unverified"
    return "unsupported_unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"Invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise SkillError(f"Expected a JSON object: {path}")
    return payload


def atomic_json(path: Path, payload: dict, *, uid: int | None = None, gid: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        if uid is not None and gid is not None and hasattr(os, "chown"):
            os.chown(temporary, uid, gid)
            os.chown(path.parent, uid, gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def private_temp_root() -> Path:
    """Return the per-user temporary root used for transient plaintext."""
    return Path(tempfile.gettempdir()).resolve()


def chown_if_posix(path: Path, uid: int | None, gid: int | None) -> None:
    if uid is not None and gid is not None and hasattr(os, "chown"):
        os.chown(path, uid, gid)


def find_wechat_app() -> Path | None:
    for candidate in APP_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def windows_process_pids() -> list[int]:
    """Return running WeChat for Windows PIDs, largest working set first."""
    if platform.system() != "Windows":
        return []
    result = run(["tasklist", "/FO", "CSV", "/NH"], timeout=10)
    pids: list[tuple[int, int]] = []
    for line in (result.stdout or "").splitlines():
        fields = [item.strip('"') for item in line.split('","')]
        if len(fields) < 5 or fields[0] not in WINDOWS_PROCESS_NAMES:
            continue
        try:
            pids.append((int(fields[1]), int(re.sub(r"[^0-9]", "", fields[4]))))
        except (ValueError, TypeError):
            continue
    pids.sort(key=lambda item: item[1], reverse=True)
    return [pid for pid, _ in pids]


def classify_windows_client(path: str | None, version: str | None) -> str:
    """Classify only versions for which the Windows scanner was verified."""
    process_name = Path(path).name.casefold() if path else ""
    if process_name == "wechat.exe":
        return "verified_classic" if version in WINDOWS_VERIFIED_CLASSIC else "unsupported_classic"
    if version in WINDOWS_VERIFIED_MODERN:
        return "verified_modern"
    if version and parse_version(version) > parse_version(WINDOWS_VERIFIED_MODERN[0]):
        return "unsupported_newer"
    return "unverified_modern"


def windows_wechat_metadata(pids: list[int]) -> dict[str, object] | None:
    """Read the executable path/version without touching chat data."""
    if platform.system() != "Windows" or not pids:
        return None
    pid = pids[0]
    command = f"$p=(Get-Process -Id {pid}).Path; if ($p) {{ $v=(Get-Item -LiteralPath $p).VersionInfo; Write-Output ($p+'|'+$v.ProductVersion) }}"
    result = run(
        ["powershell", "-NoProfile", "-Command", command],
        timeout=15,
    )
    value = (result.stdout or "").strip()
    if "|" not in value:
        return {"pid": pid, "path": None, "version": None, "compatibility": "unknown"}
    path, version = value.rsplit("|", 1)
    version = version or None
    compatibility = classify_windows_client(path, version)
    return {"pid": pid, "path": path, "version": version, "compatibility": compatibility}


def read_plist(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise SkillError(f"Cannot read plist: {path}") from exc
    if not isinstance(payload, dict):
        raise SkillError(f"Unexpected plist structure: {path}")
    return payload


def read_entitlements(app_path: Path) -> dict[str, object]:
    result = run(
        ["/usr/bin/codesign", "-d", "--entitlements", ":-", str(app_path)],
        timeout=30,
        text=False,
    )
    for payload in (result.stdout or b"", result.stderr or b""):
        starts = [index for index in (payload.find(b"<?xml"), payload.find(b"<plist")) if index >= 0]
        end = payload.find(b"</plist>")
        if not starts or end < 0:
            continue
        end += len(b"</plist>")
        try:
            entitlements = plistlib.loads(payload[min(starts) : end])
        except Exception:
            continue
        if isinstance(entitlements, dict):
            return entitlements
    return {}


def code_signature_details(app_path: Path) -> dict[str, object]:
    verify = run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_path)],
        timeout=60,
    )
    detail = run(
        ["/usr/bin/codesign", "-dv", "--verbose=4", str(app_path)],
        timeout=30,
    )
    output = f"{detail.stdout or ''}\n{detail.stderr or ''}"
    team_match = re.search(r"^TeamIdentifier=(.+)$", output, re.MULTILINE)
    authority_match = re.search(r"^Authority=(.+)$", output, re.MULTILINE)
    return {
        "signature_valid": verify.returncode == 0,
        "team_identifier": team_match.group(1).strip() if team_match else None,
        "authority": authority_match.group(1).strip() if authority_match else None,
    }


def immutable(path: Path) -> bool:
    try:
        return bool(path.stat().st_flags & stat.UF_IMMUTABLE)
    except (AttributeError, FileNotFoundError, PermissionError):
        return False


def app_metadata(app_path: Path) -> dict[str, object]:
    info = read_plist(app_path / "Contents" / "Info.plist")
    signature = code_signature_details(app_path)
    entitlements = read_entitlements(app_path)
    version = str(info.get("CFBundleShortVersionString", ""))
    build = str(info.get("CFBundleVersion", ""))
    return {
        "path": str(app_path),
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "version": version,
        "build": build,
        "compatibility": classify_wechat_version(version, build),
        "get_task_allow": entitlements.get("com.apple.security.get-task-allow") is True,
        "immutable": immutable(app_path),
        **signature,
    }


def wechat_pids() -> list[int]:
    if platform.system() == "Windows":
        return windows_process_pids()
    result = run(["/usr/bin/pgrep", "-x", "WeChat"], timeout=10)
    if result.returncode not in (0, 1):
        return []
    return [int(line) for line in (result.stdout or "").splitlines() if line.strip().isdigit()]


def expected_data_roots(home: Path) -> list[Path]:
    if platform.system() == "Windows":
        roots: list[Path] = []
        appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        config_dir = appdata / "Tencent" / "xwechat" / "config"
        for ini_file in config_dir.glob("*.ini"):
            raw = ""
            for encoding in ("utf-8", "gbk"):
                try:
                    raw = ini_file.read_text(encoding=encoding).strip()
                    break
                except (OSError, UnicodeDecodeError):
                    continue
            if raw and "\n" not in raw and "\r" not in raw and "\x00" not in raw:
                candidate = Path(raw).expanduser()
                if candidate.is_dir():
                    roots.append(candidate / "xwechat_files")
        roots.extend(
            [
                home / "Documents" / "xwechat_files",
                home / "Documents" / "WeChat Files",
                appdata / "Tencent" / "xwechat" / "xwechat_files",
            ]
        )
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            normalized = os.path.normcase(os.path.normpath(str(root)))
            if normalized not in seen:
                seen.add(normalized)
                unique.append(root)
        return unique
    return [home / "Library" / "Containers" / BUNDLE_ID / "Data" / "Documents" / "xwechat_files"]


def expected_data_root(home: Path) -> Path:
    """Compatibility helper returning the primary local WeChat data root."""
    return expected_data_roots(home)[0]


def database_files(db_dir: Path) -> list[Path]:
    try:
        return [path for path in db_dir.rglob("*.db") if path.is_file()]
    except PermissionError as exc:
        raise SkillError("Cannot read WeChat data; grant Full Disk Access to the terminal/Codex app") from exc


def is_encrypted_database(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError:
        return False
    return len(header) == 16 and header != SQLITE_HEADER


def account_activity(db_dir: Path) -> float:
    message_dir = db_dir / "message"
    target = message_dir if message_dir.is_dir() else db_dir
    newest = target.stat().st_mtime
    try:
        for path in target.iterdir():
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def discover_accounts(home: Path) -> list[dict[str, object]]:
    accounts: list[dict[str, object]] = []
    candidates: list[Path] = []
    for root in expected_data_roots(home):
        if not root.is_dir():
            continue
        try:
            candidates.extend(path for path in root.glob("*/db_storage") if path.is_dir())
            # The classic 3.x Windows client stores its account databases in
            # Documents\\WeChat Files\\<wxid>\\Msg, rather than db_storage.
            if root.name.casefold() == "wechat files":
                candidates.extend(path.parent for path in root.glob("*/Msg") if path.is_dir())
        except PermissionError as exc:
            raise SkillError("Cannot read WeChat data; grant access to the Codex/terminal process") from exc
    unique: dict[str, Path] = {}
    for path in candidates:
        unique[os.path.normcase(os.path.normpath(str(path)))] = path
    candidates = list(unique.values())
    candidates.sort(key=account_activity, reverse=True)
    for index, db_dir in enumerate(candidates, 1):
        dbs = database_files(db_dir)
        activity = account_activity(db_dir)
        accounts.append(
            {
                "index": index,
                "db_dir": str(db_dir),
                "account_directory": db_dir.name,
                "database_format": "wcdb_sqlcipher_v4" if (db_dir / "db_storage").is_dir() else "classic_sqlcipher_v3",
                "last_activity": datetime.fromtimestamp(activity).astimezone().isoformat(timespec="seconds"),
                "database_count": len(dbs),
                "encrypted_database_count": sum(is_encrypted_database(path) for path in dbs),
            }
        )
    return accounts


def validate_key_data(payload: dict) -> dict[str, dict[str, str]]:
    validated: dict[str, dict[str, str]] = {}
    for relative_path, value in payload.items():
        if str(relative_path).startswith("_"):
            continue
        if not isinstance(value, dict):
            raise SkillError("Invalid key file structure")
        key = value.get("enc_key")
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            raise SkillError("Invalid encryption key in scanner output")
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise SkillError("Unsafe database path in scanner output")
        validated[str(relative_path)] = {"enc_key": key.lower()}
    if not validated:
        raise SkillError("No database keys were extracted")
    return validated


def command_preflight(_: argparse.Namespace) -> None:
    system = platform.system()
    if system not in {"Darwin", "Windows"}:
        fail("This skill currently supports Apple Silicon macOS and Windows")
    uid, _, _, home = real_identity()
    architecture = platform.machine()
    macos = platform.mac_ver()[0] if system == "Darwin" else None
    app_path = find_wechat_app()
    accounts = discover_accounts(home)
    state_dir = home / ".wechat-cli"
    keys_path = state_dir / "all_keys.json"
    saved_key_count = 0
    if keys_path.is_file():
        try:
            saved_key_count = len(validate_key_data(load_json(keys_path)))
        except SkillError:
            saved_key_count = -1

    app = app_metadata(app_path) if app_path else None
    pids = wechat_pids()
    windows_app = windows_wechat_metadata(pids) if system == "Windows" else None
    next_actions: list[str] = []
    if system == "Darwin" and architecture != "arm64":
        next_actions.append("unsupported_architecture")
    if system == "Darwin" and not app:
        next_actions.append("install_wechat")
    elif system == "Darwin" and app["compatibility"] == "unsupported_newer":
        next_actions.append("provide_verified_wechat_4_1_8_dmg")
    elif system == "Darwin" and app and app["compatibility"] == "unsupported_unknown":
        next_actions.append("review_wechat_version")
    if not accounts:
        next_actions.append("login_and_sync_wechat")
    if system == "Darwin" and app and not app["get_task_allow"]:
        next_actions.append("quit_and_resign_wechat")
    if system == "Darwin" and app and app["get_task_allow"] and not pids:
        next_actions.append("start_and_login_wechat")
    if system == "Windows" and not pids:
        next_actions.append("launch_weixin_and_login")
    if system == "Windows" and windows_app and windows_app.get("compatibility") == "unsupported_newer":
        next_actions.append("use_verified_weixin_4_1_8_101_or_classic_3_9_11")
    if len(accounts) > 1 and saved_key_count <= 0:
        next_actions.append("select_current_account")
    elif saved_key_count <= 0:
        next_actions.append("extract_keys")
    if saved_key_count > 0:
        next_actions.append("verify_keys")

    hard_guard = False
    if app_path:
        targets = [app_path / relative for relative in SPARKLE_EXECUTABLES]
        hard_guard = immutable(app_path) and all(
            target.exists() and immutable(target) and stat.S_IMODE(target.stat().st_mode) == 0o600
            for target in targets
        )

    emit(
        {
            "ok": True,
            "platform": "macOS" if system == "Darwin" else "Windows",
            "architecture": architecture,
            "supported_architecture": ((system == "Darwin" and architecture == "arm64")
                                       or (system == "Windows" and architecture.upper() in {"AMD64", "X86_64", "ARM64"})),
            "macos_version": macos,
            "upstream_minimum_macos": ".".join(map(str, MIN_MACOS_VERSION)) if system == "Darwin" else None,
            "app": app,
            "windows_app": windows_app,
            "wechat_running": bool(pids),
            "wechat_process_count": len(pids),
            "accounts": accounts,
            "state": {
                "owner_uid": uid,
                "config_exists": (state_dir / "config.json").is_file(),
                "keys_exist": keys_path.is_file(),
                "saved_key_count": saved_key_count,
                "state_permissions_private": state_dir.is_dir()
                and stat.S_IMODE(state_dir.stat().st_mode) & 0o077 == 0,
            },
            "runtime": {
                "scanner_exists": SCANNER_PATH.is_file() if system == "Darwin" else True,
                "scanner_hash_valid": SCANNER_PATH.is_file()
                and sha256_file(SCANNER_PATH) == SCANNER_SHA256 if system == "Darwin" else True,
                "scanner": "bundled_native_macos" if system == "Darwin" else "bundled_python_windows",
                "venv_ready": ((home / ".local/share/wechat-chat-decrypt/venv/bin/wechat-cli").is_file()
                               if system == "Darwin" else
                               (Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
                                / "wechat-chat-decrypt" / "venv" / "Scripts" / "wechat-cli.exe").is_file()),
                "upstream_commit": UPSTREAM_COMMIT,
            },
            "update_guard": {"hard_blocked": hard_guard},
            "next_actions": next_actions,
        }
    )


@contextmanager
def mounted_dmg(dmg_path: Path):
    result = run(
        ["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-plist", str(dmg_path)],
        check=True,
        timeout=120,
        text=False,
    )
    payload = plistlib.loads(result.stdout)
    mount_points = [
        Path(entity["mount-point"])
        for entity in payload.get("system-entities", [])
        if isinstance(entity, dict) and entity.get("mount-point")
    ]
    if not mount_points:
        raise SkillError("The DMG mounted without a readable volume")
    try:
        yield mount_points
    finally:
        for mount_point in reversed(mount_points):
            run(["/usr/bin/hdiutil", "detach", str(mount_point)], timeout=60)


def locate_app_in_mounts(mount_points: list[Path]) -> Path:
    for mount_point in mount_points:
        direct = mount_point / "WeChat.app"
        if direct.is_dir():
            return direct
        for candidate in mount_point.glob("*.app"):
            if candidate.name == "WeChat.app" and candidate.is_dir():
                return candidate
    raise SkillError("No WeChat.app was found in the DMG")


def inspect_installer_app(app_path: Path) -> dict[str, object]:
    metadata = app_metadata(app_path)
    lipo = run(["/usr/bin/lipo", "-archs", str(app_path / "Contents/MacOS/WeChat")], timeout=30)
    architectures = (lipo.stdout or "").strip().split() if lipo.returncode == 0 else []
    accepted = all(
        (
            metadata["bundle_identifier"] == BUNDLE_ID,
            metadata["version"] == VERIFIED_VERSION,
            metadata["build"] == VERIFIED_BUILD,
            metadata["signature_valid"] is True,
            metadata["team_identifier"] == TENCENT_TEAM_ID,
            "arm64" in architectures,
        )
    )
    return {**metadata, "architectures": architectures, "accepted": accepted}


def inspect_dmg(dmg_path: Path) -> dict[str, object]:
    if not dmg_path.is_file():
        raise SkillError(f"DMG not found: {dmg_path}")
    digest = sha256_file(dmg_path)
    with mounted_dmg(dmg_path) as mount_points:
        app_path = locate_app_in_mounts(mount_points)
        app = inspect_installer_app(app_path)
    return {"dmg": str(dmg_path.resolve()), "sha256": digest, "app": app, "accepted": app["accepted"]}


def command_inspect_dmg(args: argparse.Namespace) -> None:
    try:
        result = inspect_dmg(Path(args.dmg).expanduser().resolve())
    except (SkillError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        fail(str(exc))
    emit({"ok": bool(result["accepted"]), **result})
    if not result["accepted"]:
        raise SystemExit(2)


def run_as_user(user: str, args: list[str]) -> subprocess.CompletedProcess:
    return run(["/usr/bin/sudo", "-H", "-u", user, *args], timeout=30)


def set_update_preferences(user: str, *, enabled: bool) -> None:
    value = "true" if enabled else "false"
    for key in ("SUAutomaticallyUpdate", "SUEnableAutomaticChecks"):
        result = run_as_user(user, ["/usr/bin/defaults", "write", BUNDLE_ID, key, "-bool", value])
        if result.returncode != 0:
            raise SkillError(f"Could not update WeChat preference {key}")
    if not enabled:
        run_as_user(
            user,
            ["/usr/bin/defaults", "write", BUNDLE_ID, "SUScheduledCheckInterval", "-int", "31536000"],
        )


def clear_immutable_flags(app_path: Path) -> None:
    paths = [app_path, *(app_path / relative for relative in SPARKLE_EXECUTABLES)]
    for path in paths:
        if path.exists():
            result = run(["/usr/bin/chflags", "nouchg", str(path)], timeout=30)
            if result.returncode != 0:
                raise SkillError(f"Could not clear immutable flag: {path}")


def chown_tree(path: Path, uid: int, gid: int) -> None:
    run(["/usr/sbin/chown", "-R", f"{uid}:{gid}", str(path)], check=True, timeout=120)


def command_install_dmg(args: argparse.Namespace) -> None:
    try:
        uid, gid, user, home = require_root()
        if not args.confirm_data_backup or not args.confirm_wechat_closed:
            raise SkillError("Both explicit confirmation flags are required")
        if wechat_pids():
            raise SkillError("Quit WeChat completely before installing the supported version")
        dmg_path = Path(args.dmg).expanduser().resolve()
        initial = inspect_dmg(dmg_path)
        if not initial["accepted"]:
            raise SkillError("DMG validation failed; refusing to install")

        target = Path("/Applications/WeChat.app")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = home / "Library" / "Application Support" / "wechat-chat-decrypt" / "app-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.chmod(0o700)
        os.chown(backup_dir, uid, gid)
        backup_path: Path | None = None

        if target.exists():
            current = app_metadata(target)
            clear_immutable_flags(target)
            backup_path = backup_dir / f"WeChat-{current['version']}-{current['build']}-{timestamp}.app"
            run(["/usr/bin/ditto", str(target), str(backup_path)], check=True, timeout=300)
            chown_tree(backup_path, uid, gid)

        temporary_target = Path("/Applications") / f".WeChat.skill-{uuid.uuid4().hex}.app"
        try:
            with mounted_dmg(dmg_path) as mount_points:
                source_app = locate_app_in_mounts(mount_points)
                run(["/usr/bin/ditto", str(source_app), str(temporary_target)], check=True, timeout=300)
            installed_check = inspect_installer_app(temporary_target)
            if not installed_check["accepted"]:
                raise SkillError("Copied app failed validation")

            if target.exists():
                shutil.rmtree(target)
            os.replace(temporary_target, target)
        except Exception:
            if temporary_target.exists():
                shutil.rmtree(temporary_target, ignore_errors=True)
            if not target.exists() and backup_path and backup_path.exists():
                run(["/usr/bin/ditto", str(backup_path), str(target)], timeout=300)
            raise

        set_update_preferences(user, enabled=False)
        emit(
            {
                "ok": True,
                "installed_version": VERIFIED_VERSION,
                "installed_build": VERIFIED_BUILD,
                "previous_app_backup": str(backup_path) if backup_path else None,
                "next_action": "resign_then_launch_and_login",
            }
        )
    except (SkillError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        fail(str(exc))


def command_resign(_: argparse.Namespace) -> None:
    try:
        _, _, user, _ = require_root()
        app_path = find_wechat_app()
        if not app_path:
            raise SkillError("WeChat.app not found")
        if wechat_pids():
            raise SkillError("Quit WeChat completely before re-signing")
        metadata = app_metadata(app_path)
        if metadata["compatibility"] not in ("verified", "upstream_compatible_unverified"):
            raise SkillError("Refusing to re-sign an unsupported WeChat version")
        clear_immutable_flags(app_path)
        set_update_preferences(user, enabled=False)

        entitlements = read_entitlements(app_path)
        entitlements["com.apple.security.get-task-allow"] = True
        fd, entitlement_name = tempfile.mkstemp(prefix="wechat-entitlements-", suffix=".plist")
        entitlement_path = Path(entitlement_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                plistlib.dump(entitlements, handle, fmt=plistlib.FMT_XML, sort_keys=True)
            result = run(
                [
                    "/usr/bin/codesign",
                    "--force",
                    "--sign",
                    "-",
                    "--entitlements",
                    str(entitlement_path),
                    str(app_path),
                ],
                timeout=120,
            )
            if result.returncode != 0:
                raise SkillError("codesign failed")
        finally:
            entitlement_path.unlink(missing_ok=True)

        updated = app_metadata(app_path)
        if not updated["signature_valid"] or not updated["get_task_allow"]:
            raise SkillError("Re-signed app did not pass validation")
        emit(
            {
                "ok": True,
                "version": updated["version"],
                "build": updated["build"],
                "get_task_allow": True,
                "signature_valid": True,
                "next_action": "launch_wechat_and_login",
            }
        )
    except (SkillError, subprocess.TimeoutExpired) as exc:
        fail(str(exc))


def resolve_db_dir(value: str | None, home: Path) -> Path:
    accounts = discover_accounts(home)
    if value:
        db_dir = Path(value).expanduser().resolve()
    elif len(accounts) == 1:
        db_dir = Path(str(accounts[0]["db_dir"])).resolve()
    elif not accounts:
        raise SkillError("No WeChat database directory found")
    else:
        raise SkillError("Multiple accounts found; pass --db-dir for the currently logged-in account")
    roots = [root.resolve() for root in expected_data_roots(home)]
    classic = (db_dir / "Msg").is_dir() and not (db_dir / "db_storage").is_dir()
    wcdb = db_dir.name == "db_storage"
    if not db_dir.is_dir() or not (classic or wcdb) or not any(root in db_dir.parents for root in roots):
        raise SkillError("database directory must belong to the current user's local WeChat data directory")
    return db_dir


def command_prepare_probe(args: argparse.Namespace) -> None:
    try:
        uid, _, _, home = real_identity()
        if platform.system() != "Windows" and os.geteuid() == 0:
            raise SkillError("Run prepare-probe without sudo")
        db_dir = resolve_db_dir(args.db_dir, home)
        probe_root = Path(tempfile.mkdtemp(prefix="wechat-chat-decrypt-probe-", dir=private_temp_root()))
        if platform.system() != "Windows":
            probe_root.chmod(0o700)
        probe_home = probe_root / "home"
        database_format = "classic_sqlcipher_v3" if ((db_dir / "Msg").is_dir() and not (db_dir / "db_storage").is_dir()) else "wcdb_sqlcipher_v4"
        destination = probe_root / ("classic" if database_format.startswith("classic") else "db_storage")
        database_count = 0
        try:
            for source in database_files(db_dir):
                if not is_encrypted_database(source):
                    continue
                # Keep only page 1. The scanner needs the full encrypted page
                # to read its salt and validate candidate keys; no message
                # rows or plaintext payload are copied into the probe.
                with source.open("rb") as handle:
                    header = handle.read(PAGE_SIZE)
                target = destination / source.relative_to(db_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(header)
                target.chmod(0o600)
                database_count += 1
            if database_count == 0:
                raise SkillError("No encrypted WeChat databases found")
            manifest = {
                "schema": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by_uid": uid,
                "created_by_user": os.environ.get("USERNAME") or os.environ.get("USER") or "user",
                "db_dir": str(db_dir),
                "probe_root": str(probe_root),
                "probe_home": str(probe_home),
                "database_count": database_count,
                "scanner_sha256": SCANNER_SHA256 if platform.system() == "Darwin" else None,
                "scanner_db_dir": str(destination),
            }
            manifest_path = probe_root / "manifest.json"
            atomic_json(manifest_path, manifest)
        except Exception:
            shutil.rmtree(probe_root, ignore_errors=True)
            raise
        emit(
            {
                "ok": True,
                "database_count": database_count,
                "database_format": database_format,
                "manifest": str(manifest_path),
                "next_action": "extract_keys" if platform.system() == "Windows" else "sudo_extract_keys",
            }
        )
    except SkillError as exc:
        fail(str(exc))


def path_is_private_temp(path: Path, prefix: str) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return False
    root = private_temp_root()
    return root in resolved.parents and resolved.name.startswith(prefix)


def backup_state(state_dir: Path, uid: int, gid: int) -> Path | None:
    existing = [path for path in (state_dir / "config.json", state_dir / "all_keys.json") if path.is_file()]
    if not existing:
        return None
    backup = state_dir / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    backup.chmod(0o700)
    chown_if_posix(backup, uid, gid)
    for source in existing:
        target = backup / source.name
        shutil.copy2(source, target)
        target.chmod(0o600)
        chown_if_posix(target, uid, gid)
    return backup


def command_extract_keys(args: argparse.Namespace) -> None:
    probe_root: Path | None = None
    try:
        system = platform.system()
        if system == "Darwin":
            uid, gid, _, home = require_root()
        elif system == "Windows":
            uid, gid, _, home = real_identity()
        else:
            raise SkillError("Unsupported platform")
        if system == "Darwin" and platform.machine() != "arm64":
            raise SkillError("The bundled memory scanner is verified for Apple Silicon only")
        manifest_path = Path(args.manifest).resolve(strict=True)
        probe_root = manifest_path.parent
        if not path_is_private_temp(probe_root, "wechat-chat-decrypt-probe-"):
            raise SkillError("Unsafe probe manifest location")
        if system == "Darwin" and (manifest_path.stat().st_uid != uid or stat.S_IMODE(manifest_path.stat().st_mode) & 0o077):
            raise SkillError("Probe manifest ownership or permissions are unsafe")
        manifest = load_json(manifest_path)
        owner_ok = manifest.get("created_by_uid") == uid if system == "Darwin" else manifest.get("created_by_user") == home.name
        if manifest.get("schema") != 1 or not owner_ok:
            raise SkillError("Probe manifest does not belong to the current user")
        if Path(str(manifest.get("probe_root"))).resolve() != probe_root:
            raise SkillError("Probe manifest path mismatch")
        db_dir = Path(str(manifest.get("db_dir", ""))).resolve(strict=True)
        roots = [root.resolve() for root in expected_data_roots(home)]
        database_format = str(manifest.get("database_format", "wcdb_sqlcipher_v4"))
        valid_db_dir = db_dir.name == "db_storage" or ((db_dir / "Msg").is_dir() and not (db_dir / "db_storage").is_dir())
        if not valid_db_dir or not any(root in db_dir.parents for root in roots):
            raise SkillError("Probe database directory is outside the local WeChat data directory")
        probe_home = Path(str(manifest.get("probe_home", probe_root / "home"))).resolve()
        if system == "Darwin" and probe_root not in probe_home.parents:
            raise SkillError("Unsafe probe home")
        if system == "Darwin" and (not SCANNER_PATH.is_file() or sha256_file(SCANNER_PATH) != SCANNER_SHA256):
            raise SkillError("Bundled scanner hash mismatch")

        pids = [args.pid] if args.pid else wechat_pids()
        if len(pids) != 1 and args.pid:
            raise SkillError("Expected exactly one running WeChat process")
        if not pids:
            raise SkillError("Expected at least one running WeChat process")
        if system == "Windows":
            windows_meta = windows_wechat_metadata([pids[0]])
            compatibility = (windows_meta or {}).get("compatibility")
            if database_format == "classic_sqlcipher_v3" and compatibility != "verified_classic":
                raise SkillError(
                    f"Classic probe requires verified WeChat 3.9.11.25; detected {(windows_meta or {}).get('version') or 'unknown'}"
                )
            if database_format == "wcdb_sqlcipher_v4" and compatibility != "verified_modern":
                raise SkillError(
                    f"Modern Windows probe requires verified Weixin 4.1.8.101; detected {(windows_meta or {}).get('version') or 'unknown'}"
                )
        if system == "Darwin":
            app_path = find_wechat_app()
            if not app_path or not app_metadata(app_path)["get_task_allow"]:
                raise SkillError("WeChat is not re-signed with get-task-allow")

        scanner_output_dir = probe_root / "scanner-output"
        scanner_output_dir.mkdir(mode=0o700)
        environment = os.environ.copy()
        environment["HOME"] = str(probe_home)
        for key in ("SUDO_USER", "SUDO_UID", "SUDO_GID"):
            environment.pop(key, None)
        if system == "Darwin":
            command = [str(SCANNER_PATH), str(pids[0])]
        else:
            scanner_db_dir = Path(str(manifest.get("scanner_db_dir", ""))).resolve(strict=True)
            if probe_root not in scanner_db_dir.parents:
                raise SkillError("Unsafe Windows scanner database directory")
            environment["PYTHONPATH"] = str(VENDOR_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
            # The current Windows client splits work across several Weixin.exe
            # processes. Let the scanner inspect every process unless the user
            # explicitly supplied --pid; keys are accepted only after DB-HMAC
            # validation, so scanning helpers does not weaken correctness.
            command = [sys.executable, "-m", "wechat_cli.keys.scanner_windows", str(scanner_db_dir), str(scanner_output_dir / "all_keys.json")]
            if database_format == "classic_sqlcipher_v3":
                command.append("--legacy")
            if args.pid:
                command.extend(["--pid", str(args.pid)])
        result = run(command, timeout=300, env=environment, cwd=scanner_output_dir)
        combined = f"{result.stdout or ''}\n{result.stderr or ''}"
        if result.returncode != 0:
            if "task_for_pid" in combined:
                raise SkillError("task_for_pid failed; quit, re-sign, reopen and log in to WeChat")
            if system == "Windows" and any(token in combined.lower() for token in ("openprocess", "access is denied", "permission")):
                raise SkillError("Windows denied process-memory access; run WeChat and Codex/PowerShell at the same integrity level or use Administrator PowerShell")
            if system == "Windows":
                metadata = windows_wechat_metadata([pids[0]])
                version = (metadata or {}).get("version") or "unknown"
                raise SkillError(
                    f"No database key was found in the running Windows WeChat client {version}. The client may be unsupported or not fully logged in; keep encrypted data unchanged and try the compatible classic client path."
                )
            raise SkillError(f"Memory scanner failed with exit code {result.returncode}")
        scanner_keys = scanner_output_dir / "all_keys.json"
        if not scanner_keys.is_file():
            raise SkillError("Memory scanner did not create a key file")
        key_data = validate_key_data(load_json(scanner_keys))
        if database_format == "classic_sqlcipher_v3":
            if not any(Path(relative).parts[0].lower() == "msg" for relative in key_data):
                raise SkillError("No classic Msg database key was matched")
        elif not any(Path(relative).parts[0] == "message" for relative in key_data):
            raise SkillError("No message database key was matched")

        state_dir = home / ".wechat-cli"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o700)
        chown_if_posix(state_dir, uid, gid)
        backup = backup_state(state_dir, uid, gid)
        atomic_json(state_dir / "all_keys.json", key_data, uid=uid, gid=gid)
        atomic_json(
            state_dir / "config.json",
            {"db_dir": str(db_dir), "database_format": database_format},
            uid=uid,
            gid=gid,
        )
        atomic_json(
            state_dir / "skill_state.json",
            {
                "upstream_commit": UPSTREAM_COMMIT,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "matched_database_count": len(key_data),
                "database_format": database_format,
            },
            uid=uid,
            gid=gid,
        )
        shutil.rmtree(probe_root)
        probe_root = None
        emit(
            {
                "ok": True,
                "encrypted_database_count": int(manifest["database_count"]),
                "matched_database_count": len(key_data),
                "previous_state_backup": str(backup) if backup else None,
                "key_material_printed": False,
                "next_action": "verify",
            }
        )
    except (SkillError, subprocess.TimeoutExpired) as exc:
        fail(str(exc))
    finally:
        if probe_root and path_is_private_temp(probe_root, "wechat-chat-decrypt-probe-"):
            shutil.rmtree(probe_root, ignore_errors=True)


def key_matches_page(enc_key: bytes, page: bytes) -> bool:
    if len(enc_key) != 32 or len(page) != PAGE_SIZE:
        return False
    salt = page[:16]
    mac_salt = bytes(value ^ 0x3A for value in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)
    digest = hmac.new(mac_key, page[16 : PAGE_SIZE - RESERVED_SIZE + 16], hashlib.sha512)
    digest.update(struct.pack("<I", 1))
    return hmac.compare_digest(digest.digest(), page[PAGE_SIZE - 64 :])


def key_matches_classic_page(enc_key: bytes, page: bytes) -> bool:
    """Validate a classic 3.x SQLCipher v3 page (SHA-1/HMAC layout)."""
    if len(enc_key) != 32 or len(page) != PAGE_SIZE:
        return False
    salt = page[:16]
    derived = hashlib.pbkdf2_hmac("sha1", enc_key, salt, 64000, 32)
    mac_salt = bytes(value ^ 0x3A for value in salt)
    derived = hashlib.pbkdf2_hmac("sha1", derived, mac_salt, 2, 32)
    digest = hmac.new(derived, page[16 : PAGE_SIZE - 48], hashlib.sha1)
    digest.update(struct.pack("<I", 1))
    return hmac.compare_digest(digest.digest(), page[PAGE_SIZE - 48 : PAGE_SIZE - 28])


def decrypt_classic_database(source: Path, destination: Path, enc_key: bytes) -> None:
    """Decrypt a classic WeChat SQLCipher v3 database to a temporary SQLite file."""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        try:
            from Cryptodome.Cipher import AES
        except ImportError as exc:
            raise SkillError("Classic Windows decryption needs pycryptodome; rerun bootstrap") from exc
    data = source.read_bytes()
    if len(data) < PAGE_SIZE:
        raise SkillError("Classic database is too small for SQLite validation")
    salt = data[:16]
    derived = hashlib.pbkdf2_hmac("sha1", enc_key, salt, 64000, 32)
    with destination.open("wb") as handle:
        handle.write(SQLITE_HEADER)
        for offset in range(0, len(data), PAGE_SIZE):
            page = data[offset : offset + PAGE_SIZE] if offset else data[16 : PAGE_SIZE]
            if len(page) < 48:
                break
            handle.write(AES.new(derived, AES.MODE_CBC, page[-48:-32]).decrypt(page[:-48]))
            handle.write(page[-48:])


def import_crypto_helpers():
    sys.path.insert(0, str(VENDOR_ROOT))
    try:
        from wechat_cli.core.crypto import decrypt_wal, full_decrypt
    except ImportError as exc:
        bootstrap = "scripts\\bootstrap.ps1" if platform.system() == "Windows" else "scripts/bootstrap.sh"
        raise SkillError(f"Runtime dependencies are missing; run {bootstrap}") from exc
    return full_decrypt, decrypt_wal


def command_verify(_: argparse.Namespace) -> None:
    try:
        _, _, _, home = real_identity()
        state_dir = home / ".wechat-cli"
        config = load_json(state_dir / "config.json")
        keys = validate_key_data(load_json(state_dir / "all_keys.json"))
        db_dir = Path(str(config.get("db_dir", ""))).resolve(strict=True)
        roots = [root.resolve() for root in expected_data_roots(home)]
        if not any(root in db_dir.parents for root in roots):
            raise SkillError("Configured database directory is outside the local WeChat data directory")

        if config.get("database_format") == "classic_sqlcipher_v3":
            verified_paths: list[Path] = []
            candidates: list[tuple[int, str, Path, bytes]] = []
            for relative_path, key_info in keys.items():
                database_path = (db_dir / relative_path).resolve()
                if db_dir not in database_path.parents or not database_path.is_file():
                    continue
                enc_key = bytes.fromhex(key_info["enc_key"])
                with database_path.open("rb") as handle:
                    page = handle.read(PAGE_SIZE)
                if not key_matches_classic_page(enc_key, page):
                    continue
                verified_paths.append(database_path)
                if relative_path.replace("\\", "/").lower().startswith("msg/"):
                    candidates.append((database_path.stat().st_size, relative_path, database_path, enc_key))
            if not candidates:
                raise SkillError("No verified classic Msg database is available for SQLite validation")
            _, _, classic_db, classic_key = max(candidates)
            with tempfile.TemporaryDirectory(prefix="wechat-decrypt-verify-", dir=private_temp_root()) as temp_dir:
                decrypted_path = Path(temp_dir) / "ChatMsg.db"
                decrypt_classic_database(classic_db, decrypted_path, classic_key)
                connection = sqlite3.connect(f"file:{decrypted_path}?mode=ro", uri=True)
                try:
                    quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()[0]
                    table_count = connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                    ).fetchone()[0]
                finally:
                    connection.close()
            if quick_check != "ok":
                raise SkillError(f"SQLite quick_check failed: {quick_check}")
            emit(
                {
                    "ok": True,
                    "database_format": "classic_sqlcipher_v3",
                    "saved_key_count": len(keys),
                    "hmac_verified_count": len(verified_paths),
                    "message_database_key_count": len(candidates),
                    "sqlite_quick_check": quick_check,
                    "sqlite_table_count": table_count,
                    "message_rows_read": False,
                    "plaintext_temp_removed": True,
                }
            )
            return

        verified_paths: list[Path] = []
        message_candidates: list[tuple[int, str, Path, bytes]] = []
        for relative_path, key_info in keys.items():
            database_path = (db_dir / relative_path).resolve()
            if db_dir not in database_path.parents or not database_path.is_file():
                continue
            enc_key = bytes.fromhex(key_info["enc_key"])
            with database_path.open("rb") as handle:
                page = handle.read(PAGE_SIZE)
            if not key_matches_page(enc_key, page):
                continue
            verified_paths.append(database_path)
            normalized = relative_path.replace("\\", "/")
            # Fresh/quiet accounts can have message shards well below 1 MiB;
            # page/HMAC validation is the correctness check, not file size.
            if normalized.startswith("message/") and database_path.stat().st_size >= PAGE_SIZE:
                message_candidates.append((database_path.stat().st_size, relative_path, database_path, enc_key))
        if not message_candidates:
            raise SkillError("No verified message database is available for SQLite validation")

        full_decrypt, decrypt_wal = import_crypto_helpers()
        _, _, message_db, message_key = min(message_candidates)
        wal_path = Path(f"{message_db}-wal")
        with tempfile.TemporaryDirectory(prefix="wechat-decrypt-verify-", dir=private_temp_root()) as temp_dir:
            decrypted_path = Path(temp_dir) / "message.db"
            full_decrypt(str(message_db), str(decrypted_path), message_key)
            if wal_path.is_file():
                decrypt_wal(str(wal_path), str(decrypted_path), message_key)
            connection = sqlite3.connect(f"file:{decrypted_path}?mode=ro", uri=True)
            try:
                quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()[0]
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            finally:
                connection.close()
        if quick_check != "ok":
            raise SkillError(f"SQLite quick_check failed: {quick_check}")
        emit(
            {
                "ok": True,
                "saved_key_count": len(keys),
                "hmac_verified_count": len(verified_paths),
                "message_database_key_count": len(message_candidates),
                "sqlite_quick_check": quick_check,
                "sqlite_table_count": table_count,
                "message_rows_read": False,
                "plaintext_temp_removed": True,
            }
        )
    except (SkillError, FileNotFoundError, ValueError) as exc:
        fail(str(exc))


def update_guard_status(app_path: Path) -> dict[str, object]:
    target_status = []
    for relative in SPARKLE_EXECUTABLES:
        path = app_path / relative
        target_status.append(
            {
                "relative_path": relative,
                "exists": path.exists(),
                "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}" if path.exists() else None,
                "immutable": immutable(path),
            }
        )
    return {
        "app_immutable": immutable(app_path),
        "targets": target_status,
        "hard_blocked": immutable(app_path)
        and all(target["exists"] and target["mode"] == "0600" and target["immutable"] for target in target_status),
    }


def command_update_guard(args: argparse.Namespace) -> None:
    try:
        app_path = find_wechat_app()
        if not app_path:
            raise SkillError("WeChat.app not found")
        if args.action == "status":
            emit({"ok": True, **update_guard_status(app_path)})
            return

        if platform.system() == "Windows":
            raise SkillError("update-guard is only applicable to the macOS Sparkle updater")
        uid, gid, user, home = require_root()
        state_dir = home / ".wechat-cli"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_dir.chmod(0o700)
        chown_if_posix(state_dir, uid, gid)
        manifest_path = state_dir / "update_guard.json"

        if args.action == "block":
            clear_immutable_flags(app_path)
            if not manifest_path.exists():
                original = {}
                for relative in SPARKLE_EXECUTABLES:
                    path = app_path / relative
                    if path.exists():
                        original[relative] = {
                            "mode": stat.S_IMODE(path.stat().st_mode),
                            "flags": getattr(path.stat(), "st_flags", 0),
                        }
                atomic_json(
                    manifest_path,
                    {"schema": 1, "app_path": str(app_path), "original": original},
                    uid=uid,
                    gid=gid,
                )
            for relative in SPARKLE_EXECUTABLES:
                path = app_path / relative
                if path.exists():
                    path.chmod(0o600)
                    os.chflags(path, path.stat().st_flags | stat.UF_IMMUTABLE)
            os.chflags(app_path, app_path.stat().st_flags | stat.UF_IMMUTABLE)
            set_update_preferences(user, enabled=False)
            emit({"ok": True, **update_guard_status(app_path), "manifest": str(manifest_path)})
            return

        clear_immutable_flags(app_path)
        if manifest_path.is_file():
            manifest = load_json(manifest_path)
            original = manifest.get("original", {})
            if isinstance(original, dict):
                for relative, values in original.items():
                    path = app_path / relative
                    if path.exists() and isinstance(values, dict):
                        path.chmod(int(values.get("mode", 0o755)))
                        os.chflags(path, int(values.get("flags", 0)) & ~stat.UF_IMMUTABLE)
        if args.enable_automatic_updates:
            set_update_preferences(user, enabled=True)
        emit({"ok": True, **update_guard_status(app_path), "automatic_updates_enabled": args.enable_automatic_updates})
    except (SkillError, OSError) as exc:
        fail(str(exc))


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def command_cleanup(args: argparse.Namespace) -> None:
    try:
        uid, _, _, home = real_identity()
        removed: list[dict[str, object]] = []
        candidates = [Path(tempfile.gettempdir()) / "wechat_cli_cache"]
        temp_root = private_temp_root()
        candidates.extend(temp_root.glob("wechat-cli-safe.*"))
        candidates.extend(temp_root.glob("wechat-decrypt-verify-*"))
        if args.include_probes:
            candidates.extend(temp_root.glob("wechat-chat-decrypt-probe-*"))
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            if platform.system() != "Windows" and resolved.stat().st_uid != uid:
                continue
            size = directory_size(resolved)
            shutil.rmtree(resolved)
            removed.append({"path": str(resolved), "bytes": size})
        persistent = home / ".wechat-cli" / "decrypted"
        if args.include_persistent and persistent.is_dir():
            size = directory_size(persistent)
            shutil.rmtree(persistent)
            removed.append({"path": str(persistent), "bytes": size})
        emit(
            {
                "ok": True,
                "removed_directory_count": len(removed),
                "removed_bytes": sum(int(item["bytes"]) for item in removed),
                "removed": removed,
                "keys_preserved": True,
            }
        )
    except (SkillError, OSError) as exc:
        fail(str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="Inspect compatibility without changing anything")
    preflight.set_defaults(func=command_preflight)

    inspect_parser = subparsers.add_parser("inspect-dmg", help="Validate a user-provided WeChat DMG")
    inspect_parser.add_argument("--dmg", required=True)
    inspect_parser.set_defaults(func=command_inspect_dmg)

    install = subparsers.add_parser("install-dmg", help="Install a validated supported WeChat DMG")
    install.add_argument("--dmg", required=True)
    install.add_argument("--confirm-data-backup", action="store_true")
    install.add_argument("--confirm-wechat-closed", action="store_true")
    install.set_defaults(func=command_install_dmg)

    resign = subparsers.add_parser("resign", help="Add get-task-allow while preserving entitlements")
    resign.set_defaults(func=command_resign)

    prepare = subparsers.add_parser("prepare-probe", help="Create a private DB-header mirror")
    prepare.add_argument("--db-dir")
    prepare.set_defaults(func=command_prepare_probe)

    extract = subparsers.add_parser("extract-keys", help="Run the memory scanner without printing keys")
    extract.add_argument("--manifest", required=True)
    extract.add_argument("--pid", type=int)
    extract.set_defaults(func=command_extract_keys)

    verify = subparsers.add_parser("verify", help="Verify HMACs and one SQLite database")
    verify.set_defaults(func=command_verify)

    guard = subparsers.add_parser("update-guard", help="Manage the optional hard update block")
    guard.add_argument("action", choices=("status", "block", "unblock"))
    guard.add_argument("--enable-automatic-updates", action="store_true")
    guard.set_defaults(func=command_update_guard)

    cleanup = subparsers.add_parser("cleanup", help="Remove temporary plaintext caches")
    cleanup.add_argument("--include-probes", action="store_true")
    cleanup.add_argument("--include-persistent", action="store_true")
    cleanup.set_defaults(func=command_cleanup)
    return parser


def main() -> None:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except SkillError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
