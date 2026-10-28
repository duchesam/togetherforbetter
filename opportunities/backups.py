"""Offline SQLite/private-file snapshots; restoration never overwrites a directory."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone


MAX_BACKUP_BYTES = 2 * 1024 ** 3


class BackupError(Exception):
    pass


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def check_sqlite(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
        if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('SQLite integrity check failed')


def create_backup(database, uploads, output):
    database, uploads, output = Path(database).absolute(), Path(uploads).absolute(), Path(output).absolute()
    if not database.is_file() or database.is_symlink() or uploads.is_symlink() or (uploads.exists() and not uploads.is_dir()):
        raise BackupError('A regular SQLite database and non-symlink upload directory are required')
    if output == database or uploads.resolve() in output.resolve().parents:
        raise BackupError('Backup output must be outside private uploads and the live database')
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='pilot-snapshot-') as temporary:
            snapshot = Path(temporary) / 'database.sqlite3'
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(snapshot) as target:
                source.backup(target)
            check_sqlite(snapshot)
            files = {'database.sqlite3': snapshot}
            if uploads.exists():
                for item in uploads.rglob('*'):
                    if item.is_symlink():
                        raise BackupError('Symlinks are not permitted in private uploads')
                    if item.is_file():
                        files['uploads/' + item.relative_to(uploads).as_posix()] = item
            if len(files) > 99999 or sum(path.stat().st_size for path in files.values()) > MAX_BACKUP_BYTES:
                raise BackupError('Pilot backup exceeds supported file count or two GiB size limit')
            manifest = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': {name: {'size': path.stat().st_size, 'sha256': digest(path)} for name, path in files.items()}}
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, 'wb') as destination, tarfile.open(fileobj=destination, mode='w:gz') as archive:
                for name, path in files.items():
                    archive.add(path, arcname=name, recursive=False)
                content = json.dumps(manifest).encode()
                header = tarfile.TarInfo('manifest.json')
                header.size, header.mode = len(content), 0o600
                archive.addfile(header, io.BytesIO(content))
        return len(files) - 1
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def restore_backup(archive_path, destination):
    destination = Path(destination).absolute()
    # Exclusive creation ensures restoration cannot replace live data.
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive_path, 'r:gz') as archive:
            index, total = {}, 0
            for member in archive:
                if len(index) >= 100000 or member.name in index:
                    raise BackupError('Invalid archive member count or duplicate paths')
                total += member.size
                if member.size < 0 or total > MAX_BACKUP_BYTES + 16 * 1024 * 1024:
                    raise BackupError('Archive exceeds the pilot restore size limit')
                path = PurePosixPath(member.name)
                if not member.isfile() or path.is_absolute() or '..' in path.parts or str(path) != member.name or "\\" in member.name:
                    raise BackupError('Archive contains an unsafe path or non-regular member')
                if member.name not in ['manifest.json', 'database.sqlite3'] and not member.name.startswith('uploads/'):
                    raise BackupError('Archive contains an unexpected member')
                index[member.name] = member
            metadata = index.get('manifest.json')
            if not metadata or metadata.size > 16 * 1024 * 1024:
                raise BackupError('Missing or oversized backup manifest')
            manifest = json.load(archive.extractfile(metadata))
            files = manifest.get('files')
            if manifest.get('format') != 1 or not isinstance(files, dict) or set(files) != set(index) - {'manifest.json'} or 'database.sqlite3' not in files:
                raise BackupError('Archive and manifest do not match')
            for name, expected in files.items():
                member = index[name]
                if member.size != expected['size']:
                    raise BackupError('Backup file size mismatch')
                relative = 'db.sqlite3' if name == 'database.sqlite3' else '.private_uploads/' + name[len('uploads/'):]
                path = destination / relative
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                value = hashlib.sha256()
                with archive.extractfile(member) as source, path.open('xb') as target:
                    os.chmod(path, 0o600)
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        value.update(chunk)
                        target.write(chunk)
                if value.hexdigest() != expected['sha256']:
                    raise BackupError('Backup checksum mismatch')
            (destination / '.private_uploads').mkdir(mode=0o700, exist_ok=True)
        check_sqlite(destination / 'db.sqlite3')
        return len(files) - 1
    except Exception:
        shutil.rmtree(destination)
        raise
