"""Persistent Chimney upload queue, shared across Gunicorn workers and logins.

State is stored below the existing persistent uploads root; no existing data is
modified or deleted. A separate worker process consumes completed uploads.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import shutil
import uuid

from werkzeug.utils import secure_filename
from chimney_asset_storage import ACCEPTED_EXTS, MAX_REQUEST_BYTES

CHUNK_MAX = 8 * 1024 * 1024
JOB_ID_RE = re.compile(r'^[a-f0-9]{32}$')
STATUS = {'uploading', 'queued', 'processing', 'completed', 'failed'}

class UploadJobError(ValueError):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def jobs_root(static_folder):
    # Keep jobs on the *same persistent upload mount* as the 3D data.
    return Path(static_folder) / 'uploads' / 'chimney_tiles' / '_upload_jobs'


def _job_dir(static_folder, project_id, job_id):
    if not JOB_ID_RE.fullmatch(job_id):
        raise UploadJobError('Invalid upload identifier.')
    return jobs_root(static_folder) / str(int(project_id)) / job_id


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path, data):
    tmp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def job_lock(folder):
    with (folder / '.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def public_job(job):
    return {field: job.get(field) for field in (
        'id', 'project_id', 'filename', 'size', 'received', 'state', 'stage',
        'created_at', 'updated_at', 'error', 'model_activated')}


def new_job(static_folder, project_id, filename, size, user_id=None):
    if not isinstance(filename, str):
        raise UploadJobError('A filename is required.')
    name = secure_filename(Path(filename).name)
    if not name or Path(name).suffix.lower() not in ACCEPTED_EXTS:
        raise UploadJobError('Unsupported file. Select a 3TZ, ZIP, tileset JSON or orthophoto.')
    try:
        size = int(size)
    except (ValueError, TypeError):
        raise UploadJobError('A valid file size is required.')
    if size < 1 or size > MAX_REQUEST_BYTES:
        raise UploadJobError('File is empty or exceeds the configured limit.', 413)
    root = jobs_root(static_folder)
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < size + 1024 ** 3:
        raise UploadJobError('Not enough disk space to safely receive this upload.', 507)
    job_id = uuid.uuid4().hex
    folder = _job_dir(static_folder, project_id, job_id)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'upload.part').touch(exist_ok=False)
    job = dict(id=job_id, project_id=int(project_id), filename=name, size=size,
               received=0, state='uploading', stage='Receiving file',
               created_at=_utc(), updated_at=_utc(), error='',
               model_activated=False, created_by=user_id)
    _write_json(folder / 'job.json', job)
    return public_job(job)


def get_job(static_folder, project_id, job_id):
    folder = _job_dir(static_folder, project_id, job_id)
    try:
        job = _read_json(folder / 'job.json')
    except (FileNotFoundError, ValueError):
        raise UploadJobError('Upload job not found.', 404)
    if job.get('project_id') != int(project_id) or job.get('id') != job_id:
        raise UploadJobError('Upload job not found.', 404)
    return job


def append_chunk(static_folder, project_id, job_id, offset, body):
    folder = _job_dir(static_folder, project_id, job_id)
    if not folder.is_dir():
        raise UploadJobError('Upload job not found.', 404)
    if len(body) > CHUNK_MAX or len(body) < 1:
        raise UploadJobError('Upload chunk must be between 1 byte and 8 MiB.', 413)
    try:
        offset = int(offset)
    except (ValueError, TypeError):
        raise UploadJobError('Invalid upload chunk offset.')
    with job_lock(folder):
        job = get_job(static_folder, project_id, job_id)
        if job['state'] != 'uploading':
            # A retry after a completed request must not corrupt stored data.
            if job['received'] >= offset + len(body):
                return public_job(job)
            raise UploadJobError('The upload is no longer accepting chunks.', 409)
        received = job['received']
        if offset < 0 or offset > received:
            raise UploadJobError(f'Upload offset mismatch. Resume from {received}.', 409)
        if offset < received:
            if offset + len(body) > received:
                raise UploadJobError(f'Chunk overlaps the current offset. Resume from {received}.', 409)
            # Idempotent retry, only if bytes match what was already written.
            with (folder / 'upload.part').open('rb') as incoming:
                incoming.seek(offset)
                if incoming.read(len(body)) != body:
                    raise UploadJobError('Chunk does not match existing upload.', 409)
            return public_job(job)
        if received + len(body) > job['size']:
            raise UploadJobError('Chunk exceeds declared file size.', 413)
        with (folder / 'upload.part').open('r+b') as out:
            # After a crash, discard only uncommitted tail bytes in this
            # *new* staging file; never touch a pre-existing project asset.
            out.truncate(received)
            out.seek(received)
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        job['received'] += len(body)
        job['updated_at'] = _utc()
        if job['received'] == job['size']:
            job['state'] = 'queued'
            job['stage'] = 'Queued for background processing'
        _write_json(folder / 'job.json', job)
        return public_job(job)


def list_jobs(static_folder, project_id, count=25):
    root = jobs_root(static_folder) / str(int(project_id))
    items = []
    if not root.is_dir():
        return []
    for file in root.glob('*/job.json'):
        try:
            job = _read_json(file)
            if job['project_id'] == int(project_id):
                items.append(public_job(job))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(items, key=lambda x: x.get('created_at') or '', reverse=True)[:count]


def summary(static_folder, project_id):
    jobs = list_jobs(static_folder, project_id, 20)
    active = next((job for job in jobs if job['state'] in ('processing', 'queued', 'uploading')), None)
    return {'active': active, 'last': jobs[0] if jobs else None}


def claim_queued(static_folder):
    root = jobs_root(static_folder)
    if not root.is_dir():
        return None
    for path in sorted(root.glob('*/*/job.json')):
        folder = path.parent
        with job_lock(folder):
            try:
                job = _read_json(path)
            except (OSError, ValueError):
                continue
            if job.get('state') not in ('queued', 'processing'):
                continue
            # Safe recovery: sole worker holds the global lock; after a
            # process restart an interrupted 'processing' job is retried.
            if not (folder / 'upload.part').is_file() or (folder / 'upload.part').stat().st_size != job.get('size'):
                job.update(state='failed', error='File upload is incomplete.', stage='Failed', updated_at=_utc())
                _write_json(path, job)
                continue
            job.update(state='processing', stage='Validating and extracting files on server', updated_at=_utc())
            _write_json(path, job)
            return job
    return None


def finish_job(static_folder, job, error=None, model_activated=False):
    folder = _job_dir(static_folder, job['project_id'], job['id'])
    with job_lock(folder):
        current = get_job(static_folder, job['project_id'], job['id'])
        current['state'] = 'failed' if error else 'completed'
        current['stage'] = 'Failed' if error else 'Completed'
        current['updated_at'] = _utc()
        current['error'] = (str(error)[:400] if error else '')
        current['model_activated'] = model_activated
        _write_json(folder / 'job.json', current)
        if not error:
            # The bundle now contains the original, and completed retries use job.json.
            try:
                (folder / 'upload.part').unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning('Could not release staging file for job %s', job['id'])
        return public_job(current)
