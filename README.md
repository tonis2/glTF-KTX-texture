# glTF KTX2 Texture Extension

Blender addon that adds KTX2 texture support to glTF export/import.

## Features

- **KTX2 Texture Export**: Converts textures to KTX2 format with Basis Universal compression (ETC1S or UASTC)
- **KTX2 Texture Import**: Decodes KTX2 textures back to standard formats for Blender
- **Environment Map Export**: Exports world environment as KTX2 cubemap (KHR_environment_map extension)
- **Environment Map Import**: Imports KTX2 cubemaps and sets up world environment

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
- Choose compression mode (ETC1S for smaller files, UASTC for higher quality)
- Optionally export environment map as cubemap

**Import:**
- KTX2 textures are automatically decoded when importing glTF files

## glTF Extensions Used

- `KHR_texture_basisu` - For KTX2 compressed textures
- `KHR_environment_map` - For environment cubemaps
