import io
import json
import os
import subprocess
import sys
import sqlite3
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from deploy.host_environment import activate


class HostEnvironmentTests(SimpleTestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='pilot-host-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.private=self.root/'private'
        self.config=self.private/'production.json'

    def initialize(self):
        output=io.StringIO()
        call_command('init_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',stdout=output)
        return output.getvalue()

    def test_initializer_uses_private_permissions_no_secret_output(self):
        output=self.initialize()
        data=json.loads(self.config.read_text())
        self.assertNotIn(data['DJANGO_SECRET_KEY'],output)
        self.assertGreaterEqual(len(data['DJANGO_SECRET_KEY']),50)
        self.assertEqual(self.config.stat().st_mode&0o777,0o600)
        self.assertEqual(self.private.stat().st_mode&0o777,0o700)
        self.assertEqual(data['PUBLIC_SITE_URL'],'https://sample.pythonanywhere.com')
        self.assertEqual(data['DJANGO_TRUST_PROXY_SSL_HEADER'],'0')

    def test_existing_configuration_is_not_replaced(self):
        self.initialize();original=self.config.read_bytes()
        with self.assertRaises(CommandError):self.initialize()
        self.assertEqual(self.config.read_bytes(),original)

    def test_invalid_host_and_repository_directory_rejected(self):
        for hostname in ['https://sample.com','*.example.org','sample.com:443','sample.com/path','bad_name.example.org']:
            with self.assertRaises(CommandError):call_command('init_host_config',directory=str(self.private),hostname=hostname,stdout=io.StringIO())
        with self.assertRaises(CommandError):call_command('init_host_config',directory=str(Path(__file__).resolve().parent.parent),hostname='valid.example.org',stdout=io.StringIO())

    def test_shared_config_loads_and_removes_inherited_credentials(self):
        self.initialize()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'another-app-key','DJANGO_TRUST_PROXY_SSL_HEADER':'1'}):
            activate(self.config)
            self.assertEqual(os.environ['DJANGO_DEBUG'],'0')
            self.assertEqual(os.environ['OPENAI_API_KEY'],'')
            self.assertEqual(os.environ['DJANGO_TRUST_PROXY_SSL_HEADER'],'0')
            self.assertEqual(os.environ['DJANGO_DATA_DIR'],str(self.private))

    def test_world_readable_config_or_directory_is_rejected(self):
        self.initialize();self.config.chmod(0o644)
        with self.assertRaises(RuntimeError):activate(self.config)
        self.config.chmod(0o600);self.private.chmod(0o755)
        with self.assertRaises(RuntimeError):activate(self.config)

    def test_invalid_settings_fail_before_changing_environment(self):
        self.initialize()
        for changes in [{'DJANGO_DEBUG':'1'},{'DJANGO_SECRET_KEY':''},{'UNEXPECTED_SETTING':'value'},{'EMAIL_PORT':587}]:
            original=json.loads(self.config.read_text());data=original|changes
            self.config.write_text(json.dumps(data))
            with patch.dict(os.environ,{'DJANGO_DEBUG':'existing'}):
                with self.assertRaises(RuntimeError):activate(self.config)
                self.assertEqual(os.environ['DJANGO_DEBUG'],'existing')
            self.config.write_text(json.dumps(original))

    def test_symlink_config_is_rejected(self):
        self.initialize();link=self.private/'link.json';link.symlink_to(self.config)
        with self.assertRaises(RuntimeError):activate(link)

    def test_host_management_launcher_targets_private_database(self):
        self.initialize()
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run([sys.executable,str(root/'scripts/host_manage.py'),'--config',str(self.config),'migrate','--noinput'],cwd=root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.private/'db.sqlite3').exists())
        with sqlite3.connect(self.private/'db.sqlite3') as database:
            self.assertGreater(database.execute('SELECT COUNT(*) FROM django_migrations').fetchone()[0],0)

    def test_recovery_of_email_only_fragment_preserves_credentials_and_database(self):
        self.private.mkdir(mode=0o700)
        fragment='"EMAIL_HOST": "smtp.gmail.com", "EMAIL_PORT": "587", "EMAIL_HOST_USER": "fixture@example.invalid", "EMAIL_HOST_PASSWORD": "private-fixture-password"'
        self.config.write_text(fragment);self.config.chmod(0o600)
        database=self.private/'db.sqlite3';database.write_bytes(b'existing database fixture')
        output=io.StringIO()
        call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',replace_missing_secret=True,stdout=output)
        data=json.loads(self.config.read_text())
        self.assertEqual(data['EMAIL_HOST_PASSWORD'],'private-fixture-password')
        self.assertGreaterEqual(len(data['DJANGO_SECRET_KEY']),50)
        self.assertEqual(database.read_bytes(),b'existing database fixture')
        self.assertNotIn('private-fixture-password',output.getvalue())
        self.assertNotIn(data['DJANGO_SECRET_KEY'],output.getvalue())
        copies=list(self.private.glob('production.before-recovery-*.json'))
        self.assertEqual(len(copies),1)
        self.assertEqual(copies[0].read_text(),fragment)
        self.assertEqual(self.config.stat().st_mode&0o777,0o600)
        self.assertEqual(copies[0].stat().st_mode&0o777,0o600)

    def test_missing_secret_requires_explicit_acknowledgment(self):
        self.private.mkdir(mode=0o700);self.config.write_text('"EMAIL_HOST":"smtp.gmail.com"');self.config.chmod(0o600)
        before=self.config.read_bytes()
        with self.assertRaises(CommandError):call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',stdout=io.StringIO())
        self.assertEqual(self.config.read_bytes(),before)

    def test_recovery_preserves_existing_secret_when_fixing_braces(self):
        self.initialize();original=json.loads(self.config.read_text())
        self.config.write_text(self.config.read_text().strip()[1:-1])
        call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',stdout=io.StringIO())
        self.assertEqual(json.loads(self.config.read_text()),original)

    def test_recovery_rejects_ambiguous_or_invalid_input_without_replacement(self):
        self.private.mkdir(mode=0o700)
        for fragment in ['broken text','"EMAIL_HOST":"one","EMAIL_HOST":"two"','{"UNEXPECTED":"value"}','{"EMAIL_PORT":587}']:
            self.config.write_text(fragment);self.config.chmod(0o600)
            with self.assertRaises(CommandError):call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',replace_missing_secret=True,stdout=io.StringIO())
            self.assertEqual(self.config.read_text(),fragment)

    def test_recovery_does_not_change_existing_host_or_data_directory(self):
        self.initialize();original=json.loads(self.config.read_text());original['DJANGO_DATA_DIR']=str(self.root/'different-data')
        self.config.write_text(json.dumps(original))
        with self.assertRaises(CommandError):call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',stdout=io.StringIO())
        self.assertEqual(json.loads(self.config.read_text()),original)

    def test_failed_recovery_write_leaves_original_file(self):
        self.initialize();original=self.config.read_bytes()
        with patch('opportunities.management.commands.recover_host_config.os.replace',side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):call_command('recover_host_config',directory=str(self.private),hostname='sample.pythonanywhere.com',stdout=io.StringIO())
        self.assertEqual(self.config.read_bytes(),original)
        self.assertFalse(list(self.private.glob('.production-recovery-*')))
