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
KTX2 encoding functionality for glTF export.

Uses the KTX-Software command-line tools (toktx) to encode images to KTX2 format
with Basis Universal compression.
"""

import os
import tempfile
from pathlib import Path


class KTX2ImageData:
    """ImageData-like container for KTX2 files."""

    def __init__(self, data: bytes, mime_type: str, name: str):
        self._data = data
        self._mime_type = mime_type
        self._name = name
        self._adjusted_name = None
        self._uri = None

    def __eq__(self, other):
        return self._data == other.data

    def __hash__(self):
        return hash(self._data)

    @property
    def data(self):
        return self._data

    @property
    def name(self):
        return self._name

    @property
    def file_extension(self):
        return ".ktx2"

    @property
    def byte_length(self):
        return len(self._data)

    @property
    def uri(self):
        return self._uri

    @uri.setter
    def uri(self, uri):
        self._uri = uri

    def adjusted_name(self):
        import re
        regex_dot = re.compile(r"\.")
        adjusted_name = re.sub(regex_dot, "_", self.name)
        new_name = "".join([char for char in adjusted_name if char not in r"!#$&'()*+,/:;<>?@[\]^`{|}~"])
        return new_name

    def set_adjusted_name(self, names):
        import re
        name = self.name
        count = 1
        regex = re.compile(r"-\d+$")
        while name + self.file_extension in names:
            regex_found = re.findall(regex, name)
            if regex_found:
                name = re.sub(regex, "-" + str(count), name)
            else:
                name += "-" + str(count)
            count += 1
        self._adjusted_name = name + self.file_extension
        return self._adjusted_name


def save_image_to_temp_png(gltf_image, export_settings):
    """
    Save a glTF image to a temporary PNG file for processing.

    Args:
        gltf_image: The gltf2_io.Image object being exported
        export_settings: Export settings dict

    Returns:
        Path: Path to temporary PNG file, or None on failure
    """
    import bpy

    # Determine file extension based on mime_type
    mime_type = getattr(gltf_image, 'mime_type', 'image/png')
    if mime_type == 'image/jpeg':
        suffix = '.jpg'
    else:
        suffix = '.png'

    # Try to get image data from buffer_view (embedded GLB data)
    if gltf_image.buffer_view is not None:
        try:
            img_data = gltf_image.buffer_view.data
            if not isinstance(img_data, (bytes, bytearray)):
                img_data = bytes(img_data)

            # Write directly to temp file - data is already encoded
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.write(img_data)
            temp_file.close()
            return Path(temp_file.name)
        except Exception as e:
            export_settings['log'].debug(f"Could not save buffer_view data: {e}")

    # Try URI (ImageData object)
    uri = gltf_image.uri
    if uri is not None and hasattr(uri, 'data'):
        try:
            img_data = uri.data
            if not isinstance(img_data, (bytes, bytearray)):
                img_data = bytes(img_data)

            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.write(img_data)
            temp_file.close()
            return Path(temp_file.name)
        except Exception as e:
            export_settings['log'].warning(f"Failed to save image data from URI: {e}")

    # Fallback: try to find original Blender image by name
    if gltf_image.name:
        blender_image = bpy.data.images.get(gltf_image.name)
        if blender_image is None:
            # Try without extension
            name_no_ext = gltf_image.name.rsplit('.', 1)[0]
            blender_image = bpy.data.images.get(name_no_ext)

        if blender_image is not None:
            return save_blender_image_to_temp(blender_image, export_settings)

    return None


def save_blender_image_to_temp(blender_image, export_settings):
    """
    Save a Blender image to a temporary PNG file.

    Args:
        blender_image: bpy.types.Image
        export_settings: Export settings dict

    Returns:
        Path: Path to temporary PNG file, or None on failure
    """
    import bpy

    try:
        width, height = blender_image.size
        if width == 0 or height == 0:
            return None

        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()

        # Save the image
        # We need to temporarily change the file format settings
        original_format = blender_image.file_format
        blender_image.file_format = 'PNG'

        blender_image.save_render(temp_path)

        blender_image.file_format = original_format

        return Path(temp_path)

    except Exception as e:
        export_settings['log'].warning(f"Failed to save Blender image: {e}")
        return None


def encode_image_to_ktx2(gltf_image, target_format, compression_mode, quality_level, generate_mipmaps, export_settings, astc_block_size='6x6'):
    """
    Encode a glTF image to KTX2 format.

    Args:
        gltf_image: The gltf2_io.Image object to encode
        target_format: 'BASISU', 'BC7', 'ASTC', or 'ETC2'
        compression_mode: 'ETC1S' or 'UASTC' (for BASISU)
        quality_level: Quality level (1-255 for ETC1S, 0-4 for UASTC)
        generate_mipmaps: Whether to generate mipmaps
        export_settings: Export settings dict
        astc_block_size: ASTC block size ('4x4', '5x5', '6x6', '8x8')

    Returns:
        gltf2_io.Image: New Image object with KTX2 data, or None on failure
    """
    from . import ktx_tools
    from io_scene_gltf2.io.com import gltf2_io
    from io_scene_gltf2.io.exp.binary_data import BinaryData

    # Save source image to temp PNG
    temp_png = save_image_to_temp_png(gltf_image, export_settings)
    if temp_png is None:
        export_settings['log'].warning("Could not extract image data for KTX2 encoding")
        return None

    try:
        # Create temp file for KTX2 output
        temp_ktx2 = tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False)
        temp_ktx2_path = Path(temp_ktx2.name)
        temp_ktx2.close()

        # Prepare encoding options
        options = {
            'target_format': target_format,
            'format': compression_mode,
            'quality': quality_level if compression_mode == 'ETC1S' else min(quality_level // 64, 4),
            'mipmaps': generate_mipmaps,
            'astc_block_size': astc_block_size,
        }

        # Log the target format for debugging
        format_names = {
            'BASISU': 'Basis Universal',
            'ASTC': 'Native ASTC',
        }
        export_settings['log'].info(f"Encoding to {format_names.get(target_format, target_format)}")

        # Run toktx (or ktx for native formats)
        success, error = ktx_tools.run_toktx(temp_png, temp_ktx2_path, options)

        if not success:
            export_settings['log'].error(f"KTX2 encoding failed: {error}")
            return None

        # Read the KTX2 data
        with open(temp_ktx2_path, 'rb') as f:
            ktx2_bytes = f.read()

        # Create new glTF Image with KTX2 data
        name = gltf_image.name or "texture"
        # Remove old extension
        if '.' in name:
            name = name.rsplit('.', 1)[0]

        if export_settings['gltf_format'] == 'GLTF_SEPARATE':
            # For separate files, write KTX2 file directly and use filename as URI
            filepath = export_settings.get('gltf_filepath', '')
            output_dir = os.path.dirname(filepath)

            # Ensure output directory exists (might not be created yet at this stage)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # Track written filenames to avoid duplicates
            if 'ktx2_written_files' not in export_settings:
                export_settings['ktx2_written_files'] = set()

            # Generate unique filename
            base_name = name
            ktx2_filename = f"{base_name}.ktx2"
            counter = 1
            while ktx2_filename in export_settings['ktx2_written_files']:
                ktx2_filename = f"{base_name}_{counter}.ktx2"
                counter += 1
            export_settings['ktx2_written_files'].add(ktx2_filename)

            ktx2_filepath = os.path.join(output_dir, ktx2_filename) if output_dir else ktx2_filename

            # Write KTX2 file
            with open(ktx2_filepath, 'wb') as f:
                f.write(ktx2_bytes)

            ktx2_image = gltf2_io.Image(
                buffer_view=None,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name=name,
                uri=ktx2_filename
            )
        else:
            # For embedded (GLB), use buffer_view
            buffer_view = BinaryData(data=ktx2_bytes)

            ktx2_image = gltf2_io.Image(
                buffer_view=buffer_view,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name=name,
                uri=None
            )

        return ktx2_image

    except Exception as e:
        export_settings['log'].error(f"KTX2 encoding failed: {e}")
        import traceback
        export_settings['log'].debug(traceback.format_exc())
        return None

    finally:
        # Clean up temp files
        try:
            if temp_png and temp_png.exists():
                os.unlink(temp_png)
        except OSError:
            pass
        try:
            if temp_ktx2_path and temp_ktx2_path.exists():
                os.unlink(temp_ktx2_path)
        except OSError:
            pass
