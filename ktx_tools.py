# Copyright 2024 The glTF-Blender-IO authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
KTX Tools Management

Handles downloading, extracting, and locating the KTX-Software command-line tools
for encoding and decoding KTX2 textures.
"""

import os
import sys
import platform
import subprocess
import tempfile
import shutil
from pathlib import Path

# KTX-Software version to download
KTX_VERSION = "4.4.2"

# Base URL for downloading
GITHUB_BASE = f"https://github.com/KhronosGroup/KTX-Software/releases/download/v{KTX_VERSION}"


def get_platform_info():
    """
    Detect the current platform and architecture.

    Returns:
        tuple: (os_name, arch) e.g. ('Linux', 'x86_64'), ('Windows', 'x64'), ('Darwin', 'arm64')
    """
    os_name = platform.system()  # 'Linux', 'Windows', 'Darwin'
    machine = platform.machine().lower()

    # Normalize architecture names
    if machine in ('x86_64', 'amd64'):
        arch = 'x86_64'
    elif machine in ('aarch64', 'arm64'):
        arch = 'arm64'
    else:
        arch = machine

    return os_name, arch


def get_download_info():
    """
    Get the download URL and archive type for the current platform.

    Returns:
        tuple: (url, archive_type, extract_subdir) or (None, None, None) if unsupported
    """
    os_name, arch = get_platform_info()

    # Use GitHub releases for more reliable downloads
    github_base = f"https://github.com/KhronosGroup/KTX-Software/releases/download/v{KTX_VERSION}"

    if os_name == 'Linux':
        if arch == 'x86_64':
            filename = f"KTX-Software-{KTX_VERSION}-Linux-x86_64.tar.bz2"
        elif arch == 'arm64':
            filename = f"KTX-Software-{KTX_VERSION}-Linux-arm64.tar.bz2"
        else:
            return None, None, None
        return f"{github_base}/{filename}", 'tar.bz2', f"KTX-Software-{KTX_VERSION}-Linux-{arch}"

    elif os_name == 'Windows':
        # Windows uses installer (.exe), need 7-Zip to extract
        if arch == 'x86_64':
            filename = f"KTX-Software-{KTX_VERSION}-Windows-x64.exe"
        elif arch == 'arm64':
            filename = f"KTX-Software-{KTX_VERSION}-Windows-arm64.exe"
        else:
            return None, None, None
        return f"{github_base}/{filename}", 'exe', None

    elif os_name == 'Darwin':
        if arch == 'x86_64':
            filename = f"KTX-Software-{KTX_VERSION}-Darwin-x86_64.pkg"
        elif arch == 'arm64':
            filename = f"KTX-Software-{KTX_VERSION}-Darwin-arm64.pkg"
        else:
            return None, None, None
        return f"{github_base}/{filename}", 'pkg', None

    return None, None, None


def get_tools_directory():
    """
    Get the directory where KTX tools should be stored.

    Returns:
        Path: Directory path for storing tools
    """
    # Store in the addon's directory
    addon_dir = Path(__file__).parent
    tools_dir = addon_dir / "bin"
    return tools_dir


def get_system_tool_path(exe_name):
    """
    Locate a KTX tool that is already installed system-wide.

    Blender (especially on macOS) often launches with a minimal PATH that does
    not include common install locations like /usr/local/bin, so we check those
    directories explicitly in addition to PATH.

    Args:
        exe_name: Executable file name (e.g. 'toktx' or 'toktx.exe')

    Returns:
        Path: Full path to the executable, or None if not found
    """
    # First, honour PATH (covers custom installs and Homebrew on Intel macs).
    found = shutil.which(exe_name)
    if found:
        return Path(found)

    # Common locations Blender's stripped-down PATH usually misses.
    candidate_dirs = [
        '/usr/local/bin',      # KTX-Software .pkg default, Homebrew (Intel)
        '/opt/homebrew/bin',   # Homebrew (Apple Silicon)
        '/usr/bin',
    ]
    for directory in candidate_dirs:
        candidate = Path(directory) / exe_name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    return None


def get_tool_path(tool_name):
    """
    Get the full path to a KTX tool executable.

    Prefers the addon-bundled tools, then falls back to a system-wide
    installation (e.g. one installed via the KTX-Software .pkg or Homebrew).

    Args:
        tool_name: Name of the tool ('toktx', 'ktx', etc.)

    Returns:
        Path: Full path to the executable, or None if not found
    """
    tools_dir = get_tools_directory()
    os_name, _ = get_platform_info()

    if os_name == 'Windows':
        exe_name = f"{tool_name}.exe"
    else:
        exe_name = tool_name

    tool_path = tools_dir / exe_name

    if tool_path.exists() and os.access(tool_path, os.X_OK):
        return tool_path

    # Fall back to a system-installed tool.
    return get_system_tool_path(exe_name)


def are_tools_installed():
    """
    Check if the required KTX tools are installed.

    Returns:
        bool: True if tools are available
    """
    toktx = get_tool_path('toktx')
    return toktx is not None


def download_file(url, dest_path, progress_callback=None):
    """
    Download a file from URL to destination path.

    Args:
        url: URL to download from
        dest_path: Destination file path
        progress_callback: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        bool: True if successful
    """
    import urllib.request
    import urllib.error
    import ssl

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ssl_context = ssl.create_default_context()
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'Accept': '*/*',
        }
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.urlopen(request, timeout=120, context=ssl_context)

        content_type = response.getheader('Content-Type', '')
        if 'text/html' in content_type.lower():
            print(f"Received HTML instead of binary (Content-Type: {content_type})")
            response.close()
            return False

        total_size = response.getheader('Content-Length')
        total_size = int(total_size) if total_size else None

        print(f"Downloading {total_size // 1024 // 1024 if total_size else '?'}MB...")

        downloaded = 0
        chunk_size = 65536

        with open(dest_path, 'wb') as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size:
                    progress_callback(downloaded, total_size)

        response.close()

        # Verify we got a valid file (not HTML)
        with open(dest_path, 'rb') as f:
            header = f.read(16)
            if header.startswith(b'<!') or header.startswith(b'<html') or header.startswith(b'<HTML'):
                print("Downloaded file appears to be HTML, not the expected archive")
                return False
            if str(dest_path).endswith('.tar.bz2') and not header.startswith(b'BZ'):
                print(f"Downloaded file does not appear to be bzip2 (header: {header[:4]})")
                return False

        print(f"Download complete: {downloaded // 1024}KB")
        return True

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        return False

    except (urllib.error.URLError, OSError) as e:
        print(f"Download failed: {e}")
        return False


def extract_linux_archive(archive_path, tools_dir):
    """Extract tools from Linux tar.bz2 archive."""
    import tarfile

    tools_dir.mkdir(parents=True, exist_ok=True)

    # Create lib subdirectory for shared libraries
    lib_dir = tools_dir / 'lib'
    lib_dir.mkdir(parents=True, exist_ok=True)

    extracted_libs = []

    with tarfile.open(archive_path, 'r:bz2') as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue

            filename = os.path.basename(member.name)

            # Extract executables from bin directory
            if '/bin/' in member.name:
                if filename in ('toktx', 'ktx', 'ktxsc', 'ktxinfo'):
                    tar.extract(member, path=tools_dir.parent)
                    extracted_path = tools_dir.parent / member.name
                    dest_path = tools_dir / filename
                    shutil.move(str(extracted_path), str(dest_path))
                    os.chmod(dest_path, 0o755)
                    print(f"[KTX2] Extracted: {filename}")

            # Extract shared libraries from lib directory
            elif '/lib/' in member.name:
                if filename.startswith('libktx') and '.so' in filename:
                    tar.extract(member, path=tools_dir.parent)
                    extracted_path = tools_dir.parent / member.name
                    dest_path = lib_dir / filename
                    shutil.move(str(extracted_path), str(dest_path))
                    extracted_libs.append(filename)
                    print(f"[KTX2] Extracted library: {filename}")

    # Create symlinks for versioned libraries
    # e.g., libktx.so.4.4.2 -> libktx.so.4 -> libktx.so
    for lib_file in extracted_libs:
        lib_path = lib_dir / lib_file

        # Parse version from filename like libktx.so.4.4.2
        if '.so.' in lib_file:
            base_name = lib_file.split('.so.')[0]  # e.g., 'libktx'
            version = lib_file.split('.so.')[1]     # e.g., '4.4.2'

            # Create major version symlink (libktx.so.4 -> libktx.so.4.4.2)
            major_version = version.split('.')[0]
            major_symlink = lib_dir / f"{base_name}.so.{major_version}"
            if not major_symlink.exists():
                os.symlink(lib_file, major_symlink)
                print(f"[KTX2] Created symlink: {major_symlink.name} -> {lib_file}")

            # Create base symlink (libktx.so -> libktx.so.4.4.2)
            base_symlink = lib_dir / f"{base_name}.so"
            if not base_symlink.exists():
                os.symlink(lib_file, base_symlink)
                print(f"[KTX2] Created symlink: {base_symlink.name} -> {lib_file}")

    # Clean up extracted directories
    for item in tools_dir.parent.iterdir():
        if item.is_dir() and item.name.startswith('KTX-Software'):
            shutil.rmtree(item, ignore_errors=True)

    return True


# Direct download for the standalone reduced 7-Zip extractor (~600KB).
# Only handles .7z archives, but enough to bootstrap the full 7za.exe.
SEVEN_ZR_URL = "https://www.7-zip.org/a/7zr.exe"

# 7-Zip "extras" archive contains the standalone 7za.exe needed to extract
# the NSIS installer. Versioned URL — when 7-Zip releases a new version,
# old URLs 404, so we try a list of known versions newest-first.
SEVEN_ZIP_EXTRA_VERSIONS = ["2501", "2500", "2409", "2408", "2407"]


def find_system_7zip():
    """Locate an already-installed 7-Zip executable. Returns path or None."""
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    return None


def ensure_7zip_available(progress_callback=None):
    """
    Find or download a 7-Zip executable capable of extracting NSIS installers.

    Strategy:
      1. Use a system-installed 7-Zip if present.
      2. Use a previously-cached 7za.exe in the addon's bin directory.
      3. Bootstrap: download 7zr.exe, then download the 7-Zip extras .7z and
         use 7zr to unpack 7za.exe out of it. Cache the result.

    Returns:
        str | None: Path to a 7-Zip executable, or None if unavailable.
    """
    sys_7z = find_system_7zip()
    if sys_7z:
        return sys_7z

    tools_dir = get_tools_directory()
    cached_7za = tools_dir / "7za.exe"
    if cached_7za.is_file():
        return str(cached_7za)

    if progress_callback:
        progress_callback("7-Zip not found - downloading portable 7-Zip...", 50)

    tools_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_dir = tools_dir / "_7zip_bootstrap"
    if bootstrap_dir.exists():
        shutil.rmtree(bootstrap_dir, ignore_errors=True)
    bootstrap_dir.mkdir(parents=True, exist_ok=True)

    seven_zr = bootstrap_dir / "7zr.exe"
    if not download_file(SEVEN_ZR_URL, seven_zr):
        print("[KTX2] Failed to download 7zr.exe")
        return None

    # The 7-Zip extras archive is versioned and old versions 404 when a new
    # release ships, so try newest-first.
    extra_archive = bootstrap_dir / "7z-extra.7z"
    extras_downloaded = False
    for version in SEVEN_ZIP_EXTRA_VERSIONS:
        url = f"https://www.7-zip.org/a/7z{version}-extra.7z"
        print(f"[KTX2] Trying {url}")
        if download_file(url, extra_archive):
            extras_downloaded = True
            break

    if not extras_downloaded:
        print("[KTX2] Could not download any 7-Zip extras archive")
        return None

    try:
        result = subprocess.run(
            [str(seven_zr), "x", str(extra_archive), f"-o{bootstrap_dir}", "-y"],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"[KTX2] 7zr extraction failed: {result.stderr.decode(errors='replace')}")
            return None
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[KTX2] Failed to run 7zr: {e}")
        return None

    extracted_7za = next(bootstrap_dir.rglob("7za.exe"), None)
    if not extracted_7za:
        print("[KTX2] 7za.exe not found inside extras archive")
        return None

    shutil.copy2(extracted_7za, cached_7za)
    shutil.rmtree(bootstrap_dir, ignore_errors=True)
    print(f"[KTX2] Cached portable 7-Zip at {cached_7za}")
    return str(cached_7za)


def extract_windows_installer(installer_path, tools_dir, progress_callback=None):
    """Extract KTX tools from the Khronos Windows NSIS installer."""
    tools_dir.mkdir(parents=True, exist_ok=True)

    seven_zip = ensure_7zip_available(progress_callback)
    if not seven_zip:
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                [seven_zip, 'x', str(installer_path), f'-o{tmpdir}', '-y'],
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                print(f"[KTX2] 7-Zip extraction failed: {result.stderr.decode(errors='replace')}")
                return False

            for root, dirs, files in os.walk(tmpdir):
                for filename in files:
                    if filename in ('toktx.exe', 'ktx.exe', 'ktxsc.exe', 'ktxinfo.exe'):
                        src = Path(root) / filename
                        dst = tools_dir / filename
                        shutil.copy2(src, dst)
                    elif filename.lower().endswith('.dll'):
                        src = Path(root) / filename
                        dst = tools_dir / filename
                        shutil.copy2(src, dst)

            return (tools_dir / 'toktx.exe').exists()
        except subprocess.SubprocessError as e:
            print(f"[KTX2] Failed to run 7-Zip: {e}")
            return False


def _decode_pbzx(payload_path, output_path):
    """
    Decode an Apple pbzx-compressed payload into a raw cpio archive.

    Modern macOS .pkg payloads are wrapped in the "pbzx" container: a sequence
    of independently-xz-compressed chunks. gunzip cannot read these, which is
    why the old gzip-only extraction failed. Returns True on success.
    """
    import struct
    import lzma

    with open(payload_path, 'rb') as src, open(output_path, 'wb') as dst:
        magic = src.read(4)
        if magic != b'pbzx':
            return False

        # Initial flags field (ignored; chunk sizes drive the loop).
        src.read(8)

        while True:
            header = src.read(16)
            if len(header) < 16:
                break
            # Each chunk is prefixed by uncompressed size and compressed size.
            _uncompressed_size, compressed_size = struct.unpack('>QQ', header)
            chunk = src.read(compressed_size)
            if len(chunk) < compressed_size:
                return False
            if chunk[:6] == b'\xfd7zXZ\x00':
                dst.write(lzma.decompress(chunk))
            else:
                # Stored chunk (not xz-compressed).
                dst.write(chunk)

    return True


def _extract_cpio(cpio_path, extract_dir):
    """Extract a raw cpio archive using whatever tool is available."""
    # bsdtar (the default `tar` on macOS) reads cpio archives directly.
    for cmd in (['tar', '-xf', str(cpio_path)],
                ['cpio', '-id', '-I', str(cpio_path)]):
        try:
            result = subprocess.run(
                cmd, cwd=str(extract_dir), capture_output=True, timeout=120
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            continue

    # Last resort: pipe the cpio through stdin.
    try:
        with open(cpio_path, 'rb') as f:
            result = subprocess.run(
                ['cpio', '-id'], stdin=f, cwd=str(extract_dir),
                capture_output=True, timeout=120
            )
            return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def extract_macos_package(pkg_path, tools_dir):
    """Extract tools from macOS .pkg file."""
    tools_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        try:
            # Expand the pkg
            subprocess.run(
                ['pkgutil', '--expand', str(pkg_path), str(tmpdir / 'expanded')],
                capture_output=True,
                check=True,
                timeout=60
            )

            # The .pkg is a "product archive" containing multiple component
            # packages (e.g. *-tools.pkg, *-library.pkg, *-jni.pkg, *-dev.pkg).
            # The CLI executables live in *-tools.pkg while libktx.dylib lives
            # in *-library.pkg, so we need to extract both. Picking just the
            # first Payload found via an unordered scan would silently grab
            # the wrong (or an incomplete) component.
            payload_paths = list((tmpdir / 'expanded').rglob('Payload'))

            for payload_path in payload_paths:
                extract_dir = tmpdir / f'extracted_{payload_path.parent.name}'
                extract_dir.mkdir()

                # Inspect the payload's magic bytes to pick a decoder.
                with open(payload_path, 'rb') as f:
                    magic = f.read(4)

                extracted = False
                if magic == b'pbzx':
                    # Modern xz-wrapped payload.
                    cpio_path = tmpdir / f'{payload_path.parent.name}.cpio'
                    if _decode_pbzx(payload_path, cpio_path):
                        extracted = _extract_cpio(cpio_path, extract_dir)
                elif magic[:2] == b'\x1f\x8b':
                    # Legacy gzip-compressed cpio.
                    import gzip
                    cpio_path = tmpdir / f'{payload_path.parent.name}.cpio'
                    with gzip.open(payload_path, 'rb') as gz, open(cpio_path, 'wb') as out:
                        shutil.copyfileobj(gz, out)
                    extracted = _extract_cpio(cpio_path, extract_dir)
                else:
                    # Uncompressed cpio (or something tar/cpio can read directly).
                    extracted = _extract_cpio(payload_path, extract_dir)

                if not extracted:
                    print(f"[KTX2] Failed to extract macOS payload from {payload_path.parent.name}")
                    continue

                # Find and copy tools and the shared library they depend on.
                # The official binaries are signed with the hardened runtime,
                # which causes macOS to strip DYLD_LIBRARY_PATH at launch, so
                # the only rpath entry that actually resolves is
                # @executable_path - the dylib must sit next to the exe.
                for root, dirs, files in os.walk(extract_dir):
                    for filename in files:
                        if filename in ('toktx', 'ktx', 'ktxsc', 'ktxinfo'):
                            src = Path(root) / filename
                            dst = tools_dir / filename
                            shutil.copy2(src, dst)
                            os.chmod(dst, 0o755)
                        elif filename.startswith('libktx') and '.dylib' in filename:
                            src = Path(root) / filename
                            dst = tools_dir / filename
                            shutil.copy2(src, dst)

            if (tools_dir / 'toktx').exists():
                return True

            print("[KTX2] Could not find toktx in any component of the macOS package")

        except subprocess.SubprocessError as e:
            print(f"Failed to extract macOS package: {e}")

    return False


def install_tools(progress_callback=None):
    """
    Download and install KTX tools for the current platform.

    Args:
        progress_callback: Optional callback(status_message, progress_percent)

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    os_name, arch = get_platform_info()

    # If the tools are already available system-wide (e.g. installed via the
    # KTX-Software .pkg or Homebrew), there's nothing to download.
    if are_tools_installed():
        if progress_callback:
            progress_callback("KTX tools already available!", 100)
        return True, None

    url, archive_type, _ = get_download_info()

    if url is None:
        return False, f"Unsupported platform: {os_name} {arch}"

    tools_dir = get_tools_directory()

    # Create temp directory for download
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        archive_path = tmpdir / f"ktx_tools.{archive_type}"

        # Download
        if progress_callback:
            progress_callback("Downloading KTX tools...", 0)

        def download_progress(downloaded, total):
            if progress_callback:
                percent = int(downloaded / total * 50)  # Download is 0-50%
                progress_callback(f"Downloading... {downloaded // 1024 // 1024}MB", percent)

        if not download_file(url, archive_path, download_progress):
            return False, "Failed to download KTX tools. Check your internet connection."

        # Extract
        if progress_callback:
            progress_callback("Extracting tools...", 50)

        try:
            if archive_type == 'tar.bz2':
                success = extract_linux_archive(archive_path, tools_dir)
            elif archive_type == 'exe':
                success = extract_windows_installer(archive_path, tools_dir, progress_callback)
            elif archive_type == 'pkg':
                success = extract_macos_package(archive_path, tools_dir)
            else:
                return False, f"Unknown archive type: {archive_type}"

            if not success:
                return False, "Failed to extract KTX tools from archive."

        except Exception as e:
            return False, f"Extraction failed: {str(e)}"

    # Verify installation
    if progress_callback:
        progress_callback("Verifying installation...", 90)

    if not are_tools_installed():
        return False, "Tools were extracted but verification failed."

    if progress_callback:
        progress_callback("Installation complete!", 100)

    return True, None


def get_tool_environment():
    """
    Get environment variables for running KTX tools.

    Sets LD_LIBRARY_PATH (Linux) or PATH (Windows) to include the lib directory.
    """
    env = os.environ.copy()
    tools_dir = get_tools_directory()
    lib_dir = tools_dir / 'lib'

    os_name, _ = get_platform_info()

    if os_name == 'Linux':
        # Add lib directory to LD_LIBRARY_PATH
        current_ld_path = env.get('LD_LIBRARY_PATH', '')
        if current_ld_path:
            env['LD_LIBRARY_PATH'] = f"{lib_dir}:{current_ld_path}"
        else:
            env['LD_LIBRARY_PATH'] = str(lib_dir)
    elif os_name == 'Windows':
        # Add tools and lib directories to PATH for DLLs
        current_path = env.get('PATH', '')
        env['PATH'] = f"{tools_dir};{lib_dir};{current_path}"
    elif os_name == 'Darwin':
        # Add lib directory to DYLD_LIBRARY_PATH
        current_dyld_path = env.get('DYLD_LIBRARY_PATH', '')
        if current_dyld_path:
            env['DYLD_LIBRARY_PATH'] = f"{lib_dir}:{current_dyld_path}"
        else:
            env['DYLD_LIBRARY_PATH'] = str(lib_dir)

    return env


def run_toktx(input_path, output_path, options=None):
    """
    Run the toktx tool to convert an image to KTX2.

    Args:
        input_path: Path to input image (PNG, JPEG, etc.)
        output_path: Path for output KTX2 file
        options: Dict of options:
            - target_format: 'BASISU' or 'ASTC'
            - format: 'ETC1S' or 'UASTC' (for BASISU)
            - quality: 1-255 for ETC1S, 0-4 for UASTC
            - compression: 0-5 for ETC1S, 1-22 for UASTC
            - mipmaps: bool
            - astc_block_size: '4x4', '5x5', '6x6', '8x8' (for ASTC)
            - oetf: Transfer function (linear|srgb)
            - target_type: Target type (R, RG, RGB, RGBA)
            - normal_mode: Encode as a normal map (toktx --normal_mode)
            - normal_two_channel: Store normals as 2-component X+Y (needs shader
              Z-reconstruction); when False a standard 3-channel map is kept

    Returns:
        tuple: (success: bool, error_message: str or None)

    Notes on target formats:
        - BASISU: Basis Universal (ETC1S or UASTC) - universal, transcodes at runtime
                  to any GPU format (BC7, ASTC, ETC2, etc.)
        - ASTC: Native ASTC format - direct GPU upload on ASTC-capable hardware
                (mobile devices, Apple Silicon). No transcoding needed.
    """
    toktx_path = get_tool_path('toktx')
    if not toktx_path:
        return False, "toktx tool not found. Please install KTX tools first."

    options = options or {}

    cmd = [str(toktx_path)]

    target_format = options.get('target_format', 'BASISU')

    if target_format == 'ASTC':
        # Native ASTC compression - direct GPU upload on ASTC hardware
        cmd.extend(['--encode', 'astc'])
        block_size = options.get('astc_block_size', '6x6')
        cmd.extend(['--astc_blk_d', block_size])
        cmd.extend(['--astc_quality', 'medium'])

        compression = options.get('compression', 3)
        if compression > 0:
            cmd.extend(['--zcmp', str(compression)])
    else:
        # Basis Universal (ETC1S or UASTC) - universal format
        # Can be transcoded to BC7, ASTC, ETC2, etc. at runtime
        fmt = options.get('format', 'ETC1S')
        if fmt == 'UASTC':
            cmd.extend(['--encode', 'uastc'])
            quality = options.get('quality', 2)
            cmd.extend(['--uastc_quality', str(quality)])

            compression = options.get('compression', 3)
            if compression > 0:
                cmd.extend(['--zcmp', str(compression)])

            rdo = options.get('rdo', 0)
            if rdo > 0:
                cmd.extend(['--uastc_rdo_l', str(rdo)])
        else:
            # ETC1S (default)
            cmd.extend(['--encode', 'etc1s'])
            quality = options.get('quality', 128)
            cmd.extend(['--qlevel', str(quality)])

            compression = options.get('compression', 1)
            if compression > 0:
                cmd.extend(['--clevel', str(compression)])
    
    # Normal map mode - tunes the encoder for normal maps (requires linear input)
    normal_mode = options.get('normal_mode', False)
    normal_two_channel = options.get('normal_two_channel', False)
    if normal_mode:
        cmd.append('--normal_mode')

    # Transfer function
    oetf = options.get('oetf', 'srgb')
    cmd.extend(['--assign_oetf', oetf])

    # Target type
    if normal_mode and normal_two_channel:
        # Let toktx store its optimized 2-component X+Y normal map (RGB=X, A=Y).
        # Forcing --target_type would drop the Y component, so omit it here.
        pass
    else:
        if normal_mode:
            # Keep a standard 3-channel normal map: rgb1 prevents the default
            # 2-component conversion while still applying the normal-tuned encoder.
            cmd.extend(['--input_swizzle', 'rgb1'])
        target_type = options.get('target_type', 'RGBA')
        cmd.extend(['--target_type', target_type])

    # Scale
    scale = options.get('scale', 1.0)
    cmd.extend(['--scale', str(scale)])

    # Mipmaps
    if options.get('mipmaps', False):
        cmd.append('--genmipmap')

    # Output and input
    cmd.append(str(output_path))
    cmd.append(str(input_path))

    print(cmd)

    try:
        env = get_tool_environment()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            env=env
        )

        if result.returncode != 0:
            return False, f"toktx failed: {result.stderr}"

        return True, None

    except subprocess.TimeoutExpired:
        return False, "toktx timed out"
    except Exception as e:
        return False, f"Failed to run toktx: {str(e)}"


def run_ktx_extract(input_path, output_path):
    """
    Run the ktx tool to extract/transcode a KTX2 file to PNG.

    Args:
        input_path: Path to input KTX2 file
        output_path: Path for output PNG file

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    ktx_path = get_tool_path('ktx')
    if not ktx_path:
        return False, "ktx tool not found. Please install KTX tools first."

    cmd = [
        str(ktx_path),
        'extract',
        str(input_path),
        str(output_path)
    ]

    try:
        env = get_tool_environment()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        if result.returncode != 0:
            return False, f"ktx extract failed: {result.stderr}"

        return True, None

    except subprocess.TimeoutExpired:
        return False, "ktx extract timed out"
    except Exception as e:
        return False, f"Failed to run ktx: {str(e)}"
