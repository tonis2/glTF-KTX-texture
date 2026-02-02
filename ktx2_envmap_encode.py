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
KTX2 Environment Map export for KHR_environment_map extension.

Exports Blender's world environment texture as a KTX2 cubemap.
"""

import bpy
import os
import tempfile
import math
from pathlib import Path


def get_world_environment_texture():
    """
    Get the environment texture from the current world.

    Returns:
        bpy.types.Image or None: The environment texture image
    """
    world = bpy.context.scene.world
    if world is None:
        return None

    if world.node_tree is None:
        return None

    # Look for Environment Texture node (most common)
    for node in world.node_tree.nodes:
        if node.type == 'TEX_ENVIRONMENT':
            if node.image is not None:
                return node.image

    # Look for any image texture connected to background/emission
    for node in world.node_tree.nodes:
        if node.type == 'TEX_IMAGE':
            if node.image is not None:
                return node.image

    # Look for group nodes that might contain environment textures
    for node in world.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree is not None:
            for inner_node in node.node_tree.nodes:
                if inner_node.type == 'TEX_ENVIRONMENT':
                    if inner_node.image is not None:
                        return inner_node.image
                if inner_node.type == 'TEX_IMAGE':
                    if inner_node.image is not None:
                        return inner_node.image

    return None


def render_cubemap_faces(resolution, export_settings):
    """
    Render the environment as 6 cubemap faces using Blender's rendering.

    Args:
        resolution: Resolution of each face (e.g., 512)
        export_settings: Export settings dict

    Returns:
        list: List of 6 temp file paths for each face, or None on failure
    """
    import bpy

    resolution = int(resolution)

    # Store original settings
    scene = bpy.context.scene
    original_engine = scene.render.engine
    original_res_x = scene.render.resolution_x
    original_res_y = scene.render.resolution_y
    original_film_transparent = scene.render.film_transparent

    # Create a temporary camera for rendering
    cam_data = bpy.data.cameras.new("KTX2_EnvMap_Camera")
    cam_data.type = 'PANO'
    cam_data.cycles.panorama_type = 'EQUIRECTANGULAR'
    cam_obj = bpy.data.objects.new("KTX2_EnvMap_Camera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    original_camera = scene.camera
    scene.camera = cam_obj

    # Cubemap face directions (rotation in radians)
    # Order: +X, -X, +Y, -Y, +Z, -Z
    face_rotations = [
        (math.radians(90), 0, math.radians(-90)),   # +X (right)
        (math.radians(90), 0, math.radians(90)),    # -X (left)
        (math.radians(0), 0, 0),                     # +Y (top)
        (math.radians(180), 0, 0),                   # -Y (bottom)
        (math.radians(90), 0, 0),                    # +Z (front)
        (math.radians(90), 0, math.radians(180)),   # -Z (back)
    ]
    face_names = ['+X', '-X', '+Y', '-Y', '+Z', '-Z']

    temp_files = []

    try:
        # Setup render settings
        scene.render.engine = 'CYCLES'
        scene.render.resolution_x = resolution
        scene.render.resolution_y = resolution
        scene.render.film_transparent = False

        # Use a perspective camera with 90 degree FOV for cubemap faces
        cam_data.type = 'PERSP'
        cam_data.angle = math.radians(90)

        for i, (rx, ry, rz) in enumerate(face_rotations):
            cam_obj.rotation_euler = (rx, ry, rz)

            # Create temp file for this face
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.close()
            temp_files.append(temp_file.name)

            scene.render.filepath = temp_file.name
            scene.render.image_settings.file_format = 'PNG'

            # Render
            bpy.ops.render.render(write_still=True)

        return temp_files

    except Exception as e:
        export_settings['log'].error(f"Failed to render cubemap faces: {e}")
        # Clean up any temp files created
        for f in temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        return None

    finally:
        # Restore original settings
        scene.render.engine = original_engine
        scene.render.resolution_x = original_res_x
        scene.render.resolution_y = original_res_y
        scene.render.film_transparent = original_film_transparent
        scene.camera = original_camera

        # Clean up temp camera
        bpy.data.objects.remove(cam_obj)
        bpy.data.cameras.remove(cam_data)


def equirect_to_cubemap_faces(env_image, resolution, export_settings):
    """
    Convert an equirectangular image to 6 cubemap faces using numpy.

    Args:
        env_image: Blender image (equirectangular)
        resolution: Resolution of each face
        export_settings: Export settings dict

    Returns:
        tuple: (list of 6 temp file paths, intensity_factor) or (None, 1.0) on failure
    """
    import numpy as np

    resolution = int(resolution)

    try:
        # Get image pixels
        width, height = env_image.size
        if width == 0 or height == 0:
            return None, 1.0

        # Get pixel data as numpy array
        pixels = np.array(env_image.pixels[:])
        channels = len(pixels) // (width * height)
        pixels = pixels.reshape((height, width, channels))

        # Flip vertically (Blender stores bottom-to-top)
        pixels = np.flipud(pixels)

        # For HDR images, calculate intensity to compensate for clipping
        rgb_pixels = pixels[:, :, :3] if channels >= 3 else pixels
        max_value = np.max(rgb_pixels)

        if max_value > 1.0:
            # Calculate mean before and after clipping to determine intensity factor
            mean_before = np.mean(rgb_pixels)
            clipped = np.clip(rgb_pixels, 0.0, 1.0)
            mean_after = np.mean(clipped)

            # Intensity factor compensates for lost brightness from clipping
            # Add 1.3x boost to compensate for compression losses
            if mean_after > 0:
                intensity_factor = (mean_before / mean_after) * 1.3
            else:
                intensity_factor = 1.0

            pixels = np.clip(pixels, 0.0, 1.0)
        else:
            intensity_factor = 1.0

        temp_files = []

        # Face directions for sampling
        # Each face is defined by its forward direction and up direction
        face_configs = [
            # +X (right): look right, up is Y+
            lambda u, v: (1.0, v, -u),
            # -X (left): look left, up is Y+
            lambda u, v: (-1.0, v, u),
            # +Y (top): look up, up is Z-
            lambda u, v: (u, 1.0, -v),
            # -Y (bottom): look down, up is Z+
            lambda u, v: (u, -1.0, v),
            # +Z (front): look forward, up is Y+
            lambda u, v: (u, v, 1.0),
            # -Z (back): look back, up is Y+
            lambda u, v: (-u, v, -1.0),
        ]

        for face_idx, dir_func in enumerate(face_configs):
            # Create face image
            face = np.zeros((resolution, resolution, channels), dtype=np.float32)

            for y in range(resolution):
                for x in range(resolution):
                    # Map pixel to [-1, 1] range
                    u = (2.0 * x / resolution) - 1.0
                    v = (2.0 * y / resolution) - 1.0

                    # Get 3D direction
                    dx, dy, dz = dir_func(u, v)

                    # Normalize
                    length = math.sqrt(dx*dx + dy*dy + dz*dz)
                    dx, dy, dz = dx/length, dy/length, dz/length

                    # Convert to spherical coordinates
                    theta = math.atan2(dx, dz)  # longitude
                    phi = math.asin(dy)          # latitude

                    # Map to equirectangular UV
                    eq_u = (theta + math.pi) / (2.0 * math.pi)
                    eq_v = (phi + math.pi/2.0) / math.pi

                    # Sample from equirectangular image
                    src_x = int(eq_u * (width - 1))
                    src_y = int((1.0 - eq_v) * (height - 1))

                    src_x = max(0, min(width - 1, src_x))
                    src_y = max(0, min(height - 1, src_y))

                    face[resolution - 1 - y, x] = pixels[src_y, src_x]

            # Save face to temp file
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_file.close()

            # Convert to 8-bit and save using Blender
            face_img = bpy.data.images.new(
                f"ktx2_cubemap_face_{face_idx}",
                width=resolution,
                height=resolution,
                alpha=channels == 4
            )
            face_img.pixels = face.flatten().tolist()
            face_img.filepath_raw = temp_file.name
            face_img.file_format = 'PNG'
            face_img.save()
            bpy.data.images.remove(face_img)

            temp_files.append(temp_file.name)

        return temp_files, intensity_factor

    except Exception as e:
        export_settings['log'].error(f"Failed to convert equirectangular to cubemap: {e}")
        import traceback
        export_settings['log'].debug(traceback.format_exc())
        return None, 1.0


def encode_cubemap_to_ktx2(face_files, compression_mode, quality_level, generate_mipmaps, export_settings):
    """
    Encode 6 cubemap face images to a single KTX2 cubemap file.

    Args:
        face_files: List of 6 temp file paths for each face
        compression_mode: 'ETC1S' or 'UASTC'
        quality_level: Quality level
        generate_mipmaps: Whether to generate mipmaps
        export_settings: Export settings dict

    Returns:
        bytes: KTX2 cubemap data, or None on failure
    """
    from . import ktx_tools

    # Create temp file for KTX2 output
    temp_ktx2 = tempfile.NamedTemporaryFile(suffix='.ktx2', delete=False)
    temp_ktx2_path = Path(temp_ktx2.name)
    temp_ktx2.close()

    try:
        toktx_path = ktx_tools.get_tool_path('toktx')
        if not toktx_path:
            export_settings['log'].error("toktx not found")
            return None

        # Build toktx command for cubemap
        cmd = [str(toktx_path)]

        # Cubemap flag
        cmd.append('--cubemap')

        # Compression options
        if compression_mode == 'UASTC':
            cmd.append('--uastc')
            quality = min(quality_level // 64, 4)
            cmd.extend(['--uastc_quality', str(quality)])
            cmd.append('--uastc_rdo')
        else:
            cmd.append('--bcmp')
            cmd.extend(['--qlevel', str(quality_level)])

        # Mipmaps
        if generate_mipmaps:
            cmd.append('--genmipmap')

        # Output file
        cmd.append(str(temp_ktx2_path))

        # Input files (6 faces in order: +X, -X, +Y, -Y, +Z, -Z)
        for face_file in face_files:
            cmd.append(face_file)

        # Run toktx
        import subprocess
        env = ktx_tools.get_tool_environment()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env
        )

        if result.returncode != 0:
            export_settings['log'].error(f"toktx cubemap failed: {result.stderr}")
            return None

        # Read the KTX2 data
        with open(temp_ktx2_path, 'rb') as f:
            ktx2_bytes = f.read()

        return ktx2_bytes

    except Exception as e:
        export_settings['log'].error(f"Cubemap encoding failed: {e}")
        return None

    finally:
        # Clean up temp KTX2 file
        try:
            if temp_ktx2_path.exists():
                os.unlink(temp_ktx2_path)
        except OSError:
            pass


def export_environment_map(properties, export_settings):
    """
    Export the world environment as a KTX2 cubemap.

    Args:
        properties: KTX2ExportProperties
        export_settings: Export settings dict

    Returns:
        tuple: (ktx2_bytes, extension_data) or (None, None) on failure
    """
    # Check for environment texture
    env_image = get_world_environment_texture()
    if env_image is None:
        return None, None


    resolution = properties.envmap_resolution
    face_files = None
    intensity_factor = 1.0

    try:
        # Convert equirectangular to cubemap faces
        face_files, intensity_factor = equirect_to_cubemap_faces(
            env_image,
            resolution,
            export_settings
        )

        if face_files is None or len(face_files) != 6:
            export_settings['log'].error("Failed to create cubemap faces")
            return None, None

        # Encode to KTX2 cubemap
        ktx2_bytes = encode_cubemap_to_ktx2(
            face_files,
            properties.compression_mode,
            properties.quality_level,
            properties.generate_mipmaps,
            export_settings
        )

        if ktx2_bytes is None:
            return None, None


        return ktx2_bytes, {
            'intensity': intensity_factor,
        }

    finally:
        # Clean up face temp files
        if face_files:
            for f in face_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
