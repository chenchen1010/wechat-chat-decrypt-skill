"""Windows 密钥提取 — 扫描 WeChat.exe / Weixin.exe 进程内存"""

import ctypes
import ctypes.wintypes as wt
import functools
import os
import re
import subprocess
import time
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import struct

from .common import collect_db_files, scan_memory_for_keys, cross_verify_keys, save_results

print = functools.partial(print, flush=True)

kernel32 = ctypes.windll.kernel32
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD), ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_pad2", wt.DWORD),
    ]


def _get_pids():
    """返回 3.x/4.x 客户端进程的 (pid, mem_kb) 列表，按内存降序。"""
    pids = []
    seen = set()
    for image_name in ("Weixin.exe", "WeChat.exe"):
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True)
        for line in r.stdout.strip().split('\n'):
            if not line.strip():
                continue
            p = line.strip('"').split('","')
            if len(p) >= 5:
                pid = int(p[1])
                if pid in seen:
                    continue
                mem = int(p[4].replace(',', '').replace(' K', '').strip() or '0')
                pids.append((pid, mem))
                seen.add(pid)
    if not pids:
        raise RuntimeError("WeChat.exe / Weixin.exe 未运行")
    pids.sort(key=lambda x: x[1], reverse=True)
    for pid, mem in pids:
        print(f"[+] WeChat PID={pid} ({mem // 1024}MB)")
    return pids


def _read_mem(h, addr, sz):
    buf = ctypes.create_string_buffer(sz)
    n = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, sz, ctypes.byref(n)):
        return buf.raw[:n.value]
    return None


def _enum_regions(h):
    regs = []
    addr = 0
    mbi = MBI()
    while addr < 0x7FFFFFFFFFFF:
        if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and 0 < mbi.RegionSize < 500 * 1024 * 1024:
            regs.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return regs


def extract_keys(db_dir, output_path, pid=None):
    """提取 Windows 微信数据库密钥。

    Args:
        db_dir: 微信数据库目录
        output_path: all_keys.json 输出路径
        pid: 可选，指定 PID（默认自动检测所有 Weixin.exe）

    Returns:
        dict: salt_hex -> enc_key_hex 映射
    """
    print("=" * 60)
    print("  提取所有微信数据库密钥")
    print("=" * 60)

    db_files, salt_to_dbs = collect_db_files(db_dir)

    print(f"\n找到 {len(db_files)} 个数据库, {len(salt_to_dbs)} 个不同的salt")
    for salt_hex, dbs in sorted(salt_to_dbs.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"  salt {salt_hex}: {', '.join(dbs)}")

    pids = _get_pids() if pid is None else [(pid, 0)]

    hex_re = re.compile(b"x'([0-9a-fA-F]{64,192})'")
    key_map = {}
    remaining_salts = set(salt_to_dbs.keys())
    all_hex_matches = 0
    t0 = time.time()

    for pid_val, mem_kb in pids:
        h = kernel32.OpenProcess(0x0010 | 0x0400, False, pid_val)
        if not h:
            print(f"[WARN] 无法打开进程 PID={pid_val}，跳过")
            continue

        try:
            regions = _enum_regions(h)
            total_bytes = sum(s for _, s in regions)
            total_mb = total_bytes / 1024 / 1024
            print(f"\n[*] 扫描 PID={pid_val} ({total_mb:.0f}MB, {len(regions)} 区域)")

            scanned_bytes = 0
            for reg_idx, (base, size) in enumerate(regions):
                data = _read_mem(h, base, size)
                scanned_bytes += size
                if not data:
                    continue

                all_hex_matches += scan_memory_for_keys(
                    data, hex_re, db_files, salt_to_dbs,
                    key_map, remaining_salts, base, pid_val, print,
                )

                if (reg_idx + 1) % 200 == 0:
                    elapsed = time.time() - t0
                    progress = scanned_bytes / total_bytes * 100 if total_bytes else 100
                    print(
                        f"  [{progress:.1f}%] {len(key_map)}/{len(salt_to_dbs)} salts matched, "
                        f"{all_hex_matches} hex patterns, {elapsed:.1f}s"
                    )
        finally:
            kernel32.CloseHandle(h)

        if not remaining_salts:
            print(f"\n[+] 所有密钥已找到，跳过剩余进程")
            break

    elapsed = time.time() - t0
    print(f"\n扫描完成: {elapsed:.1f}s, {len(pids)} 个进程, {all_hex_matches} hex模式")

    cross_verify_keys(db_files, salt_to_dbs, key_map, print)
    return save_results(db_files, salt_to_dbs, key_map, output_path, print)


def _legacy_read(handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    count = ctypes.c_size_t()
    if kernel32.ReadProcessMemory(handle, ctypes.c_uint64(address), buffer, size, ctypes.byref(count)):
        return buffer.raw[:count.value]
    return None


def _legacy_module(handle):
    """Return (base, size) for the classic client's WeChatWin.dll."""
    psapi = ctypes.windll.psapi
    class ModuleInfo(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("size", wt.DWORD), ("entry", ctypes.c_void_p)]
    modules = (ctypes.c_void_p * 1024)()
    needed = wt.DWORD()
    if not psapi.EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3):
        return None
    count = needed.value // ctypes.sizeof(ctypes.c_void_p)
    for module in modules[:count]:
        name = ctypes.create_unicode_buffer(1024)
        if not psapi.GetModuleFileNameExW(handle, module, name, len(name)):
            continue
        if Path(name.value).name.casefold() != "wechatwin.dll":
            continue
        info = ModuleInfo()
        if psapi.GetModuleInformation(handle, module, ctypes.byref(info), ctypes.sizeof(info)):
            return int(info.base), int(info.size)
    return None


def _legacy_valid(key, database):
    try:
        page = Path(database).read_bytes()[:4096]
    except OSError:
        return False
    if len(page) != 4096 or page[:16] == b"SQLite format 3\x00":
        return False
    salt = page[:16]
    derived = hashlib.pbkdf2_hmac("sha1", key, salt, 64000, 32)
    derived = hashlib.pbkdf2_hmac("sha1", derived, bytes(value ^ 0x3A for value in salt), 2, 32)
    digest = hmac.new(derived, page[16:4048], hashlib.sha1)
    digest.update(b"\x01\x00\x00\x00")
    return hmac.compare_digest(digest.digest(), page[4048:4068])


def extract_legacy_keys(db_dir, output_path, pid=None):
    """Scan classic WeChat.exe's WeChatWin.dll pointer layout (SQLCipher v3)."""
    root = Path(db_dir).resolve()
    databases = [path for path in root.rglob("*.db") if path.is_file() and path.stat().st_size >= 4096]
    pids = [pid] if pid else [item[0] for item in _get_pids()]
    if not databases or not pids:
        raise RuntimeError("classic WeChat database or WeChat.exe process not found")
    key = None
    for process_id in pids:
        handle = kernel32.OpenProcess(0x0010 | 0x0400, False, process_id)
        if not handle:
            continue
        try:
            module = _legacy_module(handle)
            image = _legacy_read(handle, module[0], module[1]) if module else None
            if not image:
                continue
            markers = []
            for marker in (b"iphone\x00", b"android\x00", b"ipad\x00"):
                offset = 0
                while True:
                    offset = image.find(marker, offset)
                    if offset < 0:
                        break
                    markers.append(module[0] + offset)
                    offset += 1
            for address in sorted(markers, reverse=True):
                for candidate in range(address, max(module[0], address - 2000), -8):
                    pointer = _legacy_read(handle, candidate, 8)
                    if not pointer or len(pointer) != 8:
                        continue
                    candidate_key = _legacy_read(handle, struct.unpack("<Q", pointer)[0], 32)
                    if candidate_key and _legacy_valid(candidate_key, databases[0]):
                        key = candidate_key
                        break
                if key:
                    break
        finally:
            kernel32.CloseHandle(handle)
        if key:
            break
    if not key:
        raise RuntimeError("classic WeChat key was not found or did not validate")
    payload = {
        str(path.relative_to(root)).replace(os.sep, "/"): {"enc_key": key.hex()}
        for path in databases
    }
    Path(output_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan a running Weixin.exe process for local database keys")
    parser.add_argument("db_dir")
    parser.add_argument("output_path")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--legacy", action="store_true", help="use classic WeChat.exe SQLCipher v3 pointer scanner")
    cli_args = parser.parse_args()
    if cli_args.legacy:
        extract_legacy_keys(cli_args.db_dir, cli_args.output_path, pid=cli_args.pid)
    else:
        extract_keys(cli_args.db_dir, cli_args.output_path, pid=cli_args.pid)
