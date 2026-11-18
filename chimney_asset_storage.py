"""Non-destructive storage for Chimney 3D and orthophoto uploads.

Existing `static/uploads/chimney_tiles/<project_id>` files are NEVER modified.
All new uploads are staged, validated, then committed as immutable bundles.
This module deliberately has no Flask or database dependencies.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from werkzeug.utils import secure_filename

MAX_REQUEST_BYTES = int(os.environ.get('CHIMNEY_MAX_UPLOAD_BYTES', str(8 * 1024 ** 3)))
MAX_EXPANDED_BYTES = int(os.environ.get('CHIMNEY_MAX_EXPANDED_BYTES', str(16 * 1024 ** 3)))
MAX_ARCHIVE_FILES = int(os.environ.get('CHIMNEY_MAX_ARCHIVE_FILES', '100000'))
MIN_FREE_SPACE = int(os.environ.get('CHIMNEY_MIN_FREE_DISK_BYTES', str(1024 ** 3)))
ORTHO_EXTS = {'.tif', '.tiff', '.geotiff', '.jp2', '.jpg', '.jpeg', '.png', '.webp', '.mbtiles'}
ACCEPTED_EXTS = ORTHO_EXTS | {'.zip', '.3tz', '.json'}
MODEL_CONTENT_EXTS = {'.b3dm', '.i3dm', '.pnts', '.cmpt', '.glb', '.gltf', '.bin', '.subtree'}
# The archive is published under /static; do not unpack active web content.
BLOCKED_ARCHIVE_EXTS = {'.html', '.htm', '.svg', '.js', '.mjs', '.php', '.py', '.sh', '.exe', '.dll', '.css', '.wasm'}
MANIFEST = '_chimney_asset_manifest.json'


class AssetUploadError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _kind(filename: str) -> str | None:
    lower = Path(filename).name.lower()
    suffix = Path(lower).suffix
    if suffix == '.3tz':
        return '3tz'
    if suffix in ORTHO_EXTS:
        return 'ortho'
    if lower == 'tileset.json':
        return 'tileset_json'
    if suffix == '.zip':
        return 'zip'
    if suffix == '.json':
        return 'json'
    return None


def _validate_tileset(path: Path) -> None:
    try:
        with path.open('r', encoding='utf-8') as f:
            value = json.load(f)
    except (OSError, UnicodeError, ValueError) as exc:
        raise AssetUploadError(f'Invalid tileset.json ({path.name}). Check that it is a UTF-8 JSON file.') from exc
    if not isinstance(value, dict) or not isinstance(value.get('asset'), dict) or not isinstance(value.get('root'), dict):
        raise AssetUploadError('tileset.json must contain valid "asset" and "root" objects.')


def _safe_members(archive: zipfile.ZipFile):
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise AssetUploadError(f'Archive contains too many files (limit {MAX_ARCHIVE_FILES:,}).', 413)
    estimated = 0
    seen = set()
    clean = []
    for entry in members:
        raw = entry.filename
        if not raw or '\\' in raw or '\x00' in raw:
            raise AssetUploadError('Archive contains an unsafe filename.')
        name = PurePosixPath(raw)
        if name.is_absolute() or not name.parts or '..' in name.parts or '.' in name.parts:
            raise AssetUploadError('Archive contains a path outside its folder.')
        if any(len(piece) > 255 for piece in name.parts) or len(name.parts) > 24:
            raise AssetUploadError('Archive contains an invalid or overly deep path.')
        type_bits = (entry.external_attr >> 16) & 0o170000
        if type_bits not in (0, stat.S_IFDIR, stat.S_IFREG):
            raise AssetUploadError('Archive contains a link or unsupported file type.')
        if entry.is_dir():
            continue
        if Path(raw).suffix.lower() in BLOCKED_ARCHIVE_EXTS:
            # 3D Tiles export ZIPs sometimes contain optional index.html, JS,
            # CSS or SVG preview files. Do not publish executable web assets
            # under Flask's public /static/uploads; omit those entries while
            # retaining the tileset and binary geometry.
            continue
        lowered = raw.lower()
        if lowered in seen:
            raise AssetUploadError(f'Archive has a duplicate file path: {raw}')
        seen.add(lowered)
        estimated += entry.file_size
        if estimated > MAX_EXPANDED_BYTES:
            raise AssetUploadError('Archive expands beyond the configured safety limit.', 413)
        clean.append((entry, name))
    return clean, estimated


def _extract_archive(archive_path: Path, destination: Path, disk_root: Path, total_state: list[int]) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members, expanded = _safe_members(archive)
            if total_state[0] + expanded > MAX_EXPANDED_BYTES:
                raise AssetUploadError('Combined archives expand beyond the safety limit.', 413)
            if shutil.disk_usage(disk_root).free < expanded + MIN_FREE_SPACE:
                raise AssetUploadError('Not enough VPS disk space to extract this archive safely. No existing files were changed.', 507)
            destination.mkdir(parents=True, exist_ok=False)
            for entry, rel in members:
                output = destination.joinpath(*rel.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, output.open('xb') as target:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        total_state[0] += len(block)
                        if total_state[0] > MAX_EXPANDED_BYTES:
                            raise AssetUploadError('Extracted data exceeded the configured safety limit.', 413)
                        target.write(block)
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as exc:
        if isinstance(exc, AssetUploadError):
            raise
        raise AssetUploadError('Archive is corrupted, encrypted, or could not be extracted safely.') from exc


def _find_tilesets(folder: Path) -> list[Path]:
    return sorted(
        [p for p in folder.rglob('*') if p.is_file() and p.name.lower() == 'tileset.json'],
        key=lambda p: (len(p.relative_to(folder).parts), str(p)),
    )


def _has_model_content(tileset: Path) -> bool:
    # A lone JSON file is metadata, not a usable model. Never replace a working
    # viewer's tileset with an incomplete upload.
    for item in tileset.parent.rglob('*'):
        if item.is_file() and item.suffix.lower() in MODEL_CONTENT_EXTS:
            return True
    return False


def _copy_upload(source, dest: Path, used_bytes: list[int]) -> int:
    size = 0
    with dest.open('xb') as out:
        while True:
            block = source.stream.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            used_bytes[0] += len(block)
            if used_bytes[0] > MAX_REQUEST_BYTES:
                raise AssetUploadError('Upload exceeds the configured size limit.', 413)
            out.write(block)
    return size


def store_uploads(static_root: str | Path, project_id: int, uploads: list, require_model: bool = False) -> dict:
    """Save new files in a brand-new directory. Never delete or overwrite an old model.

    Returns the inventory metadata and a candidate model path relative to static/.
    Callers decide whether an existing model should remain active (it should).
    """
    files = [file for file in uploads if file and getattr(file, 'filename', '')]
    if not files:
        raise AssetUploadError('Select at least one file to upload.')
    static_root = Path(static_root)
    root = static_root / 'uploads' / 'chimney_tiles' / str(project_id)
    bundles_root = root / 'asset_uploads'
    bundles_root.mkdir(parents=True, exist_ok=True)
    source_names = set()
    for file in files:
        name = secure_filename(Path(file.filename).name)
        if not name or Path(name).suffix.lower() not in ACCEPTED_EXTS:
            raise AssetUploadError(f'Unsupported upload type: {file.filename}. Allowed: 3TZ, ZIP, JSON and orthophoto images.')
        if name.lower() in source_names:
            raise AssetUploadError(f'Duplicate filename in one upload: {name}')
        source_names.add(name.lower())
    if shutil.disk_usage(bundles_root).free < MIN_FREE_SPACE:
        raise AssetUploadError('The VPS is low on free disk space. No existing files were changed.', 507)

    with tempfile.TemporaryDirectory(prefix='.incoming-', dir=bundles_root) as temp:
        staging = Path(temp)
        originals = staging / 'originals'
        payloads = staging / 'extracted'
        originals.mkdir()
        payloads.mkdir()
        saved = []
        copied = [0]
        expanded = [0]
        model_candidates = []
        discovered = []
        for index, file in enumerate(files):
            name = secure_filename(Path(file.filename).name)
            original = originals / name
            byte_count = _copy_upload(file, original, copied)
            ext = original.suffix.lower()
            if ext in {'.zip', '.3tz'}:
                if not zipfile.is_zipfile(original):
                    raise AssetUploadError(f'{name} is not a valid ZIP/3TZ archive. Existing data is safe.')
                content = payloads / str(index)
                _extract_archive(original, content, bundles_root, expanded)
                # ZIP bundles can contain a nested 3TZ model. Extract once,
                # keeping the original 3TZ bytes unchanged in the bundle.
                nested_archives = [p for p in content.rglob('*') if p.is_file() and p.suffix.lower() == '.3tz']
                for nested_index, nested in enumerate(nested_archives):
                    nested_folder = payloads / f'{index}_3tz_{nested_index}'
                    _extract_archive(nested, nested_folder, bundles_root, expanded)
                for candidate_root in [content] + [p for p in payloads.iterdir() if p.name.startswith(f'{index}_3tz_')]:
                    for candidate in _find_tilesets(candidate_root):
                        _validate_tileset(candidate)
                        if _has_model_content(candidate):
                            model_candidates.append(candidate)
                for item in content.rglob('*'):
                    if not item.is_file():
                        continue
                    kind = _kind(item.name)
                    if kind not in ('3tz', 'ortho', 'tileset_json'):
                        continue
                    if ext == '.3tz' and kind == 'tileset_json':
                        continue  # Embedded tileset metadata is not an independently uploaded JSON.
                    if kind == 'ortho' and item.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
                        # JPEG/PNG textures inside a 3TZ must not be shown as
                        # uploaded orthophotos. In a ZIP, accept common explicit
                        # orthophoto names only; direct image uploads are handled
                        # independently above.
                        label = str(item.relative_to(content)).lower()
                        if ext == '.3tz' or not any(word in label for word in ('ortho', 'orthomosaic', 'orthophoto')):
                            continue
                    discovered.append({'name': item.name, 'kind': kind})
                # Nested 3TZ texture images belong to the model, not to the
                # user's independently uploaded orthophoto checklist.
            elif ext == '.json':
                if byte_count > 16 * 1024 * 1024:
                    raise AssetUploadError('Individual JSON metadata exceeds the 16 MiB safety limit.', 413)
                try:
                    with original.open('r', encoding='utf-8') as f:
                        json.load(f)
                except (ValueError, UnicodeError) as exc:
                    raise AssetUploadError(f'{name} is not valid JSON.') from exc
                if name.lower() == 'tileset.json':
                    _validate_tileset(original)
            saved.append({'name': name, 'kind': _kind(name), 'size': byte_count})
        if require_model and not model_candidates:
            raise AssetUploadError('Archive has no usable 3D tileset. It needs tileset.json and tile/model content. Existing model untouched.')
        if model_candidates:
            chosen = sorted(model_candidates, key=lambda p: (len(p.relative_to(staging).parts), str(p)))[0]
            relative_model = str(chosen.relative_to(staging)).replace(os.sep, '/')
        else:
            relative_model = ''
        manifest = {
            'uploaded_at': datetime.now(timezone.utc).isoformat(),
            'source_files': saved,
            'discovered_files': discovered,
            'model': relative_model,
        }
        (staging / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        bundle_id = uuid.uuid4().hex
        completed = bundles_root / bundle_id
        if relative_model and len('uploads/chimney_tiles/' + str(project_id) + '/asset_uploads/' + bundle_id + '/' + relative_model) > 255:
            raise AssetUploadError('Tileset is nested too deeply for the project database. Existing model is untouched.')
        # Rename within the same filesystem is atomic. No prior bundle is replaced.
        staging.rename(completed)
        model_path = ('uploads/chimney_tiles/' + str(project_id) + '/asset_uploads/' + bundle_id + '/' + relative_model) if relative_model else ''
        return {'manifest': manifest, 'model_path': model_path, 'bundle_id': bundle_id}


def inventory(static_root: str | Path, project_id: int, tileset_path: str = '') -> dict:
    root = Path(static_root) / 'uploads' / 'chimney_tiles' / str(project_id)
    folder = root / 'asset_uploads'
    entries = []
    manifest_model_paths = set()
    for manifest_file in sorted(folder.glob('*/' + MANIFEST)) if folder.is_dir() else []:
        try:
            data = json.loads(manifest_file.read_text(encoding='utf-8'))
            created = data.get('uploaded_at') or ''
            if data.get('model'):
                manifest_model_paths.add((manifest_file.parent / data['model']).resolve())
            for item in data.get('source_files', []) + data.get('discovered_files', []):
                if not isinstance(item, dict) or not item.get('name'):
                    continue
                entries.append({'name': item['name'], 'kind': item.get('kind'), 'uploaded_at': created,
                                'size': item.get('size'), 'source': 'uploaded' if item in data.get('source_files', []) else 'inside_archive'})
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Bad manifest must not stop displaying other uploads.
    if tileset_path:
        active_path = Path(static_root) / tileset_path
        if active_path.resolve() not in manifest_model_paths:
            entries.append({'name': 'Existing 3D tileset (' + active_path.name + ')',
                            'kind': 'existing_model', 'uploaded_at': '', 'size': None, 'source': 'existing'})
    entries.sort(key=lambda item: (item.get('uploaded_at') or '', item.get('name') or ''), reverse=True)
    kinds = {'3tz': [], 'ortho': [], 'tileset_json': []}
    for item in entries:
        if item.get('kind') in kinds:
            kinds[item['kind']].append(item)
    return {'has_model': bool(tileset_path), 'files': entries, 'by_type': kinds}
