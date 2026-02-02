
rm gltf_ktx2_extension.zip
mkdir -p gltf_ktx2_extension
# Copy all Python files and other extension files into the folder
find . -maxdepth 1 -type f \( -name "*.py" -o -name "*.json" \) -exec cp {} gltf_ktx2_extension/ \;
# Zip the folder, excluding pycache
zip -r gltf_ktx2_extension.zip gltf_ktx2_extension -x "*/__pycache__/*"
rm -rf gltf_ktx2_extension