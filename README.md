# glTF KTX2 Texture Extension

Blender addon that adds KTX2 texture support to glTF export/import.

## Features

- **KTX2 Texture Export**: Converts textures to KTX2 format with multiple compression options
- **KTX2 Texture Import**: Decodes KTX2 textures back to standard formats for Blender
- **Environment Map Export**: Exports world environment as KTX2 cubemap (KHR_environment_map extension)
- **Environment Map Import**: Imports KTX2 cubemaps and sets up world environment

## Texture Formats

### Basis Universal (Universal)
Transcodes to any GPU format at runtime (BC7, ASTC, ETC2, etc.). Best compatibility across all platforms.

| Mode | Description |
|------|-------------|
| **ETC1S** | Smaller files, good for diffuse/color textures |
| **UASTC** | Higher quality, best for normal maps and fine details |

### Native ASTC (Direct GPU Upload)
Native ASTC format that uploads directly to GPU without any transcoding.

| Block Size | Quality | Bits/pixel |
|------------|---------|------------|
| 4x4 | Highest | 8.00 bpp |
| 5x5 | High | 5.12 bpp |
| 6x6 | Balanced | 3.56 bpp |
| 8x8 | Smallest | 2.00 bpp |

Supported hardware:
- Modern Android devices
- Apple Silicon (M1/M2/M3/M4 Macs, all iPhones/iPads)
- Some desktop GPUs with ASTC support

> **Note**: Use Basis Universal for maximum compatibility. Use Native ASTC when targeting ASTC-capable hardware for zero transcoding overhead.

## Supported Export Formats

- GLB (binary)
- glTF Embedded
- glTF Separate (with external .ktx2 files)

## Requirements

- Blender 4.0+
- [KTX-Software tools](https://github.com/KhronosGroup/KTX-Software/releases/) (downloaded automatically on first use, can take few minutes ~7MB)

## Installation

1. Download the latest [gltf_ktx2_extension.zip](https://github.com/tonis2/glTF-KTX-texture/tags)
2. In Blender: Edit > Preferences > Add-ons > Install
3. Select the addon folder or zip file
4. Enable "glTF KTX2 Texture Extension"

## Usage

The extension adds options to the glTF export/import panels:

**Export:**
- Enable "KTX2 Textures" to convert textures to KTX2
- Choose target format:
  - **Basis Universal**: Universal compatibility, transcodes to any GPU format at runtime (ETC1S or UASTC mode)
  - **Native ASTC**: Direct GPU upload on ASTC hardware, no transcoding (configurable block size)
- Optionally generate mipmaps
- Optionally keep original texture as fallback
- Optionally export environment map as cubemap

**Import:**
- KTX2 textures are automatically decoded when importing glTF files

## glTF Extensions Used

- `KHR_texture_basisu` - For KTX2 compressed textures
- `KHR_environment_map` - For environment cubemaps
