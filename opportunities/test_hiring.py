import importlib
import uuid
from datetime import timedelta, timezone as utc_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .hiring import invite_to_interview, respond_to_interview, respond_to_placement
from .models import Application, EmailDelivery, Employer, Interview, InterviewEvent, Notification, PlacementReport, PlacementResponseEvent, Profile
from .models import Opportunity
from .notifications import change_application_status, deliver_one


class HiringFixture:
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user('hiring-owner','owner@example.com','Owner-hiring-password-41!')
        cls.candidate=User.objects.create_user('hiring-candidate','candidate@example.com','Candidate-hiring-password-42!')
        cls.other=User.objects.create_user('hiring-other','other@example.com','Other-hiring-password-43!')
        for user,role in [(cls.owner,'employer'),(cls.candidate,'seeker'),(cls.other,'seeker')]:
            Profile.objects.create(user=user,full_name=user.username,role=role,verified_email=user.email,email_verified_at=timezone.now())
        cls.employer=Employer.objects.create(user=cls.owner,name='Hiring test organization',verified=True)
        cls.job=Opportunity.objects.create(employer=cls.employer,title='Community assistant',kind='entry',location='Addis Ababa',category='Community',description='Test',requirements='Test',compensation='Stipend',deadline=timezone.localdate()+timedelta(days=30),published=True)
        cls.application=Application.objects.create(opportunity=cls.job,applicant=cls.candidate,cover_letter='Private application',status='reviewing')

    def data(self,**changes):
        return {'request_key':uuid.uuid4(),'scheduled_at':timezone.localtime(timezone.now()+timedelta(days=2)).replace(second=0,microsecond=0),'duration_minutes':30,'mode':'video','location':'','meeting_url':'https://meeting.example.invalid/private-room','details':'A synthetic interview for testing.',**changes}

    def invite(self,**changes):
        return invite_to_interview(self.application.pk,self.owner,self.data(**changes))

    def post_invite(self,data):
        self.client.force_login(self.owner)
        data={**data,'scheduled_at':timezone.localtime(data['scheduled_at']).strftime('%Y-%m-%dT%H:%M')}
        return self.client.post(reverse('interview_invite',args=[self.application.pk]),data)

    def hire(self):
        change_application_status(self.application.pk,self.owner,'hired')
        return PlacementReport.objects.get(application=self.application,superseded_at__isnull=True)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InterviewWorkflowTests(HiringFixture,TestCase):
    def test_invitation_uses_addis_time_and_private_notification(self):
        data=self.data()
        self.assertRedirects(self.post_invite(data),reverse('application',args=[self.application.pk]))
        interview=Interview.objects.get()
        self.assertEqual(interview.scheduled_at,data['scheduled_at'])
        self.assertEqual(InterviewEvent.objects.get().status,'pending')
        notice=Notification.objects.get();self.assertEqual(notice.recipient,self.candidate)
        self.assertEqual(notice.interview,interview)
        self.assertEqual(len(mail.outbox),0)
        response=self.client.get(reverse('application',args=[self.application.pk]))
        self.assertContains(response,'UTC+3')
        self.assertContains(response,data['scheduled_at'].strftime('%H:%M'))
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(len(response.context['interviews']),1)

    def test_same_invitation_submission_is_idempotent(self):
        data=self.data()
        self.post_invite(data);self.post_invite(data)
        self.assertEqual(Interview.objects.count(),1)
        self.assertEqual(InterviewEvent.objects.count(),1)
        self.assertEqual(Notification.objects.count(),1)

    def test_reusing_key_with_changed_payload_returns_conflict(self):
        data=self.data();self.post_invite(data)
        self.assertEqual(self.post_invite({**data,'details':'Different details'}).status_code,409)
        self.assertEqual(Interview.objects.count(),1)
        self.assertEqual(Interview.objects.get().status,'pending')

    def test_only_hiring_employer_can_invite(self):
        url=reverse('interview_invite',args=[self.application.pk])
        self.assertEqual(self.client.get(url).status_code,302)
        for user in [self.candidate,self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(url,{}).status_code,403)
        self.assertFalse(Interview.objects.exists())

    def test_invalid_new_invitation_never_replaces_existing_one(self):
        current=self.invite()
        for changes in [{'scheduled_at':timezone.now()-timedelta(hours=1)}, {'meeting_url':'http://meeting.example.invalid/'}, {'meeting_url':'https://user:password@meeting.example.invalid/'}, {'mode':'in_person','meeting_url':'','location':''}, {'mode':'phone','meeting_url':'','details':''}]:
            response=self.post_invite(self.data(**changes))
            self.assertEqual(response.status_code,200)
            current.refresh_from_db();self.assertEqual(current.status,'pending')
            self.assertEqual(Interview.objects.count(),1)

    def test_replacement_preserves_history_and_blocks_stale_reply(self):
        old=self.invite()
        original_delivery=EmailDelivery.objects.get()
        new=self.invite(details='New invitation')
        old.refresh_from_db();original_delivery.refresh_from_db()
        self.assertEqual(old.status,'replaced')
        self.assertIsNotNone(original_delivery.cancelled_at)
        self.assertEqual(old.events.count(),2)
        self.client.force_login(self.candidate)
        response=self.client.post(reverse('interview_response',args=[old.pk]),{'status':'accepted'})
        self.assertEqual(response.status_code,409)
        new.refresh_from_db();self.assertEqual(new.status,'pending')

    def test_response_and_repeat_do_not_duplicate_events(self):
        interview=self.invite();self.client.force_login(self.candidate)
        url=reverse('interview_response',args=[interview.pk])
        self.assertRedirects(self.client.post(url,{'status':'accepted','note':'Thank you'}),reverse('application',args=[self.application.pk]))
        self.client.post(url,{'status':'accepted','note':'Thank you'})
        self.assertEqual(interview.events.count(),2)
        self.assertEqual(Notification.objects.filter(recipient=self.owner).count(),1)
        interview.refresh_from_db();self.assertEqual(interview.status,'accepted')

    def test_request_another_time_needs_message_and_preserves_prior_response(self):
        interview=self.invite();self.client.force_login(self.candidate)
        url=reverse('interview_response',args=[interview.pk])
        self.assertEqual(self.client.post(url,{'status':'reschedule'}).status_code,400)
        self.assertEqual(self.client.post(url,{'status':'reschedule','note':'Could we meet the following morning?'}).status_code,302)
        interview.refresh_from_db();self.assertEqual(interview.status,'reschedule')
        self.assertIn('following morning',interview.response_note)

    def test_only_applicant_can_respond_and_only_owner_can_cancel(self):
        interview=self.invite()
        for user in [self.owner,self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse('interview_response',args=[interview.pk]),{'status':'accepted'}).status_code,403)
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(reverse('interview_cancel',args=[interview.pk])).status_code,403)
        interview.refresh_from_db();self.assertEqual(interview.status,'pending')

    def test_cancellation_is_post_only_and_idempotent(self):
        interview=self.invite();self.client.force_login(self.owner)
        url=reverse('interview_cancel',args=[interview.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.post(url);self.client.post(url)
        interview.refresh_from_db();self.assertEqual(interview.status,'cancelled')
        self.assertEqual(interview.events.count(),2)
        self.assertEqual(Notification.objects.count(),2)

    def test_hire_closes_interview_and_new_scheduling(self):
        interview=self.invite();self.hire()
        interview.refresh_from_db();self.assertEqual(interview.status,'cancelled')
        self.assertEqual(self.post_invite(self.data()).status_code,409)
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(reverse('interview_response',args=[interview.pk]),{'status':'accepted'}).status_code,409)

    def test_past_invitation_cannot_receive_response(self):
        interview=self.invite()
        Interview.objects.filter(pk=interview.pk).update(scheduled_at=timezone.now()-timedelta(minutes=1))
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(reverse('interview_response',args=[interview.pk]),{'status':'accepted'}).status_code,409)

    def test_declined_previous_invitation_cannot_override_new_round(self):
        old=self.invite();respond_to_interview(old.pk,self.candidate,'declined')
        self.invite(details='Second round')
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(reverse('interview_response',args=[old.pk]),{'status':'accepted'}).status_code,409)
        old.refresh_from_db();self.assertEqual(old.status,'declined')

    def test_calendar_has_correct_utc_private_headers_and_safe_unicode_folding(self):
        self.job.title='ሙከራ '*15+'\r\nATTENDEE:untrusted@example.invalid';self.job.save()
        interview=self.invite(details='First line\nEND:VEVENT\nSecond line',location='Addis; floor 2, room 3')
        self.client.force_login(self.candidate)
        response=self.client.get(reverse('interview_calendar',args=[interview.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response['Content-Disposition'])
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        lines=response.content.split(b'\r\n')
        self.assertTrue(all(len(line)<=75 for line in lines))
        body=response.content.decode('utf-8')
        self.assertEqual(sum(line==b'BEGIN:VEVENT' for line in lines),1)
        self.assertFalse(any(line.startswith(b'ATTENDEE:') for line in lines))
        self.assertIn('DTSTART:'+interview.scheduled_at.astimezone(utc_timezone.utc).strftime('%Y%m%dT%H%M%SZ'),body)
        self.assertIn('LOCATION:Addis\\; floor 2\\, room 3',body)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('interview_calendar',args=[interview.pk])).status_code,403)

    def test_interview_mail_does_not_include_meeting_link_or_instructions(self):
        self.invite()
        self.assertEqual(deliver_one(EmailDelivery.objects.get().pk),'sent')
        self.assertIn('interview update',mail.outbox[0].body)
        self.assertNotIn('private-room',mail.outbox[0].body)
        self.assertNotIn('synthetic interview',mail.outbox[0].body)

    def test_interview_post_requires_csrf(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post(reverse('interview_invite',args=[self.application.pk]),{}).status_code,403)
        self.assertFalse(Interview.objects.exists())


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PlacementOutcomeTests(HiringFixture,TestCase):
    def test_hire_creates_one_pending_report_and_no_false_confirmation(self):
        report=self.hire();self.hire()
        self.assertEqual(PlacementReport.objects.count(),1)
        self.assertEqual(report.response,'pending')
        self.assertIsNone(report.responded_at)
        self.assertFalse(PlacementResponseEvent.objects.exists())

    def test_only_applicant_can_confirm_and_repeat_is_idempotent(self):
        report=self.hire();url=reverse('placement_response',args=[report.pk])
        for user in [self.owner,self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(url,{'response':'confirmed'}).status_code,403)
        self.client.force_login(self.candidate)
        self.assertRedirects(self.client.post(url,{'response':'confirmed'}),reverse('application',args=[self.application.pk]))
        self.client.post(url,{'response':'confirmed'})
        report.refresh_from_db();self.assertEqual(report.response,'confirmed')
        self.assertIsNotNone(report.responded_at)
        self.assertEqual(report.events.count(),1)
        self.assertEqual(Notification.objects.filter(kind='placement',recipient=self.owner).count(),1)

    def test_applicant_can_correct_response_without_erasing_history(self):
        report=self.hire()
        respond_to_placement(report.pk,self.candidate,'confirmed')
        respond_to_placement(report.pk,self.candidate,'disputed')
        report.refresh_from_db();self.assertEqual(report.response,'disputed')
        self.assertEqual(list(report.events.values_list('response',flat=True)),['confirmed','disputed'])
        self.client.force_login(self.candidate)
        response=self.client.get(reverse('application',args=[self.application.pk]))
        self.assertEqual(len(response.context['placement_history']),2)

    def test_new_hire_cycle_does_not_inherit_old_confirmation(self):
        old=self.hire();respond_to_placement(old.pk,self.candidate,'confirmed')
        change_application_status(self.application.pk,self.owner,'reviewing')
        new=self.hire();old.refresh_from_db()
        self.assertIsNotNone(old.superseded_at)
        self.assertEqual(old.response,'confirmed')
        self.assertNotEqual(old.pk,new.pk)
        self.assertEqual(new.response,'pending')
        self.client.force_login(self.candidate)
        self.assertEqual(self.client.post(reverse('placement_response',args=[old.pk]),{'response':'confirmed'}).status_code,409)

    def test_missing_or_invalid_response_never_confirms_a_hire(self):
        report=self.hire();self.client.force_login(self.candidate)
        url=reverse('placement_response',args=[report.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        for data in [{},{'response':'pending'},{'response':'forged'}]:
            self.assertEqual(self.client.post(url,data).status_code,400)
        report.refresh_from_db();self.assertEqual(report.response,'pending')

    def test_impact_distinguishes_reported_confirmed_disputed_and_demo_outcomes(self):
        report=self.hire()
        staff=User.objects.create_superuser('impact-outcome-admin','admin@example.com','Outcome-admin-password-44!')
        self.client.force_login(staff)
        response=self.client.get(reverse('impact'))
        self.assertEqual(response.context['placements'],1)
        self.assertEqual(response.context['awaiting_placements'],1)
        self.assertEqual(response.context['applicant_confirmed'],0)
        respond_to_placement(report.pk,self.candidate,'confirmed')
        response=self.client.get(reverse('impact'))
        self.assertEqual(response.context['applicant_confirmed'],1)
        self.assertEqual(response.context['confirmed_people'],1)
        self.assertEqual(response.context['awaiting_placements'],0)
        respond_to_placement(report.pk,self.candidate,'disputed')
        response=self.client.get(reverse('impact'))
        self.assertEqual(response.context['applicant_confirmed'],0)
        self.assertEqual(response.context['disputed_placements'],1)
        self.employer.is_demo=True;self.employer.save()
        response=self.client.get(reverse('impact'))
        for key in ['placements','awaiting_placements','applicant_confirmed','confirmed_people','disputed_placements']:
            self.assertEqual(response.context[key],0,key)

    def test_admin_cannot_impersonate_applicant_confirmation(self):
        report=self.hire()
        admin=User.objects.create_superuser('outcome-review-admin','admin@example.com','Outcome-admin-password-45!')
        self.client.force_login(admin)
        self.assertEqual(self.client.post(reverse('placement_response',args=[report.pk]),{'response':'confirmed'}).status_code,403)
        url=reverse('admin:opportunities_placementreport_change',args=[report.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.post(url,{'response':'confirmed','_save':'Save'}).status_code,403)
        report.refresh_from_db();self.assertEqual(report.response,'pending')

    def test_backfill_preserves_update_timestamp_and_does_not_fabricate_acceptance(self):
        Application.objects.filter(pk=self.application.pk).update(status='hired')
        self.application.refresh_from_db()
        migration=importlib.import_module('opportunities.migrations.0008_backfill_pending_placement_reports')
        migration.backfill(apps,SimpleNamespace(connection=SimpleNamespace(alias='default')))
        migration.backfill(apps,SimpleNamespace(connection=SimpleNamespace(alias='default')))
        report=PlacementReport.objects.get()
        self.assertEqual(report.response,'pending')
        self.assertEqual(report.reported_at,self.application.updated_at)
        self.assertFalse(report.events.exists())

    def test_applicant_deletion_removes_hiring_history_and_queued_messages(self):
        self.invite();report=self.hire();respond_to_placement(report.pk,self.candidate,'confirmed')
        self.candidate.delete()
        for model in [Application,Interview,InterviewEvent,PlacementReport,PlacementResponseEvent,Notification,EmailDelivery]:
            self.assertFalse(model.objects.exists(),model.__name__)
