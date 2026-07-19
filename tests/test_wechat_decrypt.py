from __future__ import annotations

import hashlib
import hmac
import importlib.util
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_decrypt.py"
SPEC = importlib.util.spec_from_file_location("wechat_decrypt", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VersionTests(unittest.TestCase):
    def test_verified_version(self) -> None:
        self.assertEqual(MODULE.classify_wechat_version("4.1.8", "37261"), "verified")

    def test_newer_version_is_blocked(self) -> None:
        self.assertEqual(MODULE.classify_wechat_version("4.1.12", "40000"), "unsupported_newer")

    def test_older_four_x_is_explicitly_unverified(self) -> None:
        self.assertEqual(
            MODULE.classify_wechat_version("4.1.7", "36000"),
            "upstream_compatible_unverified",
        )


class KeyValidationTests(unittest.TestCase):
    def test_valid_key_map(self) -> None:
        key = "ab" * 32
        payload = {"message/example.db": {"enc_key": key}}
        self.assertEqual(MODULE.validate_key_data(payload), payload)

    def test_parent_path_is_rejected(self) -> None:
        with self.assertRaises(MODULE.SkillError):
            MODULE.validate_key_data({"../outside.db": {"enc_key": "ab" * 32}})

    def test_bad_key_is_rejected(self) -> None:
        with self.assertRaises(MODULE.SkillError):
            MODULE.validate_key_data({"message/example.db": {"enc_key": "not-a-key"}})


class PageVerificationTests(unittest.TestCase):
    def test_page_hmac(self) -> None:
        key = bytes(range(32))
        page = bytearray(MODULE.PAGE_SIZE)
        page[:16] = bytes(range(16, 32))
        for index in range(16, MODULE.PAGE_SIZE - MODULE.RESERVED_SIZE + 16):
            page[index] = index % 251
        mac_salt = bytes(value ^ 0x3A for value in page[:16])
        mac_key = hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, dklen=32)
        digest = hmac.new(
            mac_key,
            page[16 : MODULE.PAGE_SIZE - MODULE.RESERVED_SIZE + 16],
            hashlib.sha512,
        )
        digest.update(struct.pack("<I", 1))
        page[MODULE.PAGE_SIZE - 64 :] = digest.digest()
        self.assertTrue(MODULE.key_matches_page(key, bytes(page)))

        page[100] ^= 0x01
        self.assertFalse(MODULE.key_matches_page(key, bytes(page)))


class FilesystemSafetyTests(unittest.TestCase):
    def test_private_probe_path(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="wechat-chat-decrypt-probe-", dir="/private/tmp"))
        try:
            path.chmod(stat.S_IRWXU)
            self.assertTrue(MODULE.path_is_private_temp(path, "wechat-chat-decrypt-probe-"))
        finally:
            shutil.rmtree(path)


if __name__ == "__main__":
    unittest.main()
