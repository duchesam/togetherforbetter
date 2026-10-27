import json
import os
from pathlib import Path
import subprocess
import tempfile

from django.test import Client, TestCase, override_settings
from django.urls import reverse


class CodespaceOriginTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory(prefix='codespace-csrf-') as runtime:
            environment = os.environ | {
                'CODESPACE_NAME': 'test-private-preview',
                'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN': 'app.github.dev',
                'PILOT_RUNTIME_DIR': runtime,
                'PILOT_PORT': '8000',
                'DJANGO_SECRET_KEY': 'test-only-origin-regression-key',
            }
            result = subprocess.run(
                ['bash', '-c', 'source .devcontainer/environment.sh\n.venv/bin/python -c \'import os,json; print(json.dumps(os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"].split(",")))\''],
                cwd=root, env=environment, check=True, capture_output=True, text=True,
            )
            cls.origins = json.loads(result.stdout)
        cls.preview = 'test-private-preview-8000.app.github.dev'

    def post_language(self, origin, token=True):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse('login'), secure=True, HTTP_HOST=self.preview)
        data = {'language': 'am', 'next': '/'}
        if token:
            data['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        return client.post(reverse('set_language'), data, secure=True, HTTP_HOST=self.preview, HTTP_ORIGIN=origin)

    def test_bootstrap_has_only_preview_and_exact_local_upstreams(self):
        self.assertEqual(set(self.origins), {f'https://{self.preview}', 'http://localhost:8000', 'http://127.0.0.1:8000'})

    def test_forwarded_local_origin_accepts_valid_token_and_sets_amharic(self):
        with override_settings(ALLOWED_HOSTS=[self.preview], CSRF_TRUSTED_ORIGINS=self.origins):
            for origin in self.origins:
                response = self.post_language(origin)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.cookies['django_language'].value, 'am')

    def test_unrelated_origins_and_ports_remain_rejected(self):
        with override_settings(ALLOWED_HOSTS=[self.preview], CSRF_TRUSTED_ORIGINS=self.origins):
            for origin in ['https://unrelated.example', 'http://localhost:9000', 'https://another-preview-8000.app.github.dev']:
                self.assertEqual(self.post_language(origin).status_code, 403)

    def test_trusted_origin_does_not_bypass_csrf_token(self):
        with override_settings(ALLOWED_HOSTS=[self.preview], CSRF_TRUSTED_ORIGINS=self.origins):
            self.assertEqual(self.post_language('http://localhost:8000', token=False).status_code, 403)

    def test_reproduces_original_failure_without_local_origin(self):
        with override_settings(ALLOWED_HOSTS=[self.preview], CSRF_TRUSTED_ORIGINS=[f'https://{self.preview}']):
            self.assertEqual(self.post_language('http://localhost:8000').status_code, 403)
