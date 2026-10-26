import os
import re
import stat
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from pypdf import PdfWriter

from .models import Application, Employer, Opportunity, Profile
from .uploads import MAX_CV_BYTES


def pdf_file(name="my-cv.pdf", encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("private-password")
    output = BytesIO()
    writer.write(output)
    return SimpleUploadedFile(name, output.getvalue(), content_type="application/pdf")


class PrivateCVTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.applicant = User.objects.create_user("cv-candidate", email="candidate@example.com")
        cls.profile = Profile.objects.create(user=cls.applicant, full_name="Test Applicant")
        cls.employer_user = User.objects.create_user("cv-employer")
        Profile.objects.create(user=cls.employer_user, full_name="Employer", role="employer")
        cls.employer = Employer.objects.create(user=cls.employer_user, name="CV employer", verified=True)
        cls.job = Opportunity.objects.create(employer=cls.employer, title="CV internship", kind="internship", location="Addis Ababa", category="Testing", description="Test", requirements="Test", compensation="Stipend", deadline=timezone.localdate()+timedelta(days=20), published=True)
        cls.other = User.objects.create_user("unrelated-person")
        Profile.objects.create(user=cls.other, full_name="Other")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media_root = Path(temporary.name)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(self.applicant)

    def upload(self, file=None, **extra):
        data = {"full_name": "Test Applicant", **extra}
        if file is not None:
            data["cv"] = file
        return self.client.post(reverse("profile"), data)

    def attach(self):
        response = self.upload(pdf_file())
        self.assertRedirects(response, reverse("dashboard"))
        self.profile.refresh_from_db()
        return self.profile.cv.name

    def test_upload_pdf_and_download_as_private_attachment(self):
        name = self.attach()
        self.assertRegex(name, r"^cvs/[0-9a-f]{32}\.pdf$")
        self.assertEqual(stat.S_IMODE((self.media_root/name).stat().st_mode), 0o600)
        response = self.client.get(reverse("download_cv", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn('attachment;', response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
        response.close()
        self.assertEqual(self.client.get(self.profile.cv.url).status_code, 404)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, 'enctype="multipart/form-data"')
        self.assertContains(page, "Download current CV")
        self.assertNotContains(page, self.profile.cv.url)

    def test_unrelated_people_and_employers_cannot_download(self):
        self.attach()
        url = reverse("download_cv", args=[self.profile.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.employer_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_only_hiring_employer_can_download_after_application(self):
        self.attach()
        Application.objects.create(applicant=self.applicant, opportunity=self.job, cover_letter="Please consider me")
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("application", args=[Application.objects.get().pk]))
        self.assertContains(response, reverse("download_cv", args=[self.profile.pk]))
        response = self.client.get(reverse("download_cv", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
        Employer.objects.create(user=self.other, name="Other employer", verified=True)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("download_cv", args=[self.profile.pk])).status_code, 403)

    def test_admin_requires_profile_permission(self):
        self.attach()
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        url = reverse("download_cv", args=[self.profile.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.other.user_permissions.add(Permission.objects.get(codename="view_profile"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_rejects_non_pdf_and_disguised_pdf(self):
        for name, content in [("cv.html", b"<html>not a cv</html>"), ("cv.pdf", b"<script>not PDF</script>"), ("cv.pdf", b"%PDF-1.4\nnot a valid PDF")]:
            response = self.upload(SimpleUploadedFile(name, content, content_type="application/pdf"))
            self.assertEqual(response.status_code, 200)
            self.profile.refresh_from_db()
            self.assertFalse(self.profile.cv)
        self.assertFalse(list(self.media_root.rglob("*.pdf")))

    def test_rejects_oversized_and_encrypted_pdf(self):
        response = self.upload(SimpleUploadedFile("huge.pdf", b"%PDF-"+b"0"*MAX_CV_BYTES))
        self.assertContains(response, "5 MB or smaller")
        self.assertContains(self.upload(pdf_file(encrypted=True)), "without password protection")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.cv)

    def test_invalid_replacement_preserves_existing_cv(self):
        original = self.attach()
        self.upload(SimpleUploadedFile("bad.pdf", b"not PDF"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.cv.name, original)
        self.assertTrue((self.media_root/original).exists())

    def test_replacement_removal_and_account_deletion_clean_up_files(self):
        original = self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(pdf_file("replacement.pdf"))
        self.profile.refresh_from_db()
        replacement = self.profile.cv.name
        self.assertNotEqual(original, replacement)
        self.assertFalse((self.media_root/original).exists())
        self.assertTrue((self.media_root/replacement).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(remove_cv="on")
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.cv)
        self.assertFalse((self.media_root/replacement).exists())
        self.assertEqual(self.client.get(reverse("download_cv", args=[self.profile.pk])).status_code, 404)
        name = self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            self.applicant.delete()
        self.assertFalse((self.media_root/name).exists())

    def test_cannot_replace_and_remove_simultaneously(self):
        original = self.attach()
        self.assertContains(self.upload(pdf_file(), remove_cv="on"), "Choose either a replacement CV or removal")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.cv.name, original)

    def test_employer_cannot_upload_cv_or_change_other_profile(self):
        self.client.force_login(self.employer_user)
        self.upload(pdf_file())
        self.employer_user.profile.refresh_from_db()
        self.assertFalse(self.employer_user.profile.cv)
        self.assertNotContains(self.client.get(reverse("profile")), 'type="file"')
        self.client.force_login(self.other)
        self.upload(pdf_file())
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.cv)
        self.other.profile.refresh_from_db()
        self.assertTrue(self.other.profile.cv)

    def test_missing_stored_file_returns_404(self):
        name = self.attach()
        (self.media_root/name).unlink()
        self.assertEqual(self.client.get(reverse("download_cv", args=[self.profile.pk])).status_code, 404)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", PASSWORD_RESET_TIMEOUT=3600)
class PasswordRecoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("recover-me", "recover@example.com", "Old-strong-password-129!")
        Profile.objects.create(user=cls.user, full_name="Recovery Candidate")

    def send_reset(self, email="recover@example.com"):
        return self.client.post(reverse("password_reset"), {"email": email})

    def link_from_email(self):
        return re.search(r"http://testserver(/password/reset/[^\s]+)", mail.outbox[-1].body).group(1)

    def test_complete_recovery_and_single_use_token(self):
        self.assertRedirects(self.send_reset(), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["recover@example.com"])
        link = self.link_from_email()
        response = self.client.get(link, follow=True)
        self.assertContains(response, "Choose a new password")
        response = self.client.post(response.request["PATH_INFO"], {"new_password1":"New-unique-password-907!", "new_password2":"New-unique-password-907!"})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertFalse(self.client.login(username="recover-me", password="Old-strong-password-129!"))
        self.assertTrue(self.client.login(username="recover-me", password="New-unique-password-907!"))
        self.client.logout()
        self.assertContains(self.client.get(link, follow=True), "invalid, has expired, or has already been used")

    def test_unknown_address_gets_same_response_without_email(self):
        known = self.send_reset()
        count = len(mail.outbox)
        unknown = self.send_reset("unknown@example.com")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        self.assertEqual(len(mail.outbox), count)

    def test_inactive_or_unusable_accounts_do_not_get_reset_mail(self):
        self.user.is_active = False
        self.user.save()
        self.send_reset()
        self.assertEqual(len(mail.outbox), 0)
        self.user.is_active = True
        self.user.set_unusable_password()
        self.user.save()
        self.send_reset()
        self.assertEqual(len(mail.outbox), 0)

    def test_expired_and_malformed_links_fail(self):
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        link = reverse("password_reset_confirm", args=[uid, token])
        with patch.object(default_token_generator, "_now", return_value=default_token_generator._now()+timedelta(hours=2)):
            self.assertContains(self.client.get(link, follow=True), "invalid, has expired, or has already been used")
        self.assertContains(self.client.get(reverse("password_reset_confirm", args=["bad-uid", "bad-token"])), "invalid, has expired, or has already been used")

    def test_weak_new_password_is_rejected(self):
        self.send_reset()
        response = self.client.get(self.link_from_email(), follow=True)
        response = self.client.post(response.request["PATH_INFO"], {"new_password1":"123", "new_password2":"123"})
        self.assertContains(response, "This password is too short")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Old-strong-password-129!"))

    def test_local_inbox_is_private_and_not_web_accessible(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)/"private-inbox"
            with override_settings(EMAIL_BACKEND="opportunities.mail.PrivateFileEmailBackend", EMAIL_FILE_PATH=inbox):
                self.send_reset()
            files = list(inbox.glob("*.log"))
            self.assertEqual(len(files), 1)
            self.assertEqual(stat.S_IMODE(inbox.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            self.assertIn("recover@example.com", files[0].read_text())
            self.assertEqual(self.client.get("/.private_mail/"+files[0].name).status_code, 404)
