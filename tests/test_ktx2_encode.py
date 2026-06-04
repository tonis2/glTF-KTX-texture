"""Tests for the Blender-independent pieces of ktx2_encode.

Only ``KTX2ImageData`` is exercised here — ``encode_image_to_ktx2`` imports
``io_scene_gltf2`` and shells out to toktx, so it belongs in an in-Blender /
integration test rather than a unit test.
"""

import os
import sys
import unittest

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)

import ktx2_encode  # noqa: E402


class KTX2ImageDataTests(unittest.TestCase):
    def test_basic_properties(self):
        img = ktx2_encode.KTX2ImageData(b"abc", "image/ktx2", "wood")
        self.assertEqual(img.data, b"abc")
        self.assertEqual(img.name, "wood")
        self.assertEqual(img.file_extension, ".ktx2")
        self.assertEqual(img.byte_length, 3)

    def test_uri_roundtrip(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "n")
        self.assertIsNone(img.uri)
        img.uri = "textures/n.ktx2"
        self.assertEqual(img.uri, "textures/n.ktx2")

    def test_equality_and_hash_by_data(self):
        a = ktx2_encode.KTX2ImageData(b"same", "image/ktx2", "a")
        b = ktx2_encode.KTX2ImageData(b"same", "image/ktx2", "b-different-name")
        c = ktx2_encode.KTX2ImageData(b"other", "image/ktx2", "a")
        self.assertEqual(a, b)            # equal by data, name ignored
        self.assertNotEqual(a, c)
        self.assertEqual(hash(a), hash(b))

    def test_adjusted_name_replaces_dots(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "wood.001")
        self.assertEqual(img.adjusted_name(), "wood_001")

    def test_adjusted_name_strips_special_chars(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "tex/name?#")
        self.assertEqual(img.adjusted_name(), "texname")

    def test_set_adjusted_name_unique_first_use(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "tex")
        self.assertEqual(img.set_adjusted_name(set()), "tex.ktx2")

    def test_set_adjusted_name_dedupes_against_existing(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "tex")
        self.assertEqual(img.set_adjusted_name({"tex.ktx2"}), "tex-1.ktx2")

    def test_set_adjusted_name_increments_suffix(self):
        img = ktx2_encode.KTX2ImageData(b"x", "image/ktx2", "tex")
        result = img.set_adjusted_name({"tex.ktx2", "tex-1.ktx2"})
        self.assertEqual(result, "tex-2.ktx2")


if __name__ == "__main__":
    unittest.main()
