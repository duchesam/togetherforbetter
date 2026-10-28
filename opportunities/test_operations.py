import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from config.production import production_config
from .backups import BackupError, create_backup, restore_backup


class ProductionConfigTests(SimpleTestCase):
    def config(self, **values):
        return production_config({'DJANGO_DATA_DIR':'/tmp/private-test',**values},Path('/tmp/app'), 'https://pilot.example.org', 'a-strong-test-only-key-with-varied-characters-0123456789ABCDEF')

    def test_explicit_private_directory_and_derived_host(self):
        data,static,hosts=self.config()
        self.assertEqual(data,Path('/tmp/private-test'))
        self.assertEqual(static,Path('/tmp/app/staticfiles'))
        self.assertEqual(hosts,['pilot.example.org'])

    def test_missing_relative_and_overlapping_data_directories_rejected(self):
        for values in [{'DJANGO_DATA_DIR':''},{'DJANGO_DATA_DIR':'relative'},{'DJANGO_DATA_DIR':'/tmp/app/staticfiles'},{'DJANGO_DATA_DIR':'/tmp/app/staticfiles/private'},{'DJANGO_DATA_DIR':'/tmp/app'}]:
            with self.assertRaises(RuntimeError):self.config(**values)

    def test_wildcards_ports_and_wrong_hosts_rejected(self):
        for hosts in ['*','.example.org','https://pilot.example.org','pilot.example.org:443','wrong.example.org','pilot.example.org,']:
            with self.assertRaises(RuntimeError):self.config(DJANGO_ALLOWED_HOSTS=hosts)

    def test_weak_secret_rejected(self):
        with self.assertRaises(RuntimeError):production_config({'DJANGO_DATA_DIR':'/tmp/private'},Path('/tmp/app'),'https://pilot.example.org','short')


class BackupRecoveryTests(SimpleTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='pilot-recovery-test-')
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.database=self.root/'live.sqlite3'
        with sqlite3.connect(self.database) as database:
            database.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)')
            database.execute('INSERT INTO sample(value) VALUES (?)',('Synthetic recovery record',))
        self.uploads=self.root/'uploads'
        self.uploads.mkdir()
        (self.uploads/'cvs').mkdir()
        (self.uploads/'cvs'/'example.pdf').write_bytes(b'%PDF-synthetic-fixture')
        self.archive=self.root/'private-backups'/'snapshot.tar.gz'

    def backup(self):
        return create_backup(self.database,self.uploads,self.archive)

    def test_database_and_private_file_round_trip_with_private_permissions(self):
        self.assertEqual(self.backup(),1)
        destination=self.root/'restored'
        self.assertEqual(restore_backup(self.archive,destination),1)
        with sqlite3.connect(destination/'db.sqlite3') as database:
            self.assertEqual(database.execute('SELECT value FROM sample').fetchone()[0],'Synthetic recovery record')
        self.assertEqual((destination/'.private_uploads/cvs/example.pdf').read_bytes(),b'%PDF-synthetic-fixture')
        self.assertEqual(self.archive.stat().st_mode & 0o777,0o600)
        self.assertEqual(destination.stat().st_mode & 0o777,0o700)
        self.assertEqual((destination/'db.sqlite3').stat().st_mode & 0o777,0o600)

    def test_snapshot_does_not_change_when_live_database_changes(self):
        self.backup()
        with sqlite3.connect(self.database) as database:database.execute('DELETE FROM sample')
        destination=self.root/'snapshot'
        restore_backup(self.archive,destination)
        with sqlite3.connect(destination/'db.sqlite3') as database:self.assertEqual(database.execute('SELECT COUNT(*) FROM sample').fetchone()[0],1)

    def test_backup_and_restore_never_overwrite_existing_files(self):
        self.backup();original=self.archive.read_bytes()
        with self.assertRaises(FileExistsError):self.backup()
        self.assertEqual(self.archive.read_bytes(),original)
        destination=self.root/'existing';destination.mkdir();(destination/'keep.txt').write_text('Keep me')
        with self.assertRaises(FileExistsError):restore_backup(self.archive,destination)
        self.assertEqual((destination/'keep.txt').read_text(),'Keep me')

    def test_does_not_include_mail_secrets_or_source(self):
        (self.root/'.env').write_text('secret fixture')
        (self.root/'.private_mail').mkdir()
        (self.root/'.private_mail'/'test.log').write_text('private fixture')
        self.backup()
        with tarfile.open(self.archive) as archive:self.assertEqual(set(archive.getnames()),{'database.sqlite3','uploads/cvs/example.pdf','manifest.json'})

    def test_rejects_upload_symlinks_and_removes_failed_new_archive(self):
        (self.uploads/'linked').symlink_to(self.database)
        with self.assertRaises(BackupError):self.backup()
        self.assertFalse(self.archive.exists())

    def test_missing_database_and_output_inside_uploads_rejected(self):
        with self.assertRaises(BackupError):create_backup(self.root/'missing',self.uploads,self.archive)
        with self.assertRaises(BackupError):create_backup(self.database,self.uploads,self.uploads/'backup.tar.gz')

    def test_corrupt_manifest_checksum_does_not_leave_restored_data(self):
        self.backup();bad=self.root/'bad.tar.gz'
        with tarfile.open(self.archive) as source,tarfile.open(bad,'w:gz') as target:
            for member in source:
                content=source.extractfile(member).read()
                if member.name=='manifest.json':
                    value=json.loads(content);value['files']['database.sqlite3']['sha256']='0'*64;content=json.dumps(value).encode();member.size=len(content)
                target.addfile(member,io.BytesIO(content))
        destination=self.root/'failed-restore'
        with self.assertRaises(BackupError):restore_backup(bad,destination)
        self.assertFalse(destination.exists())

    def test_archive_traversal_and_symlinks_rejected_without_escape(self):
        for name,kind in [('../escape.txt',tarfile.REGTYPE),('uploads/link',tarfile.SYMTYPE)]:
            bad=self.root/'unsafe.tar.gz'
            with tarfile.open(bad,'w:gz') as archive:
                header=tarfile.TarInfo(name);header.type=kind;header.linkname='/etc/passwd';archive.addfile(header)
            with self.assertRaises(BackupError):restore_backup(bad,self.root/'unsafe')
            self.assertFalse((self.root/'unsafe').exists())
            self.assertFalse((self.root/'escape.txt').exists())

    def test_commands_require_offline_acknowledgment_and_protect_public_storage(self):
        with self.assertRaises(CommandError):call_command('backup_pilot',output=str(self.archive))
        with override_settings(STATIC_ROOT=self.root/'static'):
            with self.assertRaises(CommandError):call_command('backup_pilot',output=str(self.root/'static'/'snapshot.tar.gz'),offline=True)

    def test_management_command_recovery_drill(self):
        with override_settings(MEDIA_ROOT=self.uploads), patch.dict('django.conf.settings.DATABASES', {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':self.database}}):
            call_command('backup_pilot',output=str(self.archive),offline=True,stdout=io.StringIO())
        call_command('restore_pilot',archive=str(self.archive),destination=str(self.root/'drill'),stdout=io.StringIO())
        self.assertTrue((self.root/'drill/db.sqlite3').exists())

    def test_failed_archive_write_does_not_remove_previous_backup(self):
        self.backup();original=self.archive.read_bytes()
        with patch('opportunities.backups.tarfile.open',side_effect=OSError('simulated storage failure')):
            with self.assertRaises(FileExistsError):self.backup()
        self.assertEqual(self.archive.read_bytes(),original)
