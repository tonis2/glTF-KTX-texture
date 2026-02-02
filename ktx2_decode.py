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
KTX2 decoding functionality for glTF import.

Uses the KTX-Software command-line tools to decode KTX2 textures
and convert them to a format Blender can display.
"""

import os
import tempfile
from pathlib import Path


def decode_ktx2_to_png(ktx2_data, gltf):
    """
    Decode KTX2 texture data to PNG format for Blender.

    Args:
        ktx2_data: Raw KTX2 file bytes
        gltf: The glTF importer object (for logging)

    Returns:
        bytes: PNG image data, or None on failure
    """
    from . import ktx_tools

    # Write KTX2 data to temp file
    temp_ktx2 = None
    temp_png = None

    try:
        # Create temp file for KTX2 input
        temp_ktx2 = tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False)
        temp_ktx2.write(ktx2_data)
        temp_ktx2.close()
        temp_ktx2_path = Path(temp_ktx2.name)

        # Create temp file for PNG output
        temp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_png.close()
        temp_png_path = Path(temp_png.name)

        # Run ktx extract
        success, error = ktx_tools.run_ktx_extract(temp_ktx2_path, temp_png_path)

        if not success:
            gltf.log.warning(f"KTX2 decoding with ktx tool failed: {error}")
            # Try fallback method using Python libraries
            return decode_ktx2_fallback(ktx2_data, gltf)

        # Read the PNG data
        if temp_png_path.exists():
            with open(temp_png_path, 'rb') as f:
                return f.read()
        else:
            gltf.log.warning("ktx extract did not produce output file")
            return decode_ktx2_fallback(ktx2_data, gltf)

    except Exception as e:
        gltf.log.error(f"KTX2 decoding failed: {e}")
        import traceback
        gltf.log.debug(traceback.format_exc())
        return None

    finally:
        # Clean up temp files
        try:
            if temp_ktx2 and Path(temp_ktx2.name).exists():
                os.unlink(temp_ktx2.name)
        except OSError:
            pass
        try:
            if temp_png and Path(temp_png.name).exists():
                os.unlink(temp_png.name)
        except OSError:
            pass


def decode_ktx2_fallback(ktx2_data, gltf):
    """
    Fallback KTX2 decoding using Python libraries when CLI tools fail.

    This is a simpler decoder that handles basic KTX2 files.

    Args:
        ktx2_data: Raw KTX2 file bytes
        gltf: The glTF importer object

    Returns:
        bytes: PNG image data, or None on failure
    """
    try:
        import numpy as np
        from PIL import Image
        import io
        import struct

        # KTX2 file header structure (simplified)
        # See: https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html

        # Check KTX2 magic number
        magic = ktx2_data[:12]
        expected_magic = bytes([0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A])

        if magic != expected_magic:
            gltf.log.warning("Invalid KTX2 magic number")
            return None

        # Parse header (simplified - only handles basic cases)
        # This is a minimal parser and won't work for all KTX2 files
        # For full support, the CLI tools are needed

        # Read basic header fields
        vk_format = struct.unpack_from('<I', ktx2_data, 12)[0]
        type_size = struct.unpack_from('<I', ktx2_data, 16)[0]
        pixel_width = struct.unpack_from('<I', ktx2_data, 20)[0]
        pixel_height = struct.unpack_from('<I', ktx2_data, 24)[0]
        pixel_depth = struct.unpack_from('<I', ktx2_data, 28)[0]
        layer_count = struct.unpack_from('<I', ktx2_data, 32)[0]
        face_count = struct.unpack_from('<I', ktx2_data, 36)[0]
        level_count = struct.unpack_from('<I', ktx2_data, 40)[0]
        supercompression_scheme = struct.unpack_from('<I', ktx2_data, 44)[0]

        gltf.log.debug(f"KTX2: {pixel_width}x{pixel_height}, format={vk_format}, supercompression={supercompression_scheme}")

        # If supercompression is used (BasisLZ=1, Zstd=2, ZLIB=3), we can't easily decode without proper tools
        if supercompression_scheme != 0:
            gltf.log.warning(f"KTX2 uses supercompression scheme {supercompression_scheme}, fallback decoder cannot handle this")
            return None

        # For uncompressed formats, try to extract pixel data
        # This is very limited - only handles simple RGBA8 format (VK_FORMAT_R8G8B8A8_UNORM = 37)
        if vk_format == 37:  # VK_FORMAT_R8G8B8A8_UNORM
            # Find level 0 data offset
            dfd_offset = struct.unpack_from('<I', ktx2_data, 48)[0]
            dfd_size = struct.unpack_from('<I', ktx2_data, 52)[0]
            kvd_offset = struct.unpack_from('<I', ktx2_data, 56)[0]
            kvd_size = struct.unpack_from('<I', ktx2_data, 60)[0]
            sgd_offset = struct.unpack_from('<Q', ktx2_data, 64)[0]
            sgd_size = struct.unpack_from('<Q', ktx2_data, 72)[0]

            # Level index starts at offset 80
            level_offset = struct.unpack_from('<Q', ktx2_data, 80)[0]
            level_size = struct.unpack_from('<Q', ktx2_data, 88)[0]

            # Extract pixel data
            pixel_data = ktx2_data[level_offset:level_offset + level_size]

            # Convert to image
            pixels = np.frombuffer(pixel_data, dtype=np.uint8)
            expected_size = pixel_width * pixel_height * 4

            if len(pixels) == expected_size:
                pixels = pixels.reshape((pixel_height, pixel_width, 4))
                # KTX2 might be flipped
                pixels = np.flipud(pixels)

                # Convert to PNG
                pil_image = Image.fromarray(pixels, mode='RGBA')
                output = io.BytesIO()
                pil_image.save(output, format='PNG')
                return output.getvalue()

        gltf.log.warning(f"Fallback decoder cannot handle VK format {vk_format}")
        return None

    except Exception as e:
        gltf.log.warning(f"Fallback KTX2 decoding failed: {e}")
        return None


def get_ktx2_source_from_texture(pytexture, gltf):
    """
    Get the KTX2 image source from a texture's KHR_texture_basisu extension.

    Args:
        pytexture: The glTF texture object
        gltf: The glTF importer object

    Returns:
        Image index or None if not found
    """
    try:
        ext = pytexture.extensions.get('KHR_texture_basisu', {})
        return ext.get('source')
    except (AttributeError, TypeError):
        return None
