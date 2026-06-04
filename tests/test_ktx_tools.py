"""Tests for ktx_tools — platform detection, tool discovery, command building,
and macOS pbzx payload decoding.

Run with either:
    python -m unittest discover -s tests
    pytest tests/
"""

import os
import sys
import lzma
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# These tests run outside Blender. ktx_tools only imports bpy lazily inside
# functions, so it imports fine as a plain top-level module once the addon root
# is on sys.path.
ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)

import ktx_tools  # noqa: E402


def flag_value(cmd, flag):
    """Return the argument immediately following ``flag`` in a command list,
    or None if the flag is absent / has no following value."""
    try:
        idx = cmd.index(flag)
    except ValueError:
        return None
    return cmd[idx + 1] if idx + 1 < len(cmd) else None


# ---------------------------------------------------------------------------
# Platform / download matrix
# ---------------------------------------------------------------------------

class GetPlatformInfoTests(unittest.TestCase):
    def _info(self, system, machine):
        with mock.patch("ktx_tools.platform.system", return_value=system), \
             mock.patch("ktx_tools.platform.machine", return_value=machine):
            return ktx_tools.get_platform_info()

    def test_normalizes_amd64_to_x86_64(self):
        self.assertEqual(self._info("Windows", "AMD64"), ("Windows", "x86_64"))

    def test_normalizes_aarch64_to_arm64(self):
        self.assertEqual(self._info("Linux", "aarch64"), ("Linux", "arm64"))

    def test_normalizes_apple_arm64(self):
        self.assertEqual(self._info("Darwin", "arm64"), ("Darwin", "arm64"))

    def test_passes_unknown_arch_through(self):
        self.assertEqual(self._info("Linux", "riscv64"), ("Linux", "riscv64"))


class GetDownloadInfoTests(unittest.TestCase):
    def _download(self, os_name, arch):
        with mock.patch("ktx_tools.get_platform_info", return_value=(os_name, arch)):
            return ktx_tools.get_download_info()

    def test_linux_x86_64_uses_tar_bz2(self):
        url, archive_type, subdir = self._download("Linux", "x86_64")
        self.assertTrue(url.endswith(".tar.bz2"))
        self.assertEqual(archive_type, "tar.bz2")
        self.assertIn("Linux-x86_64", url)
        self.assertEqual(subdir, f"KTX-Software-{ktx_tools.KTX_VERSION}-Linux-x86_64")

    def test_linux_arm64(self):
        url, archive_type, _ = self._download("Linux", "arm64")
        self.assertIn("Linux-arm64", url)
        self.assertEqual(archive_type, "tar.bz2")

    def test_windows_uses_exe_installer(self):
        url, archive_type, subdir = self._download("Windows", "x86_64")
        self.assertTrue(url.endswith(".exe"))
        self.assertEqual(archive_type, "exe")
        self.assertIn("Windows-x64", url)
        self.assertIsNone(subdir)

    def test_macos_arm64_uses_pkg(self):
        url, archive_type, _ = self._download("Darwin", "arm64")
        self.assertTrue(url.endswith(".pkg"))
        self.assertEqual(archive_type, "pkg")
        self.assertIn("Darwin-arm64", url)

    def test_macos_x86_64_uses_pkg(self):
        url, _, _ = self._download("Darwin", "x86_64")
        self.assertIn("Darwin-x86_64", url)

    def test_unsupported_arch_returns_none(self):
        self.assertEqual(self._download("Linux", "riscv64"), (None, None, None))

    def test_url_contains_pinned_version(self):
        url, _, _ = self._download("Linux", "x86_64")
        self.assertIn(f"v{ktx_tools.KTX_VERSION}", url)


# ---------------------------------------------------------------------------
# Tool discovery — system fallback (Issue #8)
# ---------------------------------------------------------------------------

class GetSystemToolPathTests(unittest.TestCase):
    def test_prefers_path_lookup(self):
        with mock.patch("ktx_tools.shutil.which", return_value="/somewhere/toktx"):
            result = ktx_tools.get_system_tool_path("toktx")
        self.assertEqual(result, Path("/somewhere/toktx"))

    def test_returns_none_when_nowhere(self):
        # A name that won't exist in /usr/local/bin, /opt/homebrew/bin, /usr/bin.
        with mock.patch("ktx_tools.shutil.which", return_value=None):
            result = ktx_tools.get_system_tool_path("toktx_definitely_not_real_xyz")
        self.assertIsNone(result)


class GetToolPathTests(unittest.TestCase):
    def test_falls_back_to_system_when_not_bundled(self):
        with tempfile.TemporaryDirectory() as d:
            # Bundled bin dir exists but contains no toktx.
            with mock.patch("ktx_tools.get_tools_directory", return_value=Path(d)), \
                 mock.patch("ktx_tools.get_platform_info", return_value=("Linux", "x86_64")), \
                 mock.patch("ktx_tools.get_system_tool_path",
                            return_value=Path("/usr/local/bin/toktx")) as sys_lookup:
                result = ktx_tools.get_tool_path("toktx")
        self.assertEqual(result, Path("/usr/local/bin/toktx"))
        sys_lookup.assert_called_once_with("toktx")

    def test_prefers_bundled_executable(self):
        with tempfile.TemporaryDirectory() as d:
            bundled = Path(d) / "toktx"
            bundled.write_text("#!/bin/sh\n")
            bundled.chmod(0o755)
            with mock.patch("ktx_tools.get_tools_directory", return_value=Path(d)), \
                 mock.patch("ktx_tools.get_platform_info", return_value=("Linux", "x86_64")), \
                 mock.patch("ktx_tools.get_system_tool_path") as sys_lookup:
                result = ktx_tools.get_tool_path("toktx")
        self.assertEqual(result, bundled)
        sys_lookup.assert_not_called()

    def test_windows_appends_exe_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("ktx_tools.get_tools_directory", return_value=Path(d)), \
                 mock.patch("ktx_tools.get_platform_info", return_value=("Windows", "x86_64")), \
                 mock.patch("ktx_tools.get_system_tool_path",
                            return_value=None) as sys_lookup:
                ktx_tools.get_tool_path("toktx")
        sys_lookup.assert_called_once_with("toktx.exe")


# ---------------------------------------------------------------------------
# run_toktx command construction (Issue #7 normal-map handling lives here)
# ---------------------------------------------------------------------------

class RunToktxCommandTests(unittest.TestCase):
    def _build_cmd(self, options):
        """Invoke run_toktx with the executable + subprocess stubbed, returning
        the command list that would have been executed."""
        fake_result = mock.Mock(returncode=0, stderr="")
        with mock.patch("ktx_tools.get_tool_path", return_value=Path("/fake/toktx")), \
             mock.patch("ktx_tools.get_tool_environment", return_value={}), \
             mock.patch("ktx_tools.subprocess.run", return_value=fake_result) as run:
            success, error = ktx_tools.run_toktx(
                Path("/in.png"), Path("/out.ktx2"), options)
        self.assertTrue(success, error)
        return run.call_args.args[0]

    def test_aborts_when_tool_missing(self):
        with mock.patch("ktx_tools.get_tool_path", return_value=None):
            success, error = ktx_tools.run_toktx(Path("/in.png"), Path("/out.ktx2"), {})
        self.assertFalse(success)
        self.assertIn("not found", error)

    def test_input_and_output_are_last_two_args(self):
        cmd = self._build_cmd({})
        self.assertEqual(cmd[-2:], ["/out.ktx2", "/in.png"])

    # --- encoder selection ---

    def test_default_is_etc1s(self):
        cmd = self._build_cmd({})
        self.assertEqual(flag_value(cmd, "--encode"), "etc1s")
        self.assertIn("--qlevel", cmd)

    def test_uastc_encoder(self):
        cmd = self._build_cmd({"format": "UASTC"})
        self.assertEqual(flag_value(cmd, "--encode"), "uastc")
        self.assertIn("--uastc_quality", cmd)

    def test_astc_target_format(self):
        cmd = self._build_cmd({"target_format": "ASTC", "astc_block_size": "4x4"})
        self.assertEqual(flag_value(cmd, "--encode"), "astc")
        self.assertEqual(flag_value(cmd, "--astc_blk_d"), "4x4")

    # --- normal map mode (Issue #7) ---

    def test_normal_mode_three_channel_keeps_rgb1_swizzle_and_target_type(self):
        cmd = self._build_cmd({"normal_mode": True, "normal_two_channel": False})
        self.assertIn("--normal_mode", cmd)
        # 3-channel safe path: swizzle to rgb1 and keep an explicit target type
        # so standard glTF viewers / the addon's decoder get a normal RGB map.
        self.assertEqual(flag_value(cmd, "--input_swizzle"), "rgb1")
        self.assertIn("--target_type", cmd)

    def test_normal_mode_two_channel_omits_swizzle_and_target_type(self):
        cmd = self._build_cmd({"normal_mode": True, "normal_two_channel": True})
        self.assertIn("--normal_mode", cmd)
        # 2-channel path lets toktx store its optimized X+Y map; forcing
        # target_type/swizzle would clobber that.
        self.assertNotIn("--input_swizzle", cmd)
        self.assertNotIn("--target_type", cmd)

    def test_no_normal_mode_by_default(self):
        cmd = self._build_cmd({})
        self.assertNotIn("--normal_mode", cmd)
        self.assertNotIn("--input_swizzle", cmd)
        self.assertIn("--target_type", cmd)

    def test_oetf_assigned(self):
        cmd = self._build_cmd({"oetf": "linear"})
        self.assertEqual(flag_value(cmd, "--assign_oetf"), "linear")

    def test_mipmaps_flag(self):
        self.assertIn("--genmipmap", self._build_cmd({"mipmaps": True}))
        self.assertNotIn("--genmipmap", self._build_cmd({"mipmaps": False}))

    def test_subprocess_failure_is_reported(self):
        fail = mock.Mock(returncode=1, stderr="boom")
        with mock.patch("ktx_tools.get_tool_path", return_value=Path("/fake/toktx")), \
             mock.patch("ktx_tools.get_tool_environment", return_value={}), \
             mock.patch("ktx_tools.subprocess.run", return_value=fail):
            success, error = ktx_tools.run_toktx(Path("/in.png"), Path("/out.ktx2"), {})
        self.assertFalse(success)
        self.assertIn("boom", error)


# ---------------------------------------------------------------------------
# macOS pbzx payload decoding (Issue #8)
# ---------------------------------------------------------------------------

def _build_pbzx(raw, chunk_size=64):
    """Construct a minimal Apple pbzx container holding ``raw``.

    Layout: b'pbzx' + 8 flag bytes + repeated (16-byte header of
    >QQ(uncompressed, compressed) + chunk). xz-compressed chunks carry the
    standard xz magic so the decoder lzma-decompresses them.
    """
    out = bytearray(b"pbzx")
    out += struct.pack(">Q", chunk_size)  # flags field (ignored by decoder)
    for i in range(0, len(raw), chunk_size):
        piece = raw[i:i + chunk_size]
        compressed = lzma.compress(piece)  # FORMAT_XZ -> \xfd7zXZ\x00 magic
        out += struct.pack(">QQ", len(piece), len(compressed))
        out += compressed
    return bytes(out)


class DecodePbzxTests(unittest.TestCase):
    def test_roundtrip_multichunk(self):
        original = b"normal map texture data " * 50  # forces multiple chunks
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d) / "Payload"
            decoded = Path(d) / "payload.cpio"
            payload.write_bytes(_build_pbzx(original, chunk_size=64))
            ok = ktx_tools._decode_pbzx(payload, decoded)
            self.assertTrue(ok)
            self.assertEqual(decoded.read_bytes(), original)

    def test_handles_stored_uncompressed_chunk(self):
        # A chunk that is not xz-wrapped must be copied verbatim.
        raw_chunk = b"raw-not-xz"
        payload_bytes = bytearray(b"pbzx") + struct.pack(">Q", 0)
        payload_bytes += struct.pack(">QQ", len(raw_chunk), len(raw_chunk))
        payload_bytes += raw_chunk
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d) / "Payload"
            decoded = Path(d) / "out.cpio"
            payload.write_bytes(bytes(payload_bytes))
            ok = ktx_tools._decode_pbzx(payload, decoded)
            self.assertTrue(ok)
            self.assertEqual(decoded.read_bytes(), raw_chunk)

    def test_rejects_non_pbzx_magic(self):
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d) / "Payload"
            decoded = Path(d) / "out.cpio"
            payload.write_bytes(b"\x1f\x8b not pbzx")
            ok = ktx_tools._decode_pbzx(payload, decoded)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
