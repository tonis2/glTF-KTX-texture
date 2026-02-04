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
KTX2 Texture Support for glTF-Blender-IO

This addon adds KTX2 texture support to glTF export/import via the KHR_texture_basisu extension.
It uses the official Khronos KTX-Software command-line tools for encoding/decoding.

The tools are automatically downloaded on first use (~7MB).
"""

import bpy
import importlib

# Debug: Print when module is loaded to verify code is up to date
print("KTX2 Extension: Module loaded (version with post-process debugging)")


def _reload_submodules():
    """Reload all submodules to pick up code changes during development."""
    import sys

    # List of submodule names (without package prefix)
    submodule_names = ['ktx_tools', 'ktx2_encode', 'ktx2_decode', 'ktx2_envmap_encode', 'ktx2_envmap_decode']

    # Get the package name (this module's package)
    package = __name__

    for name in submodule_names:
        full_name = f"{package}.{name}"
        if full_name in sys.modules:
            print(f"KTX2 Extension: Reloading {name}")
            importlib.reload(sys.modules[full_name])

bl_info = {
    "name": "glTF KTX2 Texture Extension",
    "category": "Import-Export",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "File > Export/Import > glTF 2.0",
    "description": "Add KTX2 texture support via KHR_texture_basisu extension",
    "tracker_url": "https://github.com/KhronosGroup/glTF-Blender-IO/issues/",
    "isDraft": False,
    "developer": "glTF-Blender-IO Contributors",
    "url": "https://github.com/KhronosGroup/glTF-Blender-IO",
}

# glTF extension name following Khronos naming convention
glTF_extension_name = "KHR_texture_basisu"

# KTX2 textures require the extension for proper viewing
extension_is_required = False

# Track installation state
_tools_available = None
_installation_in_progress = False


def check_tools_available(force_recheck=False):
    """Check if KTX tools are available."""
    global _tools_available
    if _tools_available is None or force_recheck:
        from . import ktx_tools
        _tools_available = ktx_tools.are_tools_installed()
    return _tools_available


class KTX2_OT_install_tools(bpy.types.Operator):
    """Download and install KTX tools for KTX2 texture support"""
    bl_idname = "ktx2.install_tools"
    bl_label = "Download KTX Tools"
    bl_description = "Download KTX-Software tools (~7MB) for KTX2 encoding/decoding"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _installation_in_progress
        _installation_in_progress = True

        from . import ktx_tools

        try:
            self.report({'INFO'}, "Downloading KTX tools... This may take a moment.")

            def progress_callback(message, percent):
                # Can't easily update UI from here, but we report at key points
                pass

            success, error = ktx_tools.install_tools(progress_callback)

            if success:
                check_tools_available(force_recheck=True)
                self.report({'INFO'}, "KTX tools installed successfully!")
            else:
                self.report({'ERROR'}, f"Installation failed: {error}")
                print(f"\nKTX Tools Installation Error: {error}\n")

        except Exception as e:
            self.report({'ERROR'}, f"Installation failed: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            _installation_in_progress = False

        return {'FINISHED'}


class KTX2_OT_check_installation(bpy.types.Operator):
    """Check if KTX tools are installed"""
    bl_idname = "ktx2.check_installation"
    bl_label = "Check Installation"
    bl_description = "Recheck if KTX tools are available"

    def execute(self, context):
        check_tools_available(force_recheck=True)
        if check_tools_available():
            self.report({'INFO'}, "KTX tools are installed and ready!")
        else:
            self.report({'WARNING'}, "KTX tools are not available. Click 'Download KTX Tools' to install.")
        return {'FINISHED'}


class KTX2ExportProperties(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="KTX2 Textures",
        description="Export textures in KTX2 format using KHR_texture_basisu extension",
        default=False
    )

    target_format: bpy.props.EnumProperty(
        name="Target Format",
        description="GPU texture format. Native ASTC loads directly, Basis Universal transcodes at runtime",
        items=[
            ('BASISU', "Basis Universal", "Universal format that transcodes to any GPU (BC7, ASTC, ETC2, etc.) at runtime. Best compatibility"),
            ('ASTC', "Native ASTC", "Direct GPU upload on ASTC hardware (mobile, Apple Silicon). No transcoding needed"),
        ],
        default='BASISU'
    )

    compression_mode: bpy.props.EnumProperty(
        name="Compression",
        description="Basis Universal compression mode",
        items=[
            ('ETC1S', "ETC1S", "Smaller files, lower quality. Best for diffuse/color textures"),
            ('UASTC', "UASTC", "Larger files, higher quality. Best for normal maps and fine details"),
        ],
        default='ETC1S'
    )

    astc_block_size: bpy.props.EnumProperty(
        name="ASTC Block Size",
        description="ASTC compression block size. Smaller blocks = higher quality, larger files",
        items=[
            ('4x4', "4x4 (Highest Quality)", "8 bits/pixel - Best quality, largest files"),
            ('5x5', "5x5 (High Quality)", "5.12 bits/pixel - High quality"),
            ('6x6', "6x6 (Balanced)", "3.56 bits/pixel - Good balance of quality and size"),
            ('8x8', "8x8 (Smaller Files)", "2 bits/pixel - Smaller files, lower quality"),
        ],
        default='6x6'
    )

    quality_level: bpy.props.IntProperty(
        name="Quality",
        description="ETC1S: 1-255 (higher=better). UASTC: 0-4 (higher=better)",
        min=0,
        max=255,
        default=128
    )

    create_fallback: bpy.props.BoolProperty(
        name="Create Fallback",
        description="Keep original PNG/JPEG texture as fallback for viewers without KTX2 support",
        default=True
    )

    generate_mipmaps: bpy.props.BoolProperty(
        name="Generate Mipmaps",
        description="Pre-generate mipmaps in KTX2 file. Faster load times but ~33% larger files",
        default=False
    )

    export_environment_map: bpy.props.BoolProperty(
        name="Export Environment Map",
        description="Export world environment texture as KTX2 cubemap (KHR_environment_map extension - experimental)",
        default=False
    )

    envmap_resolution: bpy.props.EnumProperty(
        name="Cubemap Resolution",
        description="Resolution of each cubemap face",
        items=[
            ('256', "256", "256x256 per face (fast, low quality)"),
            ('512', "512", "512x512 per face (balanced)"),
            ('1024', "1024", "1024x1024 per face (high quality)"),
            ('2048', "2048", "2048x2048 per face (very high quality)"),
        ],
        default='512'
    )


class KTX2ImportProperties(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="KTX2 Textures",
        description="Import KTX2 textures from KHR_texture_basisu extension",
        default=True
    )

    prefer_ktx2: bpy.props.BoolProperty(
        name="Prefer KTX2",
        description="When both KTX2 and fallback textures exist, prefer KTX2 source",
        default=True
    )


def draw_install_tools_ui(layout):
    """Draw the KTX tools installation UI."""
    box = layout.box()
    box.label(text="KTX tools required", icon='INFO')

    if _installation_in_progress:
        box.label(text="Downloading... please wait")
        box.enabled = False
    else:
        col = box.column(align=True)
        col.operator("ktx2.install_tools", icon='IMPORT')
        col.operator("ktx2.check_installation", icon='FILE_REFRESH')
        col.label(text="One-time download (~7MB)", icon='URL')


def draw_export(context, layout):
    """Draw export UI panel."""
    header, body = layout.panel("GLTF_addon_ktx2_exporter", default_closed=True)
    header.use_property_split = False

    props = context.scene.KTX2ExportProperties

    header.prop(props, 'enabled')

    if body is not None:
        if not check_tools_available():
            draw_install_tools_ui(body)
        else:
            body.prop(props, 'target_format')

            # Show format-specific options
            if props.target_format == 'BASISU':
                body.prop(props, 'compression_mode')
                # Show appropriate quality range based on mode
                if props.compression_mode == 'UASTC':
                    body.prop(props, 'quality_level', text="Quality (0-4)")
                else:
                    body.prop(props, 'quality_level', text="Quality (1-255)")
            elif props.target_format == 'ASTC':
                body.prop(props, 'astc_block_size')

            body.prop(props, 'generate_mipmaps')
            body.prop(props, 'create_fallback')

            body.separator()
            body.label(text="Environment Map (Experimental):")
            body.prop(props, 'export_environment_map')
            if props.export_environment_map:
                body.prop(props, 'envmap_resolution')


def draw_import(context, layout):
    """Draw import UI panel."""
    header, body = layout.panel("GLTF_addon_ktx2_importer", default_closed=True)
    header.use_property_split = False

    props = context.scene.KTX2ImportProperties

    header.prop(props, 'enabled')

    if body is not None:
        if not check_tools_available():
            draw_install_tools_ui(body)
        else:
            body.prop(props, 'prefer_ktx2')


class glTF2ExportUserExtension:
    """Export extension for KTX2 texture support."""

    def __init__(self):
        from io_scene_gltf2.io.com.gltf2_io_extensions import Extension
        self.Extension = Extension
        self.properties = bpy.context.scene.KTX2ExportProperties
        self._processed_images = {}  # Cache to avoid processing same image twice

    def gather_texture_hook(self, gltf2_texture, blender_shader_sockets, export_settings):
        """Hook called when gathering texture data for export."""
        if not self.properties.enabled:
            return

        if not check_tools_available():
            export_settings['log'].warning("KTX2 export disabled: KTX tools not installed")
            return

        if gltf2_texture.source is None:
            return

        from . import ktx2_encode

        # Get the source image
        source_image = gltf2_texture.source

        # Check if we already processed this image
        cache_key = id(source_image)
        if cache_key in self._processed_images:
            ktx2_image = self._processed_images[cache_key]
        else:
            # Encode to KTX2
            ktx2_image = ktx2_encode.encode_image_to_ktx2(
                source_image,
                self.properties.target_format,
                self.properties.compression_mode,
                self.properties.quality_level,
                self.properties.generate_mipmaps,
                export_settings,
                astc_block_size=self.properties.astc_block_size
            )
            if ktx2_image is None:
                export_settings['log'].warning(
                    f"Failed to encode image to KTX2: {getattr(source_image, 'name', 'unknown')}"
                )
                return

            self._processed_images[cache_key] = ktx2_image

        # Add KHR_texture_basisu extension to texture
        if gltf2_texture.extensions is None:
            gltf2_texture.extensions = {}

        ext_data = {"source": ktx2_image}

        gltf2_texture.extensions[glTF_extension_name] = self.Extension(
            name=glTF_extension_name,
            extension=ext_data,
            required=not self.properties.create_fallback
        )

        # If no fallback wanted, remove the original source
        if not self.properties.create_fallback:
            gltf2_texture.source = None

    def gather_gltf_extensions_hook(self, gltf, export_settings):
        """Hook called to add root-level extensions like KHR_environment_map."""
        if not self.properties.export_environment_map:
            return

        if not check_tools_available():
            export_settings['log'].warning("Environment map export disabled: KTX tools not installed")
            return

        from . import ktx2_envmap_encode
        from io_scene_gltf2.io.com import gltf2_io

        # Export the environment map
        ktx2_bytes, env_data = ktx2_envmap_encode.export_environment_map(
            self.properties,
            export_settings
        )

        if ktx2_bytes is None:
            return

        # Create the KTX2 image for the cubemap
        if export_settings['gltf_format'] == 'GLTF_SEPARATE':
            # For separate files, write KTX2 file directly and use filename as URI
            import os
            filepath = export_settings.get('gltf_filepath', '')
            output_dir = os.path.dirname(filepath)
            ktx2_filename = "environment_cubemap.ktx2"
            ktx2_filepath = os.path.join(output_dir, ktx2_filename)

            # Write KTX2 file
            with open(ktx2_filepath, 'wb') as f:
                f.write(ktx2_bytes)

            env_image = gltf2_io.Image(
                buffer_view=None,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name="environment_cubemap",
                uri=ktx2_filename
            )
        else:
            # For GLB/embedded formats, we must use base64 data URI
            # Note: Using buffer_view with BinaryData doesn't work in gather_gltf_extensions_hook
            # because BinaryData processing has already completed at this stage
            import base64
            b64_data = base64.b64encode(ktx2_bytes).decode('ascii')
            data_uri = f"data:image/ktx2;base64,{b64_data}"

            env_image = gltf2_io.Image(
                buffer_view=None,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name="environment_cubemap",
                uri=data_uri
            )

        # Add image to glTF images array
        if gltf.images is None:
            gltf.images = []
        gltf.images.append(env_image)
        cubemap_image_index = len(gltf.images) - 1

        # Mark that we exported an environment map and schedule post-processing
        export_settings['ktx2_envmap_exported'] = True

        # Schedule post-processing to convert data URI to bufferView
        filepath = export_settings.get('gltf_filepath', '')
        gltf_format = export_settings['gltf_format']
        import sys
        print(f"KTX2 Extension: Export format={gltf_format}, filepath={filepath}")
        sys.stdout.flush()

        # Post-process for formats that use binary buffers
        if gltf_format in ('GLB', 'GLTF_EMBEDDED', 'GLTF_SEPARATE'):
            _schedule_post_process(filepath, gltf_format)

        # Create texture referencing the cubemap image by index
        # Use KHR_environment_map extension since cubemap is always KTX2 in this extension
        env_texture = gltf2_io.Texture(
            extensions={
                "KHR_environment_map": {"source": cubemap_image_index}
            },
            extras=None,
            name="environment_cubemap",
            sampler=None,
            source=None  # No fallback source, using extension only
        )

        if gltf.textures is None:
            gltf.textures = []
        gltf.textures.append(env_texture)
        cubemap_texture_index = len(gltf.textures) - 1

        # Add KHR_environment_map extension to glTF root
        if gltf.extensions is None:
            gltf.extensions = {}

        # Extension data following the proposed spec
        extension_data = {
            "environmentMaps": [
                {
                    "cubemap": cubemap_texture_index,
                    "intensity": env_data.get('intensity', 1.0),
                }
            ]
        }

        gltf.extensions["KHR_environment_map"] = self.Extension(
            name="KHR_environment_map",
            extension=extension_data,
            required=False
        )

        # Add to extensionsUsed
        if gltf.extensions_used is None:
            gltf.extensions_used = []
        if "KHR_environment_map" not in gltf.extensions_used:
            gltf.extensions_used.append("KHR_environment_map")
        sys.stdout.flush()


class _ImportExtensionInfo:
    """Simple class to hold extension info for the importer."""
    def __init__(self, name, required=True):
        self.name = name
        self.required = required


class glTF2ImportUserExtension:
    """Import extension for KTX2 texture support."""

    def __init__(self):
        self.properties = bpy.context.scene.KTX2ImportProperties
        self._decoded_images = {}  # Cache decoded images by index
        # Declare that we handle KHR_texture_basisu and KHR_environment_map extensions
        self.extensions = [
            _ImportExtensionInfo(glTF_extension_name, required=True),
            _ImportExtensionInfo("KHR_environment_map", required=False)
        ]

    def gather_import_texture_before_hook(self, gltf_texture, mh, tex_info, location, label,
                                          color_socket, alpha_socket, is_data, gltf):
        """Hook called before importing a texture - select KTX2 source if available."""
        if not self.properties.enabled:
            return

        if not check_tools_available():
            return

        # Check for KHR_texture_basisu extension
        try:
            ktx2_source = gltf_texture.extensions['KHR_texture_basisu']['source']
        except (AttributeError, KeyError, TypeError):
            return

        if ktx2_source is None:
            return

        # Check user preference for KTX2 vs fallback
        if self.properties.prefer_ktx2:
            # Prefer KTX2: use the KTX2 source
            # Store original source as fallback reference
            gltf_texture._original_source = gltf_texture.source
            gltf_texture.source = ktx2_source
        else:
            # Prefer fallback: only use KTX2 if no fallback exists
            if gltf_texture.source is None:
                gltf_texture.source = ktx2_source

    def gather_import_image_before_hook(self, gltf_img, gltf):
        """Hook called before importing an image - decode KTX2 if needed."""
        if not self.properties.enabled:
            return

        if not check_tools_available():
            return

        # Check if this is a KTX2 image
        mime_type = getattr(gltf_img, 'mime_type', None)
        if mime_type != "image/ktx2":
            return

        from . import ktx2_decode
        from io_scene_gltf2.io.imp.gltf2_io_binary import BinaryData

        # Get image index
        try:
            img_idx = gltf.data.images.index(gltf_img)
        except ValueError:
            gltf.log.warning("Could not find image index for KTX2 image")
            return

        # Check cache
        if img_idx in self._decoded_images:
            return

        # Get KTX2 binary data
        ktx2_data = BinaryData.get_image_data(gltf, img_idx)

        # If BinaryData returns None, try loading from URI (for separate files)
        if ktx2_data is None and gltf_img.uri:
            uri = gltf_img.uri
            if not uri.startswith('data:'):
                # It's a file URI, load from disk
                import os
                gltf_dir = os.path.dirname(gltf.filename)
                file_path = os.path.join(gltf_dir, uri)
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        ktx2_data = f.read()

        if ktx2_data is None:
            gltf.log.warning(f"Could not get KTX2 data for image {img_idx}")
            return

        # Convert to bytes if needed
        if hasattr(ktx2_data, 'tobytes'):
            ktx2_data = ktx2_data.tobytes()

        # Decode KTX2 to PNG
        png_data = ktx2_decode.decode_ktx2_to_png(ktx2_data, gltf)
        if png_data is None:
            gltf.log.warning(f"Failed to decode KTX2 image {img_idx}")
            return

        # Create Blender image from decoded PNG data
        # We need to write to a temp file and load it, since pack() expects raw pixels
        import tempfile
        import os

        img_name = gltf_img.name or f'KTX2_Image_{img_idx}'

        temp_png = None
        try:
            # Write PNG to temp file
            temp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_png.write(png_data)
            temp_png.close()

            # Load the image from temp file
            blender_image = bpy.data.images.load(temp_png.name)
            blender_image.name = img_name
            blender_image.alpha_mode = 'CHANNEL_PACKED'

            # Pack the image into the .blend file so the temp file can be deleted
            blender_image.pack()

            # Mark as already processed so the importer doesn't try again
            gltf_img.blender_image_name = blender_image.name
            self._decoded_images[img_idx] = blender_image.name

            # Clear the buffer_view so the main importer's create_from_data()
            # returns None and doesn't overwrite our blender_image_name
            gltf_img.buffer_view = None
            gltf_img.uri = None

        finally:
            # Clean up temp file
            if temp_png:
                try:
                    os.unlink(temp_png.name)
                except OSError:
                    pass

    def gather_import_scene_after_nodes_hook(self, gltf_scene, blender_scene, gltf):
        """Hook called after scene nodes are created - import environment map."""
        if not self.properties.enabled:
            return

        # Check for KHR_environment_map extension
        if gltf.data.extensions is None:
            return

        env_map_ext = gltf.data.extensions.get('KHR_environment_map')
        if env_map_ext is None:
            return

        from . import ktx2_envmap_decode

        try:
            ktx2_envmap_decode.import_environment_map(env_map_ext, gltf)
        except Exception as e:
            gltf.log.error(f"Failed to import environment map: {e}")
            import traceback
            traceback.print_exc()


def register():
    """Register addon classes and UI."""
    # Reload submodules to pick up code changes (for development)
    _reload_submodules()

    bpy.utils.register_class(KTX2_OT_install_tools)
    bpy.utils.register_class(KTX2_OT_check_installation)
    bpy.utils.register_class(KTX2ExportProperties)
    bpy.utils.register_class(KTX2ImportProperties)

    bpy.types.Scene.KTX2ExportProperties = bpy.props.PointerProperty(type=KTX2ExportProperties)
    bpy.types.Scene.KTX2ImportProperties = bpy.props.PointerProperty(type=KTX2ImportProperties)

    # Register UI panels with glTF addon (with duplicate check)
    try:
        from io_scene_gltf2 import exporter_extension_layout_draw, importer_extension_layout_draw
        if 'KTX2 Textures' not in exporter_extension_layout_draw:
            exporter_extension_layout_draw['KTX2 Textures'] = draw_export
        if 'KTX2 Textures' not in importer_extension_layout_draw:
            importer_extension_layout_draw['KTX2 Textures'] = draw_import
    except ImportError:
        print("glTF-Blender-IO addon not found. KTX2 extension panels will not be available.")

    # Check tools availability on load
    check_tools_available()


def unregister():
    """Unregister addon classes and UI."""
    # Unregister UI panels from glTF addon
    try:
        from io_scene_gltf2 import exporter_extension_layout_draw, importer_extension_layout_draw
        if 'KTX2 Textures' in exporter_extension_layout_draw:
            del exporter_extension_layout_draw['KTX2 Textures']
        if 'KTX2 Textures' in importer_extension_layout_draw:
            del importer_extension_layout_draw['KTX2 Textures']
    except (ImportError, KeyError):
        pass

    del bpy.types.Scene.KTX2ExportProperties
    del bpy.types.Scene.KTX2ImportProperties

    bpy.utils.unregister_class(KTX2ImportProperties)
    bpy.utils.unregister_class(KTX2ExportProperties)
    bpy.utils.unregister_class(KTX2_OT_check_installation)
    bpy.utils.unregister_class(KTX2_OT_install_tools)


def glTF2_pre_export_callback(export_settings):
    """Called before export starts."""
    # Clear the flag for environment map export
    export_settings['ktx2_envmap_exported'] = False


def glTF2_post_export_callback(export_settings):
    """Called after export completes. Post-process GLB to fix environment map bufferView."""
    _run_post_export(export_settings)


def _run_post_export(export_settings):
    """Run post-export processing."""
    # Only process if we exported an environment map in GLB format
    if not export_settings.get('ktx2_envmap_exported', False):
        return

    if export_settings['gltf_format'] not in ('GLB', 'GLTF_EMBEDDED'):
        return

    filepath = export_settings['gltf_filepath']
    if not filepath.lower().endswith('.glb'):
        return

    try:
        _post_process_glb_envmap(filepath, export_settings)
    except Exception as e:
        print(f"KTX2 Extension: Failed to post-process GLB for environment map: {e}")
        import traceback
        traceback.print_exc()


# Global storage for pending post-processing
_pending_post_process = None
_post_process_retries = 0
_MAX_POST_PROCESS_RETRIES = 50  # 50 * 0.2s = 10 seconds max wait


def _schedule_post_process(filepath, gltf_format):
    """Schedule GLB post-processing using a timer."""
    global _pending_post_process, _post_process_retries
    import sys

    print(f"KTX2 Extension: Scheduling post-process for {filepath} (format={gltf_format})")
    sys.stdout.flush()

    _pending_post_process = {
        'filepath': filepath,
        'gltf_format': gltf_format
    }
    _post_process_retries = 0  # Reset retry counter
    # Register timer to run after export completes
    try:
        bpy.app.timers.register(_timer_post_process, first_interval=0.5)
        print("KTX2 Extension: Timer registered successfully")
        sys.stdout.flush()
    except Exception as e:
        print(f"KTX2 Extension: Failed to register timer: {e}")
        sys.stdout.flush()
        import traceback
        traceback.print_exc()


def _timer_post_process():
    """Timer callback to post-process GLB/GLTF after export."""
    global _pending_post_process, _post_process_retries
    import sys
    import os
    import time

    print("KTX2 Extension: Timer callback invoked")
    sys.stdout.flush()

    if _pending_post_process is None:
        print("KTX2 Extension: No pending post-process, stopping timer")
        sys.stdout.flush()
        _post_process_retries = 0
        return None  # Stop timer

    filepath = _pending_post_process['filepath']
    gltf_format = _pending_post_process['gltf_format']

    # Check retry limit
    if _post_process_retries >= _MAX_POST_PROCESS_RETRIES:
        print(f"KTX2 Extension: Max retries ({_MAX_POST_PROCESS_RETRIES}) exceeded, giving up")
        sys.stdout.flush()
        _pending_post_process = None
        _post_process_retries = 0
        return None

    # Check if file exists
    if not os.path.exists(filepath):
        print(f"KTX2 Extension: File not found yet, retrying... ({_post_process_retries + 1}/{_MAX_POST_PROCESS_RETRIES})")
        sys.stdout.flush()
        _post_process_retries += 1
        return 0.2  # Try again in 0.2 seconds

    # Check if file is still being written by checking if size is stable
    try:
        size1 = os.path.getsize(filepath)
        time.sleep(0.05)  # Brief pause
        size2 = os.path.getsize(filepath)
        if size1 != size2:
            print(f"KTX2 Extension: File still being written, retrying... ({_post_process_retries + 1}/{_MAX_POST_PROCESS_RETRIES})")
            sys.stdout.flush()
            _post_process_retries += 1
            return 0.2
    except OSError:
        _post_process_retries += 1
        return 0.2

    # File is ready, clear pending state
    _pending_post_process = None
    _post_process_retries = 0

    print(f"KTX2 Extension: Timer triggered, processing {filepath}")
    sys.stdout.flush()

    try:
        if filepath.lower().endswith('.glb'):
            _post_process_glb_envmap(filepath, None)
        elif filepath.lower().endswith('.gltf'):
            _post_process_gltf_envmap(filepath, gltf_format)
    except Exception as e:
        print(f"KTX2 Extension: Failed to post-process for environment map: {e}")
        import traceback
        traceback.print_exc()

    return None  # Stop timer


def _post_process_glb_envmap(filepath, export_settings):
    """
    Post-process a GLB file to convert environment map data URI to bufferView.

    GLB format:
    - 12 byte header: magic (4), version (4), length (4)
    - JSON chunk: length (4), type "JSON" (4), json data (padded to 4 bytes)
    - Binary chunk: length (4), type "BIN\0" (4), binary data (padded to 4 bytes)
    """
    import json
    import base64
    import struct

    with open(filepath, 'rb') as f:
        glb_data = f.read()

    # Parse GLB header
    magic, version, total_length = struct.unpack('<III', glb_data[:12])
    if magic != 0x46546C67:  # 'glTF' in little-endian
        print("KTX2 Extension: Not a valid GLB file")
        return

    # Parse JSON chunk
    json_chunk_length, json_chunk_type = struct.unpack('<II', glb_data[12:20])
    if json_chunk_type != 0x4E4F534A:  # 'JSON' in little-endian
        print("KTX2 Extension: Invalid JSON chunk")
        return

    json_data = glb_data[20:20 + json_chunk_length].decode('utf-8').rstrip('\x00 ')
    gltf = json.loads(json_data)

    # Parse binary chunk (if exists)
    bin_chunk_start = 20 + json_chunk_length
    # Align to 4 bytes
    if bin_chunk_start % 4 != 0:
        bin_chunk_start += 4 - (bin_chunk_start % 4)

    binary_data = bytearray()
    if bin_chunk_start + 8 <= len(glb_data):
        bin_chunk_length, bin_chunk_type = struct.unpack('<II', glb_data[bin_chunk_start:bin_chunk_start + 8])
        if bin_chunk_type == 0x004E4942:  # 'BIN\0' in little-endian
            binary_data = bytearray(glb_data[bin_chunk_start + 8:bin_chunk_start + 8 + bin_chunk_length])

    # Find images with data URIs that are KTX2
    images = gltf.get('images', [])
    modified = False

    for i, image in enumerate(images):
        uri = image.get('uri', '')
        if isinstance(uri, str) and uri.startswith('data:image/ktx2;base64,'):
            # Extract base64 data
            b64_data = uri[len('data:image/ktx2;base64,'):]
            ktx2_bytes = base64.b64decode(b64_data)

            # Align binary buffer to 4 bytes before adding new data
            padding = (4 - len(binary_data) % 4) % 4
            if padding > 0:
                binary_data.extend(b'\x00' * padding)

            byte_offset = len(binary_data)
            binary_data.extend(ktx2_bytes)

            # Create or extend bufferViews
            if 'bufferViews' not in gltf:
                gltf['bufferViews'] = []

            buffer_view_index = len(gltf['bufferViews'])
            gltf['bufferViews'].append({
                'buffer': 0,
                'byteOffset': byte_offset,
                'byteLength': len(ktx2_bytes)
            })

            # Update image to use bufferView instead of URI
            del image['uri']
            image['bufferView'] = buffer_view_index
            image['mimeType'] = 'image/ktx2'

            modified = True

    if not modified:
        return

    # Update buffer length
    if 'buffers' not in gltf or len(gltf['buffers']) == 0:
        gltf['buffers'] = [{'byteLength': len(binary_data)}]
    else:
        gltf['buffers'][0]['byteLength'] = len(binary_data)

    # Rebuild GLB
    new_json = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    # Pad JSON to 4 bytes with spaces
    json_padding = (4 - len(new_json) % 4) % 4
    new_json += b' ' * json_padding

    # Pad binary to 4 bytes with zeros
    bin_padding = (4 - len(binary_data) % 4) % 4
    binary_data.extend(b'\x00' * bin_padding)

    # Calculate new total length
    new_total_length = 12 + 8 + len(new_json) + 8 + len(binary_data)

    # Build new GLB
    new_glb = bytearray()
    # Header
    new_glb.extend(struct.pack('<III', 0x46546C67, 2, new_total_length))
    # JSON chunk
    new_glb.extend(struct.pack('<II', len(new_json), 0x4E4F534A))
    new_glb.extend(new_json)
    # Binary chunk
    new_glb.extend(struct.pack('<II', len(binary_data), 0x004E4942))
    new_glb.extend(binary_data)

    # Write back
    with open(filepath, 'wb') as f:
        f.write(new_glb)

    print(f"KTX2 Extension: Successfully post-processed GLB, new size: {len(new_glb)} bytes")


def _post_process_gltf_envmap(filepath, gltf_format):
    """
    Post-process a GLTF file to convert environment map data URI to bufferView.

    Handles both:
    - GLTF_SEPARATE: JSON + separate .bin file
    - GLTF_EMBEDDED: JSON with base64-encoded buffer inline
    """
    import json
    import base64
    import os
    import sys

    print(f"KTX2 Extension: Post-processing GLTF file: {filepath}")
    sys.stdout.flush()

    with open(filepath, 'r', encoding='utf-8') as f:
        gltf = json.load(f)

    # Find images with data URIs that are KTX2
    images = gltf.get('images', [])
    modified = False
    ktx2_data_list = []  # Store data to append to buffer

    for i, image in enumerate(images):
        uri = image.get('uri', '')
        if isinstance(uri, str) and uri.startswith('data:image/ktx2;base64,'):
            # Extract base64 data
            b64_data = uri[len('data:image/ktx2;base64,'):]
            ktx2_bytes = base64.b64decode(b64_data)
            ktx2_data_list.append((i, image, ktx2_bytes))
            modified = True

    if not modified:
        print("KTX2 Extension: No KTX2 data URIs found to process")
        sys.stdout.flush()
        return

    # Get or create buffer
    buffers = gltf.get('buffers', [])

    # Determine if we have a separate .bin file or embedded buffer
    buffer_uri = buffers[0].get('uri', '') if buffers else ''
    is_embedded = not buffer_uri or buffer_uri.startswith('data:')

    if is_embedded:
        # GLTF_EMBEDDED: buffer is base64-encoded in the JSON
        print("KTX2 Extension: Processing embedded buffer format")
        sys.stdout.flush()

        # Decode existing buffer data (if any)
        if buffer_uri.startswith('data:'):
            # Extract base64 data from data URI
            # Format: data:application/octet-stream;base64,XXXXX
            comma_idx = buffer_uri.find(',')
            if comma_idx != -1:
                existing_b64 = buffer_uri[comma_idx + 1:]
                binary_data = bytearray(base64.b64decode(existing_b64))
            else:
                binary_data = bytearray()
        elif buffers and buffers[0].get('byteLength', 0) > 0:
            # Buffer exists but no data yet (shouldn't happen)
            binary_data = bytearray()
        else:
            # No existing buffer
            binary_data = bytearray()
            if not buffers:
                gltf['buffers'] = [{}]
                buffers = gltf['buffers']

        original_size = len(binary_data)

        # Process each KTX2 image
        if 'bufferViews' not in gltf:
            gltf['bufferViews'] = []

        for i, image, ktx2_bytes in ktx2_data_list:
            # Align binary buffer to 4 bytes before adding new data
            padding = (4 - len(binary_data) % 4) % 4
            if padding > 0:
                binary_data.extend(b'\x00' * padding)

            byte_offset = len(binary_data)
            binary_data.extend(ktx2_bytes)

            # Create bufferView
            buffer_view_index = len(gltf['bufferViews'])
            gltf['bufferViews'].append({
                'buffer': 0,
                'byteOffset': byte_offset,
                'byteLength': len(ktx2_bytes)
            })

            # Update image to use bufferView instead of URI
            del image['uri']
            image['bufferView'] = buffer_view_index
            image['mimeType'] = 'image/ktx2'
            sys.stdout.flush()

        # Update buffer with new base64-encoded data
        new_b64 = base64.b64encode(binary_data).decode('ascii')
        buffers[0]['uri'] = f"data:application/octet-stream;base64,{new_b64}"
        buffers[0]['byteLength'] = len(binary_data)

        # Write updated JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(gltf, f, separators=(',', ':'))

        sys.stdout.flush()

    else:
        # GLTF_SEPARATE: buffer is in a separate .bin file
        print("KTX2 Extension: Processing separate .bin file format")
        sys.stdout.flush()

        # Construct the path to the .bin file
        gltf_dir = os.path.dirname(filepath)
        bin_path = os.path.join(gltf_dir, buffer_uri)

        if not os.path.exists(bin_path):
            print(f"KTX2 Extension: Binary file not found: {bin_path}")
            sys.stdout.flush()
            return

        # Read existing binary data
        with open(bin_path, 'rb') as f:
            binary_data = bytearray(f.read())

        original_size = len(binary_data)

        # Process each KTX2 image
        if 'bufferViews' not in gltf:
            gltf['bufferViews'] = []

        for i, image, ktx2_bytes in ktx2_data_list:
            # Align binary buffer to 4 bytes before adding new data
            padding = (4 - len(binary_data) % 4) % 4
            if padding > 0:
                binary_data.extend(b'\x00' * padding)

            byte_offset = len(binary_data)
            binary_data.extend(ktx2_bytes)

            # Create bufferView
            buffer_view_index = len(gltf['bufferViews'])
            gltf['bufferViews'].append({
                'buffer': 0,
                'byteOffset': byte_offset,
                'byteLength': len(ktx2_bytes)
            })

            # Update image to use bufferView instead of URI
            del image['uri']
            image['bufferView'] = buffer_view_index
            image['mimeType'] = 'image/ktx2'
            sys.stdout.flush()

        # Update buffer length
        buffers[0]['byteLength'] = len(binary_data)

        # Write updated binary file
        with open(bin_path, 'wb') as f:
            f.write(binary_data)

        # Write updated JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(gltf, f, separators=(',', ':'))

        print(f"KTX2 Extension: Successfully post-processed GLTF")
        print(f"  Binary file grew from {original_size} to {len(binary_data)} bytes")
        print(f"  JSON updated: {filepath}")
        sys.stdout.flush()
