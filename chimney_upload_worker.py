"""Independent background worker for safely received Chimney upload jobs.

Started alongside Gunicorn; it consumes shared on-disk jobs after the browser
has left. On restart, unfinished processing is retried without touching old data.
"""
from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
import time

from chimney_asset_storage import store_uploads, AssetUploadError
from chimney_upload_jobs import jobs_root, claim_queued, finish_job

LOG = logging.getLogger('chimney-upload-worker')


class StoredFile:
    def __init__(self, name, stream):
        self.filename = name
        self.stream = stream


def process_job(app, job):
    from models import db, ChimneyProject
    folder = jobs_root(app.static_folder) / str(job['project_id']) / job['id']
    candidate = folder / 'upload.part'
    activated = False
    try:
        with candidate.open('rb') as stream:
            result = store_uploads(app.static_folder, job['project_id'],
                                   [StoredFile(job['filename'], stream)],
                                   require_model=job['filename'].lower().endswith('.3tz'))
        if result.get('model_path'):
            with app.app_context():
                project = db.session.get(ChimneyProject, job['project_id'])
                if project is None:
                    raise AssetUploadError('The project no longer exists. Upload was preserved but not activated.')
                # NEVER replace the model already in use. Concurrent workers
                # are prevented by the global OS file lock below.
                if not project.tileset_path:
                    project.tileset_path = result['model_path']
                    db.session.commit()
                    activated = True
        finish_job(app.static_folder, job, model_activated=activated)
        LOG.info('Completed upload job %s for project %s', job['id'], job['project_id'])
    except (AssetUploadError, OSError) as exc:
        LOG.exception('Upload job %s failed safely', job['id'])
        finish_job(app.static_folder, job, error=str(exc))
    except Exception:
        LOG.exception('Unexpected error in upload job %s', job['id'])
        with app.app_context():
            db.session.rollback()
        finish_job(app.static_folder, job, error='Processing failed on server. Existing files have not been deleted; see server logs.')


def run_forever():
    from app import app
    root = jobs_root(app.static_folder)
    root.mkdir(parents=True, exist_ok=True)
    LOG.info('Background Chimney upload worker online; storage %s', root)
    with (root / '.worker.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info('Another worker owns this queue; exiting.')
            return
        while True:
            job = claim_queued(app.static_folder)
            if job is None:
                time.sleep(3)
                continue
            process_job(app, job)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    run_forever()
