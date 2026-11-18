"""Persistent queue tests (run with python -m unittest discover -s tests)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chimney_upload_jobs import (UploadJobError, new_job, get_job, append_chunk,
                                 list_jobs, claim_queued, finish_job, summary)


class PersistentQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.static = Path(self.tmp.name) / 'static'
        # Tests are tiny; production has a 1 GiB free disk reserve.
        self.p = patch('chimney_upload_jobs.shutil.disk_usage')
        self.disk = self.p.start()
        self.disk.return_value.free = 32 * 1024 ** 3

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_overlapping_retry_is_rejected(self):
        job = new_job(self.static, 1, 'scan.3tz', 10)
        append_chunk(self.static, 1, job['id'], 0, b'hello')
        with self.assertRaises(UploadJobError):
            append_chunk(self.static, 1, job['id'], 3, b'lo123')
        self.assertEqual(get_job(self.static, 1, job['id'])['received'], 5)

    def test_processing_continues_without_uploader_and_shared_between_logins(self):
        job = new_job(self.static, 1, 'scan.3tz', 9, user_id=1)
        self.assertEqual(summary(self.static, 1)['active']['state'], 'uploading')
        part = append_chunk(self.static, 1, job['id'], 0, b'hello')
        self.assertEqual(part['received'], 5)
        # Imagine closing browser. Different login sees already received bytes.
        self.assertEqual(list_jobs(self.static, 1)[0]['received'], 5)
        resumed = append_chunk(self.static, 1, job['id'], 5, b'1234')
        self.assertEqual(resumed['state'], 'queued')
        claimed = claim_queued(self.static)
        self.assertEqual(claimed['state'], 'processing')
        self.assertEqual(summary(self.static, 1)['active']['state'], 'processing')
        done = finish_job(self.static, claimed)
        self.assertEqual(done['state'], 'completed')
        self.assertIsNone(summary(self.static, 1)['active'])

    def test_previously_uploaded_data_is_never_modified(self):
        original = self.static / 'uploads/chimney_tiles/1/tileset.json'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'KEEP THIS OLD MODEL')
        job = new_job(self.static, 1, 'ortho.tif', 4)
        append_chunk(self.static, 1, job['id'], 0, b'foto')
        finish_job(self.static, get_job(self.static, 1, job['id']), error='invalid format')
        self.assertEqual(original.read_bytes(), b'KEEP THIS OLD MODEL')
        self.assertEqual(list_jobs(self.static, 1)[0]['state'], 'failed')

    def test_duplicate_chunk_is_idempotent_and_mismatch_is_rejected(self):
        job = new_job(self.static, 1, 'scan.zip', 10)
        append_chunk(self.static, 1, job['id'], 0, b'hello')
        self.assertEqual(append_chunk(self.static, 1, job['id'], 0, b'hello')['received'], 5)
        with self.assertRaises(UploadJobError):
            append_chunk(self.static, 1, job['id'], 0, b'wrong')
        with self.assertRaises(UploadJobError):
            append_chunk(self.static, 1, job['id'], 6, b'a')
        self.assertEqual(get_job(self.static, 1, job['id'])['received'], 5)

    def test_job_identifier_and_project_ownership_restricted(self):
        job = new_job(self.static, 1, 'tileset.json', 2)
        with self.assertRaises(UploadJobError):
            get_job(self.static, 2, job['id'])
        with self.assertRaises(UploadJobError):
            get_job(self.static, 1, '../../etc/passwd')

    def test_interrupted_worker_job_can_be_reclaimed_after_restart(self):
        job = new_job(self.static, 9, 'photo.jpg', 3)
        append_chunk(self.static, 9, job['id'], 0, b'abc')
        first = claim_queued(self.static)
        second = claim_queued(self.static)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['state'], 'processing')

    def test_reject_unsupported_upload_and_oversized_chunk(self):
        with self.assertRaises(UploadJobError):
            new_job(self.static, 1, 'hacker.exe', 3)
        job = new_job(self.static, 1, 'file.3tz', 4)
        with self.assertRaises(UploadJobError):
            append_chunk(self.static, 1, job['id'], 0, b'abcde')
        self.assertEqual(get_job(self.static, 1, job['id'])['received'], 0)


if __name__ == '__main__':
    unittest.main()
