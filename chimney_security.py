"""Authorization classification and immutable inspection-photo storage helpers."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

PROJECT_FOLDERS = frozenset({
    'chimney_tiles', 'chimney_defect_images', 'chimney_rectified_images', 'kml',
})
LINKED_FOLDERS = {
    'chimney_covers': 'cover_snapshot_path',
    'chimney_client_logos': 'client_logo_path',
}
MAX_INSPECTION_PHOTO_BYTES = 32 * 1024 * 1024
ALLOWED_PHOTO_FORMATS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}


class PhotoUploadError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def asset_scope(path: str):
    """Classify /uploads and /static/uploads routes; None means non-Chimney.

    Returns ('project', project_id), ('linked', project_field, relative_path),
    or ('deny',). The Flask middleware enforces login and project permission.
    """
    if not isinstance(path, str):
        return None
    prefix = next((p for p in ('/static/uploads/', '/uploads/') if path.startswith(p)), None)
    if not prefix:
        return None
    subpath = path[len(prefix):]
    parts = subpath.split('/')
    if not parts or parts[0] not in PROJECT_FOLDERS | LINKED_FOLDERS.keys() | {'report_crops'}:
        return None
    if (len(parts) < 2 or any(part in ('', '.', '..') for part in parts)
            or '\\' in subpath or '\x00' in subpath):
        return ('deny',)
    folder = parts[0]
    if folder == 'report_crops':
        return ('deny',)
    if folder in PROJECT_FOLDERS:
        if len(parts) < 3 or not parts[1].isascii() or not parts[1].isdecimal() or int(parts[1]) < 1:
            return ('deny',)
        return ('project', int(parts[1]))
    if len(parts) != 2:
        return ('deny',)
    return ('linked', LINKED_FOLDERS[folder], 'uploads/' + subpath)


def store_verified_photo(upload, dest_dir, name_prefix):
    """Validate image and publish a NEW path atomically; old files stay intact."""
    if not upload or not getattr(upload, 'filename', '') or not getattr(upload, 'stream', None):
        raise PhotoUploadError('Choose a JPEG, PNG or WebP image.')
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    identifier = uuid4().hex
    prefix = str(name_prefix)
    if not prefix or not all(c.isascii() and (c.isalnum() or c in '-_') for c in prefix):
        raise ValueError('Invalid new photo prefix.')
    temporary = dest / ('.' + prefix + '_' + identifier + '.part')
    try:
        count = 0
        with temporary.open('xb') as output:
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_INSPECTION_PHOTO_BYTES:
                    raise PhotoUploadError('Photo exceeds the 32 MiB limit.', 413)
                output.write(chunk)
            output.flush()
            import os
            os.fsync(output.fileno())
        if count == 0:
            raise PhotoUploadError('The selected photo is empty.')
        try:
            with Image.open(temporary) as picture:
                extension = ALLOWED_PHOTO_FORMATS.get(picture.format)
                if not extension:
                    raise PhotoUploadError('Only valid JPEG, PNG and WebP photos are supported.')
                picture.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, PhotoUploadError):
                raise
            raise PhotoUploadError('The photo is damaged or is not a valid image.') from exc
        published = dest / (prefix + '_' + identifier + extension)
        import os
        os.replace(temporary, published)
        return published
    finally:
        temporary.unlink(missing_ok=True)


def has_chimney_module(role, modules):
    """Admin always has access; other users require the inspection module."""
    return role == 'Admin' or '3D Inspection' in (modules or [])
