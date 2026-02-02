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
KTX2 Environment Map import/decode for KHR_environment_map extension.

Imports KTX2 cubemap from glTF and sets up Blender's world environment.
"""

import bpy
import os
import re
import tempfile
import math
from pathlib import Path


def import_environment_map(env_map_ext, gltf):
    """
    Import environment map from KHR_environment_map extension.

    Args:
        env_map_ext: The KHR_environment_map extension data
        gltf: The glTF importer object

    Returns:
        bool: True if successful, False otherwise
    """
    from . import ktx2_decode
    from io_scene_gltf2.io.imp.gltf2_io_binary import BinaryData

    # Get environment maps array
    env_maps = env_map_ext.get('environmentMaps', [])
    if not env_maps:
        gltf.log.warning("KHR_environment_map has no environmentMaps")
        return False

    # Use first environment map
    env_map = env_maps[0]
    cubemap_texture_idx = env_map.get('cubemap')
    intensity = env_map.get('intensity', 1.0)

    if cubemap_texture_idx is None:
        gltf.log.warning("Environment map has no cubemap texture")
        return False

    # Get the texture and image
    texture = gltf.data.textures[cubemap_texture_idx]

    # Check for KHR_environment_map extension first (cubemap is always KTX2)
    image_idx = None
    try:
        image_idx = texture.extensions['KHR_environment_map']['source']
    except (AttributeError, KeyError, TypeError):
        pass

    # Fallback to direct source if no extension
    if image_idx is None:
        image_idx = texture.source

    if image_idx is None:
        gltf.log.warning("Cubemap texture has no source image")
        return False

    gltf_image = gltf.data.images[image_idx]

    # Check if image was already decoded by our image hook
    if gltf_image.blender_image_name:
        blender_image = bpy.data.images.get(gltf_image.blender_image_name)
        if blender_image:
            setup_world_environment(blender_image, intensity, gltf)
            return True

    # Need to decode the cubemap ourselves

    # Get image data
    ktx2_data = BinaryData.get_image_data(gltf, image_idx)
    if ktx2_data is None:
        gltf.log.warning("Could not get cubemap image data")
        return False

    if hasattr(ktx2_data, 'tobytes'):
        ktx2_data = ktx2_data.tobytes()

    # Try to decode cubemap and convert to equirectangular
    blender_image = decode_ktx2_cubemap(ktx2_data, gltf)
    if blender_image is None:
        gltf.log.warning("Failed to decode cubemap KTX2")
        return False

    setup_world_environment(blender_image, intensity, gltf)
    return True


def decode_ktx2_cubemap(ktx2_data, gltf):
    """
    Decode a KTX2 cubemap and convert to equirectangular for Blender.

    Args:
        ktx2_data: Raw KTX2 cubemap bytes
        gltf: The glTF importer object

    Returns:
        bpy.types.Image: Blender image in equirectangular format, or None on failure
    """
    from . import ktx_tools

    temp_ktx2 = None
    temp_faces = []

    try:
        # Write KTX2 data to temp file
        temp_ktx2 = tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False)
        temp_ktx2.write(ktx2_data)
        temp_ktx2.close()
        temp_ktx2_path = Path(temp_ktx2.name)

        # Create output directory for extracted faces
        temp_dir = tempfile.mkdtemp(prefix='ktx2_cubemap_')

        # Use ktx extract to get cubemap faces
        ktx_path = ktx_tools.get_tool_path('ktx')
        if not ktx_path:
            gltf.log.warning("ktx tool not found")
            return None

        import subprocess
        env = ktx_tools.get_tool_environment()

        # Extract cubemap faces
        # Need --face all to extract all 6 cubemap faces (default is face 0 only)
        # Need --transcode to convert BasisU to readable format
        output_base = os.path.join(temp_dir, 'face')
        cmd = [
            str(ktx_path),
            'extract',
            '--face', 'all',
            '--transcode', 'rgba8',
            str(temp_ktx2_path),
            output_base
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        if result.returncode != 0:
            gltf.log.warning(f"ktx extract failed: {result.stderr}")
            return decode_ktx2_as_single_image(ktx2_data, gltf)

        # Find extracted face files
        # ktx extract outputs files with face indicators in the name
        # Expected order for our encoder: +X, -X, +Y, -Y, +Z, -Z
        # Note: ktx extract may create the output as a directory when using --face all
        search_dir = temp_dir
        all_dir_files = os.listdir(temp_dir)

        # Check if ktx extract created a subdirectory (e.g., 'face/')
        if len(all_dir_files) == 1:
            potential_subdir = os.path.join(temp_dir, all_dir_files[0])
            if os.path.isdir(potential_subdir):
                search_dir = potential_subdir
                all_dir_files = os.listdir(search_dir)

        # Look for image files (PNG, EXR, or raw)
        image_extensions = ('.png', '.exr', '.raw')
        all_files = [f for f in all_dir_files if f.lower().endswith(image_extensions)]

        # Try to sort by face order
        face_files = sort_cubemap_faces(all_files, search_dir, gltf)
        temp_faces.extend(face_files)

        if len(face_files) == 6:
            return cubemap_faces_to_equirectangular(face_files, gltf)
        elif len(face_files) == 1:
            blender_image = bpy.data.images.load(face_files[0])
            blender_image.name = "environment_cubemap"
            blender_image.pack()
            return blender_image
        elif len(face_files) == 0:
            gltf.log.warning("No image files extracted, falling back to single image decode")
            return decode_ktx2_as_single_image(ktx2_data, gltf)
        else:
            gltf.log.warning(f"Unexpected number of extracted faces: {len(face_files)}, expected 6")
            return decode_ktx2_as_single_image(ktx2_data, gltf)

    except Exception as e:
        gltf.log.error(f"Cubemap decoding failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        # Clean up temp files
        if temp_ktx2:
            try:
                os.unlink(temp_ktx2.name)
            except OSError:
                pass
        for f in temp_faces:
            try:
                os.unlink(f)
            except OSError:
                pass
        # Clean up temp directories
        if 'temp_dir' in locals():
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass


def sort_cubemap_faces(filenames, temp_dir, gltf):
    """
    Sort cubemap face files into the correct order: +X, -X, +Y, -Y, +Z, -Z.

    ktx extract can output files in various naming conventions:
    - face_0.png, face_1.png, ... (numeric order matches input order)
    - face_+X.png, face_-X.png, ... (named by face direction)
    - face_f0_d0_l0.png, face_f1_d0_l0.png, ... (with face, depth, layer indices)
    - output_0_+X.png, output_0_-X.png, ... (with mip level and face name)

    Args:
        filenames: List of extracted file names
        temp_dir: Directory containing the files
        gltf: glTF importer for logging

    Returns:
        List of full paths in correct face order
    """

    # Expected face order
    face_order = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']

    # Try to match face names in filenames
    face_patterns = {
        '+X': re.compile(r'[_\-]?\+?X|right|px', re.IGNORECASE),
        '-X': re.compile(r'[_\-]\-X|left|nx', re.IGNORECASE),
        '+Y': re.compile(r'[_\-]?\+?Y|top|up|py', re.IGNORECASE),
        '-Y': re.compile(r'[_\-]\-Y|bottom|down|ny', re.IGNORECASE),
        '+Z': re.compile(r'[_\-]?\+?Z|front|pz', re.IGNORECASE),
        '-Z': re.compile(r'[_\-]\-Z|back|nz', re.IGNORECASE),
    }

    # Try to identify faces by name
    identified = {}
    unidentified = []

    for fname in filenames:
        found = False
        for face_name, pattern in face_patterns.items():
            if pattern.search(fname):
                if face_name not in identified:
                    identified[face_name] = os.path.join(temp_dir, fname)
                    found = True
                    break
        if not found:
            unidentified.append(fname)

    # If we identified all 6 faces, return them in order
    if len(identified) == 6:
        return [identified[face] for face in face_order]

    # Fallback: Try to find face index in filename
    # ktx extract with --face all outputs: base_f0_d0_l0.png, base_f1_d0_l0.png, etc.
    # where f=face index (0-5 maps to +X, -X, +Y, -Y, +Z, -Z)
    face_indexed = []
    for fname in filenames:
        # Try to find face index pattern like _f0_, _f1_, etc.
        match = re.search(r'_f(\d+)_', fname)
        if match:
            face_idx = int(match.group(1))
            face_indexed.append((face_idx, os.path.join(temp_dir, fname)))

    if len(face_indexed) == 6:
        face_indexed.sort(key=lambda x: x[0])
        return [path for _, path in face_indexed]

    # Try general numeric pattern (face_0.png, face_1.png, etc.)
    numbered = []
    for fname in sorted(filenames):
        # Get all numbers in filename
        numbers = re.findall(r'(\d+)', fname)
        if numbers:
            # Use the last number as the index (likely face index)
            numbered.append((int(numbers[-1]), os.path.join(temp_dir, fname)))

    if len(numbered) == 6:
        numbered.sort(key=lambda x: x[0])
        return [path for _, path in numbered]

    # Last fallback: just use alphabetical order
    gltf.log.warning("Could not determine cubemap face order, using alphabetical")
    return [os.path.join(temp_dir, f) for f in sorted(filenames)]


def decode_ktx2_as_single_image(ktx2_data, gltf):
    """
    Fallback: decode KTX2 as a single image (for non-cubemap or simple cubemaps).

    Args:
        ktx2_data: Raw KTX2 bytes
        gltf: The glTF importer object

    Returns:
        bpy.types.Image or None
    """
    from . import ktx2_decode

    png_data = ktx2_decode.decode_ktx2_to_png(ktx2_data, gltf)
    if png_data is None:
        return None

    temp_png = None
    try:
        temp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_png.write(png_data)
        temp_png.close()

        blender_image = bpy.data.images.load(temp_png.name)
        blender_image.name = "environment_cubemap"
        blender_image.pack()
        return blender_image

    finally:
        if temp_png:
            try:
                os.unlink(temp_png.name)
            except OSError:
                pass


def cubemap_faces_to_equirectangular(face_files, gltf, output_width=2048):
    """
    Convert 6 cubemap face images to a single equirectangular image.

    This reverses the encoding done in ktx2_envmap_encode.py which uses:
    Face order: +X, -X, +Y, -Y, +Z, -Z
    Face configs (u, v in [-1, 1]):
        +X: (1.0, v, -u)
        -X: (-1.0, v, u)
        +Y: (u, 1.0, -v)
        -Y: (u, -1.0, v)
        +Z: (u, v, 1.0)
        -Z: (-u, v, -1.0)

    Args:
        face_files: List of 6 face image paths
        gltf: The glTF importer object
        output_width: Width of output equirectangular image (height = width/2)

    Returns:
        bpy.types.Image: Equirectangular Blender image, or None on failure
    """
    import numpy as np

    try:
        output_height = output_width // 2

        # Load face images
        # ktx extract outputs files with names like face_0.png or face_+X.png
        # We need to determine the correct order
        faces = []
        face_size = None

        for i, face_path in enumerate(face_files):
            img = bpy.data.images.load(face_path)
            w, h = img.size
            if face_size is None:
                face_size = w
            pixels = np.array(img.pixels[:]).reshape((h, w, 4))
            # Blender stores bottom-to-top, flip to top-to-bottom
            pixels = np.flipud(pixels)
            faces.append(pixels)
            bpy.data.images.remove(img)

        if len(faces) != 6:
            gltf.log.warning(f"Expected 6 faces, got {len(faces)}")
            return None

        # Create output image
        output = np.zeros((output_height, output_width, 4), dtype=np.float32)

        # Pre-compute coordinates for vectorized operation
        # For each pixel in the equirectangular output, find the corresponding cubemap face and UV

        for y in range(output_height):
            # Latitude: top of image is +90 degrees, bottom is -90 degrees
            # v goes from 0 (top) to 1 (bottom)
            v_norm = y / (output_height - 1)  # 0 to 1
            phi = (1.0 - v_norm) * math.pi - math.pi / 2  # +pi/2 to -pi/2 (top to bottom)

            for x in range(output_width):
                # Longitude: left edge is -180, right edge is +180
                u_norm = x / (output_width - 1)  # 0 to 1
                theta = u_norm * 2 * math.pi - math.pi  # -pi to +pi

                # Convert spherical to 3D direction (Y-up coordinate system)
                # theta = 0 points to +Z, theta = pi/2 points to +X
                dx = math.cos(phi) * math.sin(theta)
                dy = math.sin(phi)
                dz = math.cos(phi) * math.cos(theta)

                # Determine which face and UV based on the encoding convention
                abs_x, abs_y, abs_z = abs(dx), abs(dy), abs(dz)
                max_axis = max(abs_x, abs_y, abs_z)

                # Match the encoder's face_configs:
                # +X: (1.0, v, -u) -> u = -z/x, v = y/x
                # -X: (-1.0, v, u) -> u = z/x, v = y/x (note: x is negative)
                # +Y: (u, 1.0, -v) -> u = x/y, v = -z/y
                # -Y: (u, -1.0, v) -> u = x/y, v = z/y (note: y is negative)
                # +Z: (u, v, 1.0) -> u = x/z, v = y/z
                # -Z: (-u, v, -1.0) -> u = x/z, v = y/z (note: z is negative)

                if max_axis == abs_x:
                    if dx > 0:
                        # +X face: encoder used (1.0, v, -u)
                        # So: x=1, y=v, z=-u -> u=-z, v=y
                        face_idx = 0
                        face_u = -dz / dx
                        face_v = dy / dx
                    else:
                        # -X face: encoder used (-1.0, v, u)
                        # So: x=-1, y=v, z=u -> u=z, v=y
                        face_idx = 1
                        face_u = dz / (-dx)
                        face_v = dy / (-dx)
                elif max_axis == abs_y:
                    if dy > 0:
                        # +Y face: encoder used (u, 1.0, -v)
                        # So: x=u, y=1, z=-v -> u=x, v=-z
                        face_idx = 2
                        face_u = dx / dy
                        face_v = -dz / dy
                    else:
                        # -Y face: encoder used (u, -1.0, v)
                        # So: x=u, y=-1, z=v -> u=x, v=z
                        face_idx = 3
                        face_u = dx / (-dy)
                        face_v = dz / (-dy)
                else:
                    if dz > 0:
                        # +Z face: encoder used (u, v, 1.0)
                        # So: x=u, y=v, z=1 -> u=x, v=y
                        face_idx = 4
                        face_u = dx / dz
                        face_v = dy / dz
                    else:
                        # -Z face: encoder used (-u, v, -1.0)
                        # So: x=-u, y=v, z=-1 -> u=-x, v=y
                        face_idx = 5
                        face_u = dx / dz  # Note: dz is negative, so this gives -x/|z|
                        face_v = dy / (-dz)

                # Map face UV from [-1, 1] to pixel coordinates [0, face_size-1]
                # The encoder saved faces with v=-1 at top (row 0), v=1 at bottom
                # After loading and flipud, our array also has top at row 0
                px = int((face_u + 1) / 2 * (face_size - 1))
                py = int((face_v + 1) / 2 * (face_size - 1))  # v=-1 -> row 0, v=1 -> row size-1

                # Clamp to valid range
                px = max(0, min(face_size - 1, px))
                py = max(0, min(face_size - 1, py))

                output[y, x] = faces[face_idx][py, px]

        # Create Blender image
        # Blender expects pixels bottom-to-top, so flip
        output = np.flipud(output)

        blender_image = bpy.data.images.new(
            "environment_cubemap",
            width=output_width,
            height=output_height,
            alpha=True
        )
        blender_image.pixels = output.flatten().tolist()
        blender_image.pack()

        return blender_image

    except Exception as e:
        gltf.log.error(f"Cubemap to equirectangular conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def setup_world_environment(blender_image, intensity, gltf):
    """
    Set up Blender world with environment texture.

    Args:
        blender_image: The environment texture image
        intensity: Environment intensity/strength
        gltf: The glTF importer object
    """
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # Clear existing nodes
    nodes.clear()

    # Create nodes
    node_output = nodes.new('ShaderNodeOutputWorld')
    node_output.location = (300, 0)

    node_background = nodes.new('ShaderNodeBackground')
    node_background.location = (0, 0)
    node_background.inputs['Strength'].default_value = intensity

    node_env_tex = nodes.new('ShaderNodeTexEnvironment')
    node_env_tex.location = (-300, 0)
    node_env_tex.image = blender_image

    node_tex_coord = nodes.new('ShaderNodeTexCoord')
    node_tex_coord.location = (-500, 0)

    # Link nodes
    links.new(node_tex_coord.outputs['Generated'], node_env_tex.inputs['Vector'])
    links.new(node_env_tex.outputs['Color'], node_background.inputs['Color'])
    links.new(node_background.outputs['Background'], node_output.inputs['Surface'])
