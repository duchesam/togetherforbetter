from unittest.mock import patch
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from .admin import ApplicationAdminForm
from .forms import StatusForm
from .hiring import HiringConflict, withdraw_application, invite_to_interview, respond_to_interview
from .models import Application, ApplicationWithdrawal, EmailDelivery, InterviewEvent, Notification
from .notifications import change_application_status, render_delivery
from .test_hiring import HiringFixture


class WithdrawalTests(HiringFixture, TestCase):
    def url(self):
        return reverse('application_withdraw', args=[self.application.pk])

    def withdraw(self):
        return withdraw_application(self.application.pk, self.candidate, 'reviewing')

    def test_records_history_and_notifies_both_parties_once(self):
        self.withdraw(); self.withdraw()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'withdrawn')
        self.assertEqual(ApplicationWithdrawal.objects.get().previous_status, 'reviewing')
        notices=Notification.objects.filter(kind='withdrawal')
        self.assertEqual(notices.count(),2)
        self.assertEqual(set(notices.values_list('recipient_id',flat=True)),{self.owner.pk,self.candidate.pk})
        self.assertEqual(EmailDelivery.objects.count(),2)
        self.assertFalse(LogEntry.objects.exists())

    def test_cancel_interview_retains_history_and_cancels_stale_mail(self):
        interview=self.invite()
        old_delivery=EmailDelivery.objects.get()
        self.withdraw()
        interview.refresh_from_db();old_delivery.refresh_from_db()
        self.assertEqual(interview.status,'cancelled')
        self.assertIsNotNone(old_delivery.cancelled_at)
        self.assertEqual(list(InterviewEvent.objects.values_list('status',flat=True)),['pending','cancelled'])
        with self.assertRaises(HiringConflict):respond_to_interview(interview.pk,self.candidate,'accepted')
        with self.assertRaises(HiringConflict):invite_to_interview(self.application.pk,self.owner,self.data())

    def test_only_applicant_can_withdraw(self):
        for actor in [self.owner,self.other,User.objects.create_superuser('withdraw-admin','admin@example.invalid','Password-9!')]:
            with self.assertRaises(PermissionDenied):withdraw_application(self.application.pk,actor,'reviewing')
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url()).status_code,404)
            self.assertEqual(self.client.post(self.url(),{'expected_status':'reviewing','confirm':'on'}).status_code,404)
        self.assertFalse(ApplicationWithdrawal.objects.exists())

    def test_confirmation_required_get_does_not_mutate_csrf_enforced(self):
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.get(self.url()).status_code,200)
        self.client.post(self.url(),{'expected_status':'reviewing'})
        self.assertFalse(ApplicationWithdrawal.objects.exists())
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.candidate)
        self.assertEqual(secure.post(self.url(),{'expected_status':'reviewing','confirm':'on'}).status_code,403)
        self.assertRedirects(self.client.post(self.url(),{'expected_status':'reviewing','confirm':'on'}),reverse('application',args=[self.application.pk]))

    def test_stale_form_and_final_status_rejected(self):
        change_application_status(self.application.pk,self.owner,'shortlisted')
        with self.assertRaises(HiringConflict):self.withdraw()
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(self.url(),{'expected_status':'reviewing','confirm':'on'}).status_code,409)
        for status in ['hired','declined']:
            change_application_status(self.application.pk,self.owner,status)
            with self.assertRaises(HiringConflict):withdraw_application(self.application.pk,self.candidate,status)
        self.assertFalse(ApplicationWithdrawal.objects.exists())

    def test_employer_service_and_form_cannot_set_or_reopen_withdrawal(self):
        with self.assertRaises(HiringConflict):change_application_status(self.application.pk,self.owner,'withdrawn')
        self.assertFalse(StatusForm({'status':'withdrawn'},instance=self.application).is_valid())
        self.withdraw()
        with self.assertRaises(HiringConflict):change_application_status(self.application.pk,self.owner,'hired')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('application',args=[self.application.pk]),{'status':'hired'}).status_code,409)
        self.assertFalse(self.application.placement_reports.exists())

    def test_stale_admin_form_rejects_reopening_and_cannot_initiate_withdrawal(self):
        data={'applicant':self.candidate.pk,'opportunity':self.job.pk,'cover_letter':'Private application','status':'withdrawn'}
        self.assertFalse(ApplicationAdminForm(data,instance=self.application).is_valid())
        self.withdraw();data['status']='hired'
        self.assertFalse(ApplicationAdminForm(data,instance=self.application).is_valid())

    def test_admin_cannot_reopen_withdrawn_application(self):
        self.withdraw()
        admin=User.objects.create_superuser('withdrawal-admin','admin@example.invalid','Password-9!')
        self.client.force_login(admin)
        url=reverse('admin:opportunities_application_change',args=[self.application.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        self.client.post(url,{'status':'hired','_save':'Save'})
        self.application.refresh_from_db()
        self.assertEqual(self.application.status,'withdrawn')

    def test_transaction_rolls_back_on_notification_failure(self):
        interview=self.invite()
        with patch('opportunities.hiring.record_notification',side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):self.withdraw()
        self.application.refresh_from_db();interview.refresh_from_db()
        self.assertEqual(self.application.status,'reviewing')
        self.assertEqual(interview.status,'pending')
        self.assertFalse(ApplicationWithdrawal.objects.exists())
        self.assertIsNone(EmailDelivery.objects.get().cancelled_at)

    def test_reapplication_cannot_replace_withdrawn_record(self):
        self.withdraw();self.client.force_login(self.candidate)
        self.client.post(reverse('apply',args=[self.job.pk]),{'cover_letter':'Try again'})
        self.assertEqual(Application.objects.count(),1)
        self.application.refresh_from_db();self.assertEqual(self.application.status,'withdrawn')

    def test_private_page_and_amharic_confirmation(self):
        self.client.force_login(self.candidate);self.client.cookies['django_language']='am'
        response=self.client.get(self.url())
        self.assertContains(response,'lang="am"')
        self.assertIn('no-store',response['Cache-Control'])
        self.withdraw()
        response=self.client.get(reverse('application',args=[self.application.pk]))
        self.assertNotContains(response,'status-form')
        self.assertNotContains(response,'interview-response-form')
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code,302)

    def test_withdrawal_email_describes_applicant_action(self):
        self.withdraw()
        for delivery in EmailDelivery.objects.all():
            body=render_delivery(delivery).body
            self.assertIn('The applicant withdrew this application.',body)
            self.assertNotIn('Your application for',body)
