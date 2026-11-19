"""Run: python -m unittest discover -s tests -v (with project dependencies)."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

from chimney_security import asset_scope, store_verified_photo, PhotoUploadError, has_chimney_module


class ChimneyAssetAccessTests(unittest.TestCase):
    def test_non_admin_requires_inspection_module(self):
        self.assertTrue(has_chimney_module('Admin', []))
        self.assertTrue(has_chimney_module('Client User', ['3D Inspection']))
        self.assertFalse(has_chimney_module('Client User', []))
        self.assertFalse(has_chimney_module('Pilot', ['Land Survey']))

    def test_scoped_paths_in_both_url_forms(self):
        for prefix in ('/uploads/', '/static/uploads/'):
            for folder in ('chimney_tiles', 'chimney_defect_images', 'chimney_rectified_images', 'kml'):
                self.assertEqual(asset_scope(prefix + folder + '/42/file.png'), ('project', 42))
        self.assertEqual(asset_scope('/uploads/chimney_client_logos/logo.png'),
                         ('linked', 'client_logo_path', 'uploads/chimney_client_logos/logo.png'))
        self.assertEqual(asset_scope('/static/uploads/chimney_covers/cover_42.jpg'),
                         ('linked', 'cover_snapshot_path', 'uploads/chimney_covers/cover_42.jpg'))

    def test_internal_files_and_malformed_project_paths_denied(self):
        for path in ('/uploads/chimney_tiles/_upload_jobs/2/job.json',
                     '/static/uploads/report_crops/image.jpg',
                     '/uploads/chimney_tiles/abc/a', '/uploads/chimney_tiles/0/a',
                     '/uploads/chimney_tiles/42/../99/a',
                     '/uploads/chimney_defect_images/42/',
                     '/uploads/chimney_covers/subdir/a.jpg'):
            self.assertEqual(asset_scope(path), ('deny',))

    def test_other_modules_untouched(self):
        self.assertIsNone(asset_scope('/static/js/chimney.js'))
        self.assertIsNone(asset_scope('/uploads/announcements/a.png'))


class ImmutableChimneyPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name)
        self.old = self.dest / 'defect_17.jpg'
        self.old.write_bytes(b'existing-photo')

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, fmt='JPEG'):
        stream = io.BytesIO()
        Image.new('RGB', (8, 8), 'white').save(stream, format=fmt)
        return SimpleNamespace(filename='picture', stream=io.BytesIO(stream.getvalue()))

    def test_new_jpeg_keeps_previous_photo(self):
        new = store_verified_photo(self.upload(), self.dest, 'defect_17')
        self.assertTrue(new.exists())
        self.assertEqual(new.suffix, '.jpg')
        self.assertEqual(self.old.read_bytes(), b'existing-photo')
        self.assertNotEqual(new, self.old)

    def test_png_keeps_correct_extension(self):
        new = store_verified_photo(self.upload('PNG'), self.dest, 'rectified_17')
        self.assertEqual(new.suffix, '.png')
        self.assertEqual(self.old.read_bytes(), b'existing-photo')

    def test_bad_or_empty_image_is_rejected_without_deletion(self):
        for payload in (b'no image', b''):
            with self.assertRaises(PhotoUploadError):
                store_verified_photo(SimpleNamespace(filename='fake.jpg', stream=io.BytesIO(payload)),
                                     self.dest, 'defect_17')
            self.assertEqual(self.old.read_bytes(), b'existing-photo')
            self.assertEqual([p.name for p in self.dest.iterdir()], ['defect_17.jpg'])

    def test_size_limit_keeps_previous_photo(self):
        with patch('chimney_security.MAX_INSPECTION_PHOTO_BYTES', 5):
            with self.assertRaises(PhotoUploadError) as err:
                store_verified_photo(self.upload(), self.dest, 'defect_17')
        self.assertEqual(err.exception.status, 413)
        self.assertEqual(self.old.read_bytes(), b'existing-photo')


if __name__ == '__main__':
    unittest.main()
