import io
import json
import os
from pathlib import Path
import smtplib
import tempfile
from unittest.mock import MagicMock,patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase,override_settings
from deploy.host_environment import initial_configuration
from .gmail import GmailEmailBackend,LoginSMTP,LoginSMTPSSL


class GmailBackendTests(SimpleTestCase):
    def test_login_uses_challenges_instead_of_initial_plain_credentials(self):
        server=LoginSMTP(timeout=15)
        server.esmtp_features={'auth':'PLAIN LOGIN XOAUTH2'}
        with patch.object(server,'ehlo_or_helo_if_needed'),patch.object(server,'docmd',side_effect=[(334,b'VXNlcm5hbWU6'),(334,b'UGFzc3dvcmQ6'),(235,b'OK')]) as send:
            self.assertEqual(server.login('synthetic@example.invalid','synthetic-password')[0],235)
            self.assertEqual(send.call_args_list[0].args,('AUTH','LOGIN'))
            self.assertEqual(send.call_count,3)

    def test_unsupported_login_is_not_replaced_with_insecure_authentication(self):
        server=LoginSMTP(timeout=15);server.esmtp_features={'auth':'XOAUTH2'}
        with patch.object(server,'ehlo_or_helo_if_needed'):
            with self.assertRaises(smtplib.SMTPNotSupportedError):server.login('example','not-real')

    def test_backend_uses_tls_and_bounded_connection_timeout(self):
        backend=GmailEmailBackend(host='smtp.gmail.com',port=587,use_tls=True,use_ssl=False,username='example@example.invalid',password='synthetic-pass',timeout=15)
        with patch('opportunities.gmail.LoginSMTP') as smtp:
            self.assertTrue(backend.open())
            smtp.assert_called_once_with('smtp.gmail.com',587,local_hostname=smtp.call_args.kwargs['local_hostname'],timeout=15)
            smtp.return_value.starttls.assert_called_once()
            smtp.return_value.login.assert_called_once_with('example@example.invalid','synthetic-pass')
            self.assertTrue(backend.ssl_context.check_hostname)

    def test_unencrypted_or_wrong_host_backend_rejected(self):
        for host,tls in [('wrong.example',True),('smtp.gmail.com',False)]:
            with self.assertRaises(ImproperlyConfigured):GmailEmailBackend(host=host,use_tls=tls,use_ssl=False).open()
        self.assertEqual(GmailEmailBackend(host='smtp.gmail.com',use_ssl=True,use_tls=False).connection_class,LoginSMTPSSL)


class GmailSetupTests(SimpleTestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='gmail-setup-test-');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.root.chmod(0o700)
        self.path=self.root/'production.json'
        self.config=initial_configuration(self.root,'pilot.example.org')
        self.config['EMAIL_HOST_USER']='synthetic@example.invalid'
        self.path.write_text(json.dumps(self.config));self.path.chmod(0o600)
        self.override=override_settings(DATA_DIR=self.root,SECRET_KEY=self.config['DJANGO_SECRET_KEY']);self.override.enable();self.addCleanup(self.override.disable)
        self.environment=patch.dict(os.environ,{});self.environment.start();self.addCleanup(self.environment.stop)

    def run_setup(self, backend, password='abcd efgh ijkl mnop'):
        output=io.StringIO()
        with patch('sys.stdin.isatty',return_value=True),patch('builtins.input',return_value=''),patch('getpass.getpass',return_value=password),patch('opportunities.management.commands.setup_gmail.GmailEmailBackend',return_value=backend):
            call_command('setup_gmail',stdout=output)
        return output.getvalue()

    def test_save_only_after_success_preserving_secret_and_private_mode(self):
        backend=MagicMock()
        output=self.run_setup(backend)
        result=json.loads(self.path.read_text())
        self.assertEqual(result['EMAIL_HOST_PASSWORD'],'abcdefghijklmnop')
        self.assertEqual(result['DJANGO_SECRET_KEY'],self.config['DJANGO_SECRET_KEY'])
        self.assertEqual(result['DJANGO_DATA_DIR'],str(self.root))
        self.assertEqual(result['EMAIL_BACKEND'],'opportunities.gmail.GmailEmailBackend')
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertNotIn('abcdefghijklmnop',output)
        self.assertNotIn(self.config['DJANGO_SECRET_KEY'],output)
        backend.send_messages.assert_not_called()

    def test_gmail_rejection_leaves_config_unchanged_and_hides_provider_details(self):
        backend=MagicMock();backend.open.side_effect=smtplib.SMTPAuthenticationError(535,b'private provider detail')
        original=self.path.read_bytes()
        with self.assertRaises(CommandError) as error:self.run_setup(backend)
        self.assertIn('535',str(error.exception))
        self.assertNotIn('private provider detail',str(error.exception))
        self.assertEqual(self.path.read_bytes(),original)

    def test_invalid_password_and_missing_terminal_do_not_contact_gmail(self):
        backend=MagicMock()
        with self.assertRaises(CommandError):self.run_setup(backend,password='wrong')
        backend.open.assert_not_called()
        with patch('sys.stdin.isatty',return_value=False):
            with self.assertRaises(CommandError):call_command('setup_gmail',stdout=io.StringIO())

    def test_concurrent_edit_not_overwritten(self):
        backend=MagicMock()
        def change():
            updated=self.config|{'RESUME_AI_MODEL':'another-model'}
            self.path.write_text(json.dumps(updated))
        backend.open.side_effect=change
        with self.assertRaises(CommandError):self.run_setup(backend)
        self.assertEqual(json.loads(self.path.read_text())['RESUME_AI_MODEL'],'another-model')
        self.assertFalse(list(self.root.glob('.gmail-config-*')))
