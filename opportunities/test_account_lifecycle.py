import re
import tempfile
import time
import uuid
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from .models import Application, EmailDelivery, Employer, Notification, Opportunity, OpportunityReport, Profile
from .notifications import application_status_changed, deliver_one, queue_verification, valid_verification_token, verification_token
from .test_accounts import pdf_file


class AccountFixture:
    @classmethod
    def setUpTestData(cls):
        cls.seeker = User.objects.create_user('lifecycle-candidate','candidate@example.com','Strong-lifecycle-password-91!')
        cls.profile = Profile.objects.create(user=cls.seeker,full_name='Candidate',email_verification_required=True)
        cls.owner = User.objects.create_user('lifecycle-employer','employer@example.com','Strong-lifecycle-password-92!')
        cls.owner_profile = Profile.objects.create(user=cls.owner,full_name='Employer',role='employer',verified_email=cls.owner.email,email_verified_at=timezone.now())
        cls.employer = Employer.objects.create(user=cls.owner,name='Lifecycle organization',verified=True)
        cls.job = Opportunity.objects.create(employer=cls.employer,title='Community Assistant',kind='entry',location='Addis Ababa',category='Community',description='Test listing',requirements='Curiosity',compensation='Stipend',deadline=timezone.localdate()+timedelta(days=10),published=True)

    def verify_profile(self):
        self.profile.verified_email=self.seeker.email
        self.profile.email_verified_at=timezone.now()
        self.profile.save()

    def token(self):
        queue_verification(self.profile)
        self.profile.refresh_from_db()
        return verification_token(self.profile)

    def apply(self):
        self.client.force_login(self.seeker)
        return self.client.post(reverse('apply',args=[self.job.pk]),{'cover_letter':'Please consider my application.'})


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTests(AccountFixture,TestCase):
    def test_signup_queues_verification_without_sending_in_request(self):
        response=self.client.post(reverse('signup'),{'username':'new-lifecycle','email':'new@example.com','full_name':'New Candidate','role':'seeker','password1':'Another-unique-password-77!','password2':'Another-unique-password-77!'})
        self.assertRedirects(response,reverse('dashboard'))
        profile=Profile.objects.get(user__username='new-lifecycle')
        self.assertTrue(profile.needs_email_verification)
        self.assertFalse(profile.is_email_verified)
        self.assertEqual(EmailDelivery.objects.get(recipient=profile.user).kind,'verification')
        self.assertEqual(len(mail.outbox),0)

    def test_get_does_not_verify_and_post_consumes_token(self):
        token=self.token();url=reverse('email_verify',args=[token])
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(url).status_code,200)
        self.profile.refresh_from_db();self.assertFalse(self.profile.is_email_verified)
        self.assertRedirects(self.client.post(url),reverse('account_settings'))
        self.profile.refresh_from_db();self.assertTrue(self.profile.is_email_verified)
        self.assertEqual(self.client.post(url).status_code,400)
        self.assertIn('no-store',self.client.get(reverse('account_settings'))['Cache-Control'])

    def test_other_account_and_tampered_links_fail(self):
        token=self.token()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('email_verify',args=[token])).status_code,400)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.post(reverse('email_verify',args=[token+'tampered'])).status_code,400)
        self.profile.refresh_from_db();self.assertFalse(self.profile.is_email_verified)

    def test_expired_link_and_changed_email_fail(self):
        token=self.token()
        with patch('django.core.signing.time.time',return_value=time.time()+86401):
            self.assertFalse(valid_verification_token(self.profile,token))
        self.seeker.email='changed@example.com';self.seeker.save()
        self.profile=Profile.objects.select_related('user').get(pk=self.profile.pk)
        self.assertFalse(valid_verification_token(self.profile,token))

    def test_resend_invalidates_old_link_and_old_queue_entry(self):
        old_token=self.token();old=EmailDelivery.objects.get()
        new_token=self.token()
        old.refresh_from_db();self.assertIsNotNone(old.cancelled_at)
        self.assertFalse(valid_verification_token(self.profile,old_token))
        self.assertTrue(valid_verification_token(self.profile,new_token))
        self.assertEqual(deliver_one(old.pk),'skipped')

    def test_anonymous_and_missing_csrf_cannot_verify(self):
        url=reverse('email_verify',args=[self.token()])
        self.assertEqual(self.client.get(url).status_code,302)
        client=Client(enforce_csrf_checks=True);client.force_login(self.seeker)
        self.assertEqual(client.post(url).status_code,403)
        self.profile.refresh_from_db();self.assertFalse(self.profile.is_email_verified)

    def test_new_accounts_cannot_apply_or_post_until_verified(self):
        self.assertRedirects(self.apply(),reverse('account_settings'))
        self.assertFalse(Application.objects.exists())
        self.owner_profile.email_verification_required=True
        self.owner_profile.verified_email='';self.owner_profile.email_verified_at=None;self.owner_profile.save()
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('post_job')),reverse('account_settings'))
        self.verify_profile();self.assertRedirects(self.apply(),reverse('dashboard'))
        self.assertTrue(Application.objects.exists())

    def test_legacy_account_is_not_silently_marked_verified_or_blocked(self):
        self.profile.email_verification_required=False;self.profile.save()
        self.assertRedirects(self.apply(),reverse('dashboard'))
        self.profile.refresh_from_db();self.assertFalse(self.profile.is_email_verified)

    def test_verification_request_is_post_only_and_invalid_email_is_rejected(self):
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse('verification_request')).status_code,405)
        self.seeker.email='';self.seeker.save()
        self.assertRedirects(self.client.post(reverse('verification_request')),reverse('account_settings'))
        self.assertFalse(EmailDelivery.objects.exists())

    def test_changing_verified_account_email_revokes_verification(self):
        self.verify_profile();self.assertTrue(self.profile.is_email_verified)
        self.seeker.email='another@example.com';self.seeker.save()
        profile=Profile.objects.select_related('user').get(pk=self.profile.pk)
        self.assertFalse(profile.is_email_verified)
        self.assertTrue(profile.needs_email_verification)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationTests(AccountFixture,TestCase):
    def setUp(self):
        self.verify_profile()

    def test_new_application_notifies_only_its_employer_once(self):
        self.apply()
        notice=Notification.objects.get()
        self.assertEqual(notice.recipient,self.owner)
        self.assertEqual(notice.kind,'application')
        self.assertEqual(EmailDelivery.objects.get().notification,notice)
        self.apply();self.assertEqual(Notification.objects.count(),1)
        self.assertEqual(EmailDelivery.objects.count(),1)

    def test_admin_status_change_uses_the_same_notification_flow(self):
        self.apply();application=Application.objects.get()
        admin=User.objects.create_superuser('status-admin','status-admin@example.com','Status-admin-password-64!')
        self.client.force_login(admin)
        data={'opportunity':self.job.pk,'applicant':self.seeker.pk,'cover_letter':application.cover_letter,'status':'hired','_save':'Save'}
        url=reverse('admin:opportunities_application_change',args=[application.pk])
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(Notification.objects.filter(recipient=self.seeker,status_code='hired').count(),1)
        self.client.post(url,data)
        self.assertEqual(Notification.objects.filter(recipient=self.seeker,status_code='hired').count(),1)

    def test_account_pages_are_available_in_amharic(self):
        self.client.force_login(self.seeker)
        for name in ['account_settings','account_delete','notifications']:
            response=self.client.get(reverse(name),HTTP_ACCEPT_LANGUAGE='am')
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'<html lang="am">')
            self.assertNotContains(response,'{%')

    def test_status_changes_notify_candidate_and_identical_status_is_noop(self):
        self.apply();application=Application.objects.get()
        self.client.force_login(self.owner)
        url=reverse('application',args=[application.pk])
        self.client.post(url,{'status':'shortlisted'})
        notice=Notification.objects.get(recipient=self.seeker)
        self.assertEqual(notice.status_code,'shortlisted')
        self.client.post(url,{'status':'shortlisted'})
        self.assertEqual(Notification.objects.filter(recipient=self.seeker).count(),1)
        self.client.post(url,{'status':'invalid'})
        self.assertEqual(Notification.objects.filter(recipient=self.seeker).count(),1)

    def test_inbox_and_mark_read_are_private_and_post_only(self):
        self.apply();notice=Notification.objects.get()
        self.assertNotContains(self.client.get(reverse('notifications')),'New application received')
        url=reverse('notification_open',args=[notice.pk])
        self.assertEqual(self.client.post(url).status_code,404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('notifications')),'New application received')
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertRedirects(self.client.post(url),reverse('application',args=[notice.application_id]))
        notice.refresh_from_db();self.assertIsNotNone(notice.read_at)

    def test_opt_out_keeps_in_app_notifications_but_cancels_queued_email(self):
        self.apply();delivery=EmailDelivery.objects.get()
        self.owner_profile.email_notifications=False;self.owner_profile.save()
        self.assertEqual(deliver_one(delivery.pk),'cancelled')
        self.assertEqual(len(mail.outbox),0)
        self.assertEqual(Notification.objects.count(),1)
        application=Application.objects.get()
        self.profile.email_notifications=False;self.profile.save()
        application.status='hired';application.save()
        application_status_changed(application)
        self.assertEqual(Notification.objects.filter(recipient=self.seeker).count(),1)
        self.assertFalse(EmailDelivery.objects.filter(recipient=self.seeker).exists())

    def test_settings_cannot_change_email_verification_or_role(self):
        self.client.force_login(self.seeker)
        response=self.client.post(reverse('account_settings'),{'preferred_language':'am','email_notifications':'','verified_email':'forged@example.com','role':'employer','email':'forged@example.com'})
        self.assertEqual(response.status_code,302)
        self.profile.refresh_from_db();self.seeker.refresh_from_db()
        self.assertEqual(self.profile.preferred_language,'am')
        self.assertFalse(self.profile.email_notifications)
        self.assertEqual(self.profile.role,'seeker')
        self.assertEqual(self.seeker.email,'candidate@example.com')
        self.assertEqual(response.cookies['django_language'].value,'am')
        self.client.post(reverse('set_language'),{'language':'en','next':'/'})
        self.profile.refresh_from_db();self.assertEqual(self.profile.preferred_language,'en')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PUBLIC_SITE_URL='http://testserver')
class EmailWorkerTests(AccountFixture,TestCase):
    def test_verification_delivery_is_localized_and_sent_once(self):
        self.profile.preferred_language='am';self.profile.save()
        delivery=queue_verification(self.profile)
        self.assertEqual(deliver_one(delivery.pk),'sent')
        self.assertEqual(deliver_one(delivery.pk),'skipped')
        self.assertEqual(len(mail.outbox),1)
        self.assertIn('ያረጋግጡ',mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to,[self.seeker.email])
        token=urlsplit(re.search(r'http://[^\s]+/account/verify/[^\s]+',mail.outbox[0].body).group()).path.split('/')[-2]
        self.profile.refresh_from_db();self.assertTrue(valid_verification_token(self.profile,token))

    def test_notification_delivery_contains_no_cv_or_cover_letter(self):
        self.verify_profile();self.apply()
        delivery=EmailDelivery.objects.get()
        self.assertEqual(deliver_one(delivery.pk),'sent')
        body=mail.outbox[0].body
        self.assertIn(self.job.title,body)
        self.assertIn('/applications/',body)
        self.assertNotIn('Please consider my application',body)
        self.assertNotIn(self.seeker.email,body)
        self.assertNotIn('/private-media/',body)

    def test_backend_failure_retries_and_stops_without_logging_sensitive_errors(self):
        delivery=queue_verification(self.profile)
        with patch('opportunities.notifications.EmailMessage.send',side_effect=OSError('DO NOT STORE: credential or recipient details')):
            for number in range(1,6):
                EmailDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
                result=deliver_one(delivery.pk)
                delivery.refresh_from_db()
                self.assertEqual(delivery.attempts,number)
                self.assertEqual(delivery.last_error_type,'OSError')
                self.assertNotIn('DO NOT STORE',delivery.last_error_type)
                self.assertEqual(result,'failed' if number==5 else 'deferred')
        self.assertIsNotNone(delivery.failed_at)
        self.assertEqual(deliver_one(delivery.pk),'skipped')
        self.assertEqual(len(mail.outbox),0)

    def test_active_claim_is_not_duplicated_and_stale_claim_is_recovered(self):
        delivery=queue_verification(self.profile)
        EmailDelivery.objects.filter(pk=delivery.pk).update(claim_token=uuid.uuid4(),claimed_at=timezone.now(),attempts=1)
        self.assertEqual(deliver_one(delivery.pk),'skipped')
        EmailDelivery.objects.filter(pk=delivery.pk).update(claimed_at=timezone.now()-timedelta(minutes=11))
        self.assertEqual(deliver_one(delivery.pk),'sent')
        self.assertEqual(len(mail.outbox),1)

    def test_changed_email_or_inactive_user_cancels_delivery(self):
        delivery=queue_verification(self.profile)
        self.seeker.email='different@example.com';self.seeker.save()
        self.assertEqual(deliver_one(delivery.pk),'cancelled')
        delivery=queue_verification(Profile.objects.select_related('user').get(pk=self.profile.pk))
        self.seeker.is_active=False;self.seeker.save()
        self.assertEqual(deliver_one(delivery.pk),'cancelled')
        self.assertEqual(len(mail.outbox),0)

    def test_verification_token_is_bound_to_queued_address_during_email_change_race(self):
        delivery=queue_verification(self.profile)
        def simulate_concurrent_change(item):
            User.objects.filter(pk=self.seeker.pk).update(email='new-address@example.com')
            return True
        with patch('opportunities.notifications.delivery_allowed',side_effect=simulate_concurrent_change):
            self.assertEqual(deliver_one(delivery.pk),'sent')
        token=urlsplit(re.search(r'http://[^\s]+/account/verify/[^\s]+',mail.outbox[0].body).group()).path.split('/')[-2]
        profile=Profile.objects.select_related('user').get(pk=self.profile.pk)
        self.assertFalse(valid_verification_token(profile,token))
        self.assertEqual(mail.outbox[0].to,['candidate@example.com'])

    def test_command_outputs_counts_not_recipients_or_tokens(self):
        queue_verification(self.profile)
        output=StringIO();call_command('deliver_emails',stdout=output)
        self.assertIn('sent=1',output.getvalue())
        self.assertNotIn(self.seeker.email,output.getvalue())
        self.assertNotIn('/account/verify/',output.getvalue())

    def test_admin_can_retry_terminal_failure_but_cannot_view_token_material(self):
        delivery=queue_verification(self.profile)
        EmailDelivery.objects.filter(pk=delivery.pk).update(failed_at=timezone.now(),attempts=5)
        admin=User.objects.create_superuser('queue-admin','admin@example.com','Queue-admin-password-98!')
        self.client.force_login(admin)
        response=self.client.get(reverse('admin:opportunities_emaildelivery_change',args=[delivery.pk]))
        self.assertNotContains(response,'verification_nonce')
        self.assertNotContains(response,'claim_token')
        response=self.client.post(reverse('admin:opportunities_emaildelivery_changelist'),{'action':'retry_failed','_selected_action':[delivery.pk]})
        self.assertEqual(response.status_code,302)
        delivery.refresh_from_db();self.assertIsNone(delivery.failed_at);self.assertEqual(delivery.attempts,0)
        self.assertEqual(deliver_one(delivery.pk),'sent')


class AccountDeletionTests(AccountFixture,TestCase):
    def test_wrong_password_missing_confirmation_and_get_do_not_delete(self):
        self.client.force_login(self.seeker)
        url=reverse('account_delete')
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertContains(self.client.post(url,{'password':'wrong','confirm':'on'}),'Your password was incorrect')
        self.assertEqual(self.client.post(url,{'password':'Strong-lifecycle-password-91!'}).status_code,200)
        self.assertTrue(User.objects.filter(pk=self.seeker.pk).exists())

    def test_deletion_removes_own_data_and_private_cv_preserving_other_accounts(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        with override_settings(MEDIA_ROOT=Path(temporary.name)):
            self.verify_profile();self.apply();application=Application.objects.get()
            application.status='reviewing';application.save();application_status_changed(application)
            OpportunityReport.objects.create(reporter=self.seeker,opportunity=self.job,reason='other',details='Retained report text')
            self.client.post(reverse('profile'),{'full_name':'Candidate','cv':pdf_file()})
            self.profile.refresh_from_db();cv_path=Path(self.profile.cv.path)
            self.assertTrue(cv_path.exists())
            seeker_id=self.seeker.pk;owner_id=self.owner.pk
            with self.captureOnCommitCallbacks(execute=True):
                response=self.client.post(reverse('account_delete'),{'password':'Strong-lifecycle-password-91!','confirm':'on','user_id':owner_id})
            self.assertRedirects(response,reverse('home'))
            self.assertFalse(User.objects.filter(pk=seeker_id).exists())
            self.assertTrue(User.objects.filter(pk=owner_id).exists())
            self.assertFalse(cv_path.exists())
            self.assertFalse(Application.objects.exists())
            self.assertFalse(Notification.objects.exists())
            self.assertFalse(EmailDelivery.objects.exists())
            self.assertIsNone(OpportunityReport.objects.get().reporter)
            self.assertEqual(self.client.get(reverse('dashboard')).status_code,302)

    def test_organization_staff_and_anonymous_users_cannot_delete_through_this_flow(self):
        url=reverse('account_delete')
        self.assertEqual(self.client.get(url).status_code,302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url,{'password':'Strong-lifecycle-password-92!','confirm':'on'}).status_code,403)
        self.seeker.is_staff=True;self.seeker.save();self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(User.objects.count(),2)

    def test_delete_requires_csrf(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.seeker)
        self.assertEqual(client.post(reverse('account_delete'),{'password':'Strong-lifecycle-password-91!','confirm':'on'}).status_code,403)
        self.assertTrue(User.objects.filter(pk=self.seeker.pk).exists())


class PrivateDeletionRecoveryTests(AccountFixture,TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.media_root=Path(temporary.name)
        override=override_settings(MEDIA_ROOT=self.media_root);override.enable();self.addCleanup(override.disable)
        self.client.force_login(self.seeker)
        self.client.post(reverse('profile'),{'full_name':'Candidate','cv':pdf_file()})
        self.profile.refresh_from_db()
        self.path=Path(self.profile.cv.path)

    def test_storage_failure_does_not_undo_account_deletion_and_can_be_retried(self):
        from .models import PrivateFileCleanup
        user_id=self.seeker.pk
        with patch('django.core.files.storage.FileSystemStorage.delete',side_effect=OSError('Sensitive storage details')):
            with self.captureOnCommitCallbacks(execute=True):
                response=self.client.post(reverse('account_delete'),{'password':'Strong-lifecycle-password-91!','confirm':'on'})
        self.assertRedirects(response,reverse('home'))
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        task=PrivateFileCleanup.objects.get()
        self.assertEqual(task.last_error_type,'OSError')
        self.assertTrue(self.path.exists())
        PrivateFileCleanup.objects.filter(pk=task.pk).update(available_at=timezone.now())
        output=StringIO();call_command('cleanup_private_files',stdout=output)
        self.assertIn('removed=1',output.getvalue())
        self.assertNotIn(task.name,output.getvalue())
        self.assertFalse(self.path.exists())
        self.assertFalse(PrivateFileCleanup.objects.exists())

    def test_failed_database_transaction_preserves_original_document(self):
        from django.db import transaction
        from .models import PrivateFileCleanup
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.profile.cv='';self.profile.save()
                raise RuntimeError('Abort local change')
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.cv)
        self.assertTrue(self.path.exists())
        self.assertFalse(PrivateFileCleanup.objects.exists())

    def test_terminal_cleanup_failures_are_visible_and_recoverable(self):
        from .models import PrivateFileCleanup
        from .file_cleanup import remove_private_file
        with patch('django.core.files.storage.FileSystemStorage.delete',side_effect=OSError('Storage failure')):
            with self.captureOnCommitCallbacks(execute=True):
                self.profile.cv='';self.profile.save()
        task=PrivateFileCleanup.objects.get()
        with patch('django.core.files.storage.FileSystemStorage.delete',side_effect=OSError('Storage failure')):
            for _ in range(4): remove_private_file(task.pk)
        task.refresh_from_db();self.assertIsNotNone(task.failed_at)
        call_command('cleanup_private_files','--retry-failed',stdout=StringIO())
        self.assertFalse(self.path.exists())
        self.assertFalse(PrivateFileCleanup.objects.exists())

    def test_cleanup_never_deletes_a_document_still_in_use(self):
        from .models import PrivateFileCleanup
        from .file_cleanup import remove_private_file
        task=PrivateFileCleanup.objects.create(name=self.profile.cv.name)
        self.assertEqual(remove_private_file(task.pk),'in_use')
        self.assertTrue(self.path.exists())


class ConcurrentAccountRecoveryTests(TestCase):
    def test_password_recovery_does_not_recreate_a_deleted_account(self):
        from django.core.exceptions import ValidationError
        from .forms import LockedSetPasswordForm
        user=User.objects.create_user('recovery-race','race@example.com','Old-strong-password-44!')
        form=LockedSetPasswordForm(user,data={'new_password1':'New-strong-password-55!','new_password2':'New-strong-password-55!'})
        self.assertTrue(form.is_valid())
        User.objects.filter(pk=user.pk).delete()
        with self.assertRaises(ValidationError): form.save()
        self.assertFalse(User.objects.filter(username='recovery-race').exists())

    def test_concurrent_credential_change_invalidates_pending_reset_save(self):
        from django.core.exceptions import ValidationError
        from django.contrib.auth.hashers import make_password
        from .forms import LockedSetPasswordForm
        user=User.objects.create_user('credential-race','race@example.com','Old-strong-password-44!')
        form=LockedSetPasswordForm(user,data={'new_password1':'New-strong-password-55!','new_password2':'New-strong-password-55!'})
        self.assertTrue(form.is_valid())
        User.objects.filter(pk=user.pk).update(password=make_password('Concurrent-password-99!'))
        with self.assertRaises(ValidationError): form.save()
        user.refresh_from_db();self.assertTrue(user.check_password('Concurrent-password-99!'))


class ConcurrentProfileUpdateTests(AccountFixture,TestCase):
    def test_profile_edit_does_not_overwrite_concurrent_email_verification(self):
        from .forms import ProfileForm
        form=ProfileForm(data={'full_name':'Updated candidate'},instance=self.profile)
        self.assertTrue(form.is_valid())
        nonce=uuid.uuid4()
        Profile.objects.filter(pk=self.profile.pk).update(verified_email=self.seeker.email,email_verified_at=timezone.now(),verification_nonce=nonce)
        form.save()
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_email_verified)
        self.assertEqual(self.profile.verification_nonce,nonce)
        self.assertEqual(self.profile.full_name,'Updated candidate')

    def test_preferences_do_not_overwrite_concurrent_profile_changes(self):
        from .forms import AccountPreferencesForm
        form=AccountPreferencesForm(data={'preferred_language':'am','email_notifications':''},instance=self.profile)
        self.assertTrue(form.is_valid())
        Profile.objects.filter(pk=self.profile.pk).update(full_name='Concurrent profile edit')
        form.save()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name,'Concurrent profile edit')
        self.assertEqual(self.profile.preferred_language,'am')
