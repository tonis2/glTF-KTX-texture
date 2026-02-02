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


def get_tool_path(tool_name):
    """
    Get the full path to a KTX tool executable.

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

    return None


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
    import http.client

    # Ensure parent directory exists
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    max_redirects = 10

    for redirect_count in range(max_redirects):
        try:
            # Create SSL context
            ssl_context = ssl.create_default_context()

            # Create a request with a browser-like user agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                'Accept': '*/*',
            }
            request = urllib.request.Request(url, headers=headers)

            # Open URL
            response = urllib.request.urlopen(request, timeout=120, context=ssl_context)

            # Check for redirect in response URL
            final_url = response.geturl()
            if final_url != url:
                print(f"Redirected to: {final_url[:80]}...")

            # Check content type
            content_type = response.getheader('Content-Type', '')
            if 'text/html' in content_type.lower():
                print(f"Received HTML instead of binary (Content-Type: {content_type})")
                response.close()
                return False

            total_size = response.getheader('Content-Length')
            total_size = int(total_size) if total_size else None

            print(f"Downloading {total_size // 1024 // 1024 if total_size else '?'}MB...")

            downloaded = 0
            chunk_size = 65536  # 64KB chunks for faster download

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
                # Check for bzip2 magic number
                if dest_path.suffix == '.bz2' or str(dest_path).endswith('.tar.bz2'):
                    if not header.startswith(b'BZ'):
                        print(f"Downloaded file does not appear to be bzip2 (header: {header[:4]})")
                        return False

            print(f"Download complete: {downloaded // 1024}KB")
            return True

        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                # Manual redirect handling
                redirect_url = e.headers.get('Location')
                if redirect_url:
                    print(f"Following redirect ({e.code}) to: {redirect_url[:80]}...")
                    url = redirect_url
                    continue
            print(f"HTTP Error: {e.code} {e.reason}")
            return False

        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            print(f"Download failed: {e}")
            return False

    print("Too many redirects")
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


def extract_windows_installer(installer_path, tools_dir):
    """
    Extract tools from Windows installer.

    The Windows .exe is an NSIS installer. We can extract it using 7z or
    by running it silently, but that's complex. Instead, we'll try to
    use the GitHub release assets which might have a zip.

    For now, we'll attempt to use 7z if available, otherwise provide instructions.
    """
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Try using 7z to extract (common on Windows)
    seven_zip_paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        "7z",  # If in PATH
    ]

    seven_zip = None
    for path in seven_zip_paths:
        try:
            result = subprocess.run([path, '--help'], capture_output=True, timeout=5)
            if result.returncode == 0:
                seven_zip = path
                break
        except (subprocess.SubprocessError, FileNotFoundError):
            continue

    if seven_zip:
        # Extract using 7z
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                subprocess.run(
                    [seven_zip, 'x', str(installer_path), f'-o{tmpdir}', '-y'],
                    capture_output=True,
                    timeout=120
                )

                # Find the bin directory
                for root, dirs, files in os.walk(tmpdir):
                    for filename in files:
                        if filename in ('toktx.exe', 'ktx.exe', 'ktxsc.exe', 'ktxinfo.exe'):
                            src = Path(root) / filename
                            dst = tools_dir / filename
                            shutil.copy2(src, dst)

                return (tools_dir / 'toktx.exe').exists()
            except subprocess.SubprocessError:
                pass

    # Fallback: Try running installer silently (not ideal)
    # For better UX, we should provide manual instructions
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

            # Find and extract the payload
            payload_path = tmpdir / 'expanded' / 'ktx-tools.pkg' / 'Payload'
            if not payload_path.exists():
                # Try alternative structure
                for p in (tmpdir / 'expanded').rglob('Payload'):
                    payload_path = p
                    break

            if payload_path.exists():
                # Extract payload (it's a cpio archive, possibly gzipped)
                extract_dir = tmpdir / 'extracted'
                extract_dir.mkdir()

                # Try gunzip + cpio
                try:
                    with subprocess.Popen(
                        ['gunzip', '-c', str(payload_path)],
                        stdout=subprocess.PIPE
                    ) as gunzip:
                        subprocess.run(
                            ['cpio', '-id'],
                            stdin=gunzip.stdout,
                            cwd=str(extract_dir),
                            capture_output=True,
                            timeout=60
                        )
                except FileNotFoundError:
                    # gunzip not available, try with Python gzip
                    import gzip
                    with gzip.open(payload_path, 'rb') as f:
                        # This is more complex, skip for now
                        pass

                # Find and copy tools
                for root, dirs, files in os.walk(extract_dir):
                    for filename in files:
                        if filename in ('toktx', 'ktx', 'ktxsc', 'ktxinfo'):
                            src = Path(root) / filename
                            dst = tools_dir / filename
                            shutil.copy2(src, dst)
                            os.chmod(dst, 0o755)

                return (tools_dir / 'toktx').exists()

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
                success = extract_windows_installer(archive_path, tools_dir)
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
        # Add lib directory to PATH for DLLs
        current_path = env.get('PATH', '')
        env['PATH'] = f"{lib_dir};{current_path}"
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
            - format: 'ETC1S' or 'UASTC'
            - quality: 1-255 for ETC1S, 0-4 for UASTC
            - mipmaps: bool

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    toktx_path = get_tool_path('toktx')
    if not toktx_path:
        return False, "toktx tool not found. Please install KTX tools first."

    options = options or {}

    cmd = [str(toktx_path)]

    # Add encoding options
    fmt = options.get('format', 'ETC1S')
    if fmt == 'UASTC':
        cmd.append('--uastc')
        quality = options.get('quality', 2)
        cmd.extend(['--uastc_quality', str(quality)])
        # Enable RDO for better compression
        cmd.append('--uastc_rdo')
    else:
        # ETC1S (default)
        cmd.append('--bcmp')
        quality = options.get('quality', 128)
        cmd.extend(['--qlevel', str(quality)])

    # Mipmaps
    if options.get('mipmaps', False):
        cmd.append('--genmipmap')

    # Output and input
    cmd.append(str(output_path))
    cmd.append(str(input_path))

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
