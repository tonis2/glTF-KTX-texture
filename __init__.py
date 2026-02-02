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

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


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

    compression_mode: bpy.props.EnumProperty(
        name="Compression",
        description="Basis Universal compression mode",
        items=[
            ('ETC1S', "ETC1S", "Smaller files, lower quality. Best for diffuse/color textures"),
            ('UASTC', "UASTC", "Larger files, higher quality. Best for normal maps and fine details"),
        ],
        default='ETC1S'
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
            body.prop(props, 'compression_mode')
            # Show appropriate quality range based on mode
            if props.compression_mode == 'UASTC':
                body.prop(props, 'quality_level', text="Quality (0-4)")
            else:
                body.prop(props, 'quality_level', text="Quality (1-255)")
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
                self.properties.compression_mode,
                self.properties.quality_level,
                self.properties.generate_mipmaps,
                export_settings
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

        from . import ktx2_envmap
        from io_scene_gltf2.io.com import gltf2_io

        # Export the environment map
        ktx2_bytes, env_data = ktx2_envmap.export_environment_map(
            self.properties,
            export_settings
        )

        if ktx2_bytes is None:
            return

        # Create the KTX2 image for the cubemap
        # Use URI with ImageData for separate files, or buffer_view for GLB
        if export_settings['gltf_format'] == 'GLTF_SEPARATE':
            from .ktx2_encode import KTX2ImageData
            image_data = KTX2ImageData(
                data=ktx2_bytes,
                mime_type="image/ktx2",
                name="environment_cubemap"
            )
            env_image = gltf2_io.Image(
                buffer_view=None,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name="environment_cubemap",
                uri=image_data
            )
        else:
            # For GLB, use buffer_view like regular images
            from io_scene_gltf2.io.exp.binary_data import BinaryData
            buffer_view = BinaryData(data=ktx2_bytes)

            env_image = gltf2_io.Image(
                buffer_view=buffer_view,
                extensions=None,
                extras=None,
                mime_type="image/ktx2",
                name="environment_cubemap",
                uri=None
            )

        # Add image to glTF images array
        if gltf.images is None:
            gltf.images = []
        gltf.images.append(env_image)
        cubemap_image_index = len(gltf.images) - 1

        # Create texture referencing the cubemap image by index
        env_texture = gltf2_io.Texture(
            extensions=None,
            extras=None,
            name="environment_cubemap",
            sampler=None,
            source=cubemap_image_index  # Use index, not object
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

        export_settings['log'].info("Added KHR_environment_map extension with cubemap")


class glTF2ImportUserExtension:
    """Import extension for KTX2 texture support."""

    def __init__(self):
        self.properties = bpy.context.scene.KTX2ImportProperties
        self._decoded_images = {}  # Cache decoded images by index

    def gather_import_texture_before_hook(self, gltf_texture, mh, tex_info, location, label,
                                          color_socket, alpha_socket, is_data):
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

        gltf = mh.gltf

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
        img_name = gltf_img.name or f'KTX2_Image_{img_idx}'

        blender_image = bpy.data.images.new(img_name, 8, 8)
        blender_image.pack(data=png_data, data_len=len(png_data))
        blender_image.source = 'FILE'
        blender_image.alpha_mode = 'CHANNEL_PACKED'

        # Mark as already processed so the importer doesn't try again
        gltf_img.blender_image_name = blender_image.name
        self._decoded_images[img_idx] = blender_image.name

        gltf.log.info(f"Decoded KTX2 image: {img_name}")


def register():
    """Register addon classes and UI."""
    bpy.utils.register_class(KTX2_OT_install_tools)
    bpy.utils.register_class(KTX2_OT_check_installation)
    bpy.utils.register_class(KTX2ExportProperties)
    bpy.utils.register_class(KTX2ImportProperties)

    bpy.types.Scene.KTX2ExportProperties = bpy.props.PointerProperty(type=KTX2ExportProperties)
    bpy.types.Scene.KTX2ImportProperties = bpy.props.PointerProperty(type=KTX2ImportProperties)

    # Check tools availability on load
    check_tools_available()


def unregister():
    """Unregister addon classes and UI."""
    del bpy.types.Scene.KTX2ExportProperties
    del bpy.types.Scene.KTX2ImportProperties

    bpy.utils.unregister_class(KTX2ImportProperties)
    bpy.utils.unregister_class(KTX2ExportProperties)
    bpy.utils.unregister_class(KTX2_OT_check_installation)
    bpy.utils.unregister_class(KTX2_OT_install_tools)


def glTF2_pre_export_callback(export_settings):
    """Called before export starts."""
    pass


def glTF2_post_export_callback(export_settings):
    """Called after export completes."""
    pass
