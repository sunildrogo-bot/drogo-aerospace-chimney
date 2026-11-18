"""Run: python -m unittest discover -s tests -v (after installing project deps)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from chimney_asset_storage import AssetUploadError, inventory, store_uploads


class Upload:
    def __init__(self, filename, content):
        self.filename = filename
        self.stream = io.BytesIO(content)


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    return buffer.getvalue()


TILESET = json.dumps({'asset': {'version': '1.1'}, 'root': {'boundingVolume': {'sphere': [0, 0, 0, 1]}, 'geometricError': 0}}).encode()


class SafeChimneyUploads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static_root = Path(self.temp.name) / 'static'
        self.base = self.static_root / 'uploads' / 'chimney_tiles' / '42'
        self.base.mkdir(parents=True)
        self.original = self.base / 'tileset.json'
        self.original.write_bytes(b'ORIGINAL MODEL MUST SURVIVE')
        self.legacy_path = 'uploads/chimney_tiles/42/tileset.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_3tz_with_html_preview_and_textures_is_safe(self):
        source = archive({'tileset.json': TILESET, 'tiles/model.glb': b'geometry',
                          'index.html': b'<script>alert(1)</script>',
                          'textures/texture.jpg': b'jpeg-texture'})
        result = store_uploads(self.static_root, 42, [Upload('scene.3tz', source)], require_model=True)
        bundle = self.base / 'asset_uploads' / result['bundle_id']
        self.assertFalse((bundle / 'extracted/0/index.html').exists())
        self.assertTrue((bundle / 'extracted/0/tiles/model.glb').exists())
        listing = inventory(self.static_root, 42, self.legacy_path)
        self.assertEqual(len(listing['by_type']['3tz']), 1)
        self.assertEqual(len(listing['by_type']['ortho']), 0)
        self.assertEqual(len(listing['by_type']['tileset_json']), 0)

    def test_valid_3tz_activates_only_as_candidate_and_keeps_original(self):
        source = archive({'tileset.json': TILESET, 'tiles/0.b3dm': b'dummy'})
        result = store_uploads(self.static_root, 42, [Upload('model.3tz', source)], require_model=True)
        self.assertTrue(result['model_path'].endswith('/extracted/0/tileset.json'))
        self.assertTrue((self.static_root / result['model_path']).exists())
        self.assertEqual(self.original.read_bytes(), b'ORIGINAL MODEL MUST SURVIVE')
        self.assertTrue((self.base / 'asset_uploads' / result['bundle_id'] / 'originals' / 'model.3tz').exists())
        found = inventory(self.static_root, 42, self.legacy_path)
        self.assertEqual(len(found['by_type']['3tz']), 1)
        self.assertEqual(len(found['by_type']['tileset_json']), 0)  # embedded JSON is not a separate upload
        self.assertTrue(found['has_model'])

    def test_independent_orthophoto_and_json_have_separate_checks(self):
        ortho = store_uploads(self.static_root, 42, [Upload('ORTHO.tif', b'test image bytes')])
        self.assertFalse(ortho['model_path'])
        js = store_uploads(self.static_root, 42, [Upload('tileset.json', TILESET)])
        self.assertFalse(js['model_path'])  # Never make a JSON-only model active.
        types = inventory(self.static_root, 42, '')['by_type']
        self.assertEqual(len(types['ortho']), 1)
        self.assertEqual(len(types['tileset_json']), 1)
        self.assertEqual(len(types['3tz']), 0)

    def test_zip_of_multiple_assets(self):
        inner = archive({'tileset.json': TILESET, 'tile.b3dm': b'tile'})
        outer = archive({'scan.3tz': inner, 'ortho.tif': b'photo', 'tileset.json': TILESET})
        saved = store_uploads(self.static_root, 42, [Upload('survey.zip', outer)])
        self.assertTrue(saved['model_path'])
        grouped = inventory(self.static_root, 42)['by_type']
        self.assertEqual(len(grouped['3tz']), 1)
        self.assertEqual(len(grouped['ortho']), 1)
        self.assertEqual(len(grouped['tileset_json']), 1)

    def test_3tz_without_model_content_does_not_claim_success(self):
        source = archive({'tileset.json': TILESET})
        with self.assertRaises(AssetUploadError):
            store_uploads(self.static_root, 42, [Upload('incomplete.3tz', source)], require_model=True)
        self.assertEqual(self.original.read_bytes(), b'ORIGINAL MODEL MUST SURVIVE')
        self.assertEqual(inventory(self.static_root, 42, '')['files'], [])

    def test_corrupt_model_does_not_change_or_delete_original(self):
        with self.assertRaises(AssetUploadError):
            store_uploads(self.static_root, 42, [Upload('model.3tz', b'not a ZIP')], require_model=True)
        self.assertEqual(self.original.read_bytes(), b'ORIGINAL MODEL MUST SURVIVE')
        self.assertEqual(inventory(self.static_root, 42, '')['files'], [])

    def test_zip_slip_rejected_before_touching_existing(self):
        malicious = archive({'../../outside.txt': b'bad', 'tileset.json': TILESET, 'tile.b3dm': b'1'})
        with self.assertRaises(AssetUploadError):
            store_uploads(self.static_root, 42, [Upload('bad.zip', malicious)])
        self.assertFalse((self.static_root / 'outside.txt').exists())
        self.assertEqual(self.original.read_bytes(), b'ORIGINAL MODEL MUST SURVIVE')

    def test_no_complete_model_does_not_replace(self):
        bad = archive({'tileset.json': TILESET})
        with self.assertRaises(AssetUploadError):
            store_uploads(self.static_root, 42, [Upload('metadata_only.zip', bad)], require_model=True)
        self.assertEqual(self.original.read_bytes(), b'ORIGINAL MODEL MUST SURVIVE')

    def test_invalid_json_cannot_be_committed(self):
        with self.assertRaises(AssetUploadError):
            store_uploads(self.static_root, 42, [Upload('tileset.json', b'{bad')])
        self.assertEqual(inventory(self.static_root, 42, '')['files'], [])


if __name__ == '__main__':
    unittest.main()
