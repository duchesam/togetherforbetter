from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import re

import polib
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.contrib.auth.forms import AuthenticationForm
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format

from .forms import OpportunityForm, SignupForm
from .models import Employer, Opportunity, OpportunityReport, Profile, RequestBucket


class LanguageTests(TestCase):
    def test_authentication_guidance_has_amharic_translations(self):
        with translation.override('am'):
            form = SignupForm()
            help_text = str(form.fields['password1'].help_text)
            self.assertNotIn('Your password', help_text)
            self.assertIn('8', help_text)
            self.assertIn('የይለፍ', help_text)
            self.assertIn('ትክክለኛ', str(AuthenticationForm.error_messages['invalid_login']))

    def test_dates_remain_gregorian_with_amharic_months(self):
        with translation.override('am'):
            self.assertEqual(date_format(date(2026,10,26),'DATE_FORMAT'),'26 ኦክቶበር 2026')

    def test_switch_persists_and_preserves_search(self):
        response = self.client.post(reverse('set_language'), {'language':'am', 'next':'/?q=ስልጠና&kind=internship'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, 'am')
        self.assertIn('kind=internship', response.url)
        self.assertContains(self.client.get(reverse('home')), 'ዕድሎችን ያግኙ')
        self.assertContains(self.client.get(reverse('home')), '<html lang="am">')
        self.client.post(reverse('set_language'), {'language':'en', 'next':'/'})
        self.assertContains(self.client.get(reverse('home')), 'Find opportunities')
        self.assertContains(self.client.get(reverse('home')), '<html lang="en">')

    def test_switch_rejects_external_redirects_and_requires_csrf(self):
        response = self.client.post(reverse('set_language'), {'language':'am', 'next':'https://external.invalid/'})
        self.assertNotIn('external.invalid', response.url)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('set_language'), {'language':'am'}).status_code, 403)

    def test_forms_and_validation_translate_without_changing_values(self):
        with translation.override('am'):
            form = SignupForm()
            self.assertEqual(str(form.fields['full_name'].label), 'ሙሉ ስም')
            self.assertIn(('seeker','ሥራ ፈላጊ'), [(value,str(label)) for value,label in form.fields['role'].choices])
            form = OpportunityForm({'deadline':str(timezone.localdate()-timedelta(days=1))})
            self.assertFalse(form.is_valid())
            self.assertIn('የዛሬን', str(form.errors['deadline']))
            self.assertIn('ጎርጎርዮሳዊ',str(form.fields['deadline'].label))

    def test_amharic_public_and_recovery_pages_render(self):
        for name in ['home','about','signup','login','password_reset','password_reset_done','password_reset_complete']:
            response = self.client.get(reverse(name), HTTP_ACCEPT_LANGUAGE='am')
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, '<html lang="am">')
            self.assertNotContains(response, '{%')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_recovery_email_uses_selected_language(self):
        User.objects.create_user('am-recovery','am@example.com','Private-test-password-23!')
        self.client.post(reverse('password_reset'), {'email':'am@example.com'}, HTTP_ACCEPT_LANGUAGE='am')
        self.assertEqual(len(mail.outbox),1)
        self.assertIn('የይለፍ',mail.outbox[0].subject)
        self.assertIn('መለያዎ',mail.outbox[0].body)
        self.assertIn('/password/reset/',mail.outbox[0].body)

    def test_translation_catalog_placeholders_and_compilation(self):
        catalog = polib.pofile(str(settings.BASE_DIR/'locale/am/LC_MESSAGES/django.po'))
        self.assertGreater(len(catalog),300)
        placeholder = re.compile(r'%\((\w+)\)[sd]')
        for entry in catalog:
            self.assertTrue(entry.translated(), entry.msgid)
            variants = entry.msgstr_plural.values() if entry.msgid_plural else [entry.msgstr]
            for text in variants:
                self.assertEqual(set(placeholder.findall(entry.msgid)),set(placeholder.findall(text)),entry.msgid)
        output = StringIO()
        call_command('compile_translations', stdout=output)
        self.assertIn('Compiled',output.getvalue())


@override_settings(REQUEST_LIMITS={'login':(2,600),'password_reset':(2,900),'signup':(2,3600)})
class RequestLimitTests(TestCase):
    def test_limit_is_shared_and_rejects_spoofed_forwarding(self):
        for index in range(2):
            response = self.client.post(reverse('login'), {'username':'unknown','password':'invalid'}, HTTP_X_FORWARDED_FOR=f'192.0.2.{index}')
            self.assertEqual(response.status_code,200)
        response = Client().post(reverse('login'), {'username':'unknown','password':'invalid'}, HTTP_X_FORWARDED_FOR='192.0.2.99')
        self.assertEqual(response.status_code,429)
        self.assertGreater(int(response['Retry-After']),0)
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(RequestBucket.objects.get().attempts,2)
        key = RequestBucket.objects.get().key
        self.assertRegex(key,r'^[0-9a-f]{64}$')
        self.assertNotIn('127.0.0.1',key)

    def test_different_direct_clients_have_independent_buckets(self):
        for _ in range(2):
            self.client.post(reverse('login'), {}, REMOTE_ADDR='192.0.2.1')
        self.assertEqual(self.client.post(reverse('login'), {}, REMOTE_ADDR='192.0.2.1').status_code,429)
        self.assertEqual(self.client.post(reverse('login'), {}, REMOTE_ADDR='192.0.2.2').status_code,200)

    def test_window_expiry_and_counter_cleanup(self):
        now = timezone.now()
        with patch('opportunities.middleware.django_timezone.now',return_value=now):
            for _ in range(2): self.client.post(reverse('login'),{})
            self.assertEqual(self.client.post(reverse('login'),{}).status_code,429)
        with patch('opportunities.middleware.django_timezone.now',return_value=now+timedelta(minutes=11)):
            self.assertEqual(self.client.post(reverse('login'),{}).status_code,200)
            call_command('prune_throttles',stdout=StringIO())
        self.assertEqual(RequestBucket.objects.count(),1)

    def test_reads_are_not_throttled_and_language_is_retained_on_429(self):
        for _ in range(3): self.assertEqual(self.client.get(reverse('login')).status_code,200)
        self.assertFalse(RequestBucket.objects.exists())
        for _ in range(2): self.client.post(reverse('login'),{})
        response = self.client.post(reverse('login'),{}, HTTP_ACCEPT_LANGUAGE='am')
        self.assertEqual(response.status_code,429)
        self.assertContains(response,'በጣም ብዙ',status_code=429)

    def test_reset_and_signup_limits_apply_before_account_operations(self):
        for name in ['signup','password_reset']:
            for _ in range(2): self.assertEqual(self.client.post(reverse(name),{}).status_code,200)
            self.assertEqual(self.client.post(reverse(name),{}).status_code,429)
        self.assertFalse(User.objects.exists())


class ReportModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter = User.objects.create_user('reporter')
        Profile.objects.create(user=cls.reporter,full_name='Reporter')
        cls.owner = User.objects.create_user('reported-owner')
        Profile.objects.create(user=cls.owner,full_name='Owner',role='employer')
        cls.employer = Employer.objects.create(user=cls.owner,name='Organization',verified=True)
        cls.job = Opportunity.objects.create(employer=cls.employer,title='Community internship',kind='internship',location='Addis Ababa',category='Community',description='A listing',requirements='Curiosity',compensation='Stipend',deadline=timezone.localdate()+timedelta(days=10),published=True)
        cls.moderator = User.objects.create_superuser('moderator','moderator@example.com','Temporary-admin-password-82!')

    def report(self):
        self.client.force_login(self.reporter)
        return self.client.post(reverse('report_job',args=[self.job.pk]),{'reason':'fee','details':'The contact asked me to pay a fee.'})

    def test_report_is_private_and_does_not_auto_hide_listing(self):
        response = self.report()
        report = OpportunityReport.objects.get()
        self.assertRedirects(response,reverse('report_detail',args=[report.pk]))
        self.job.refresh_from_db()
        self.assertTrue(self.job.published)
        self.assertContains(self.client.get(reverse('dashboard')),'Asked to pay a fee')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('report_detail',args=[report.pk])).status_code,404)
        self.assertNotContains(self.client.get(reverse('dashboard')),'The contact asked me')

    def test_duplicates_return_existing_report(self):
        self.report()
        self.report()
        self.assertEqual(OpportunityReport.objects.count(),1)

    def test_anonymous_and_listing_owner_cannot_report(self):
        url=reverse('report_job',args=[self.job.pk])
        self.assertEqual(self.client.get(url).status_code,302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url,{'reason':'other','details':'Test'}).status_code,403)
        self.assertFalse(OpportunityReport.objects.exists())

    def test_invalid_reports_and_hidden_listings_are_rejected(self):
        self.client.force_login(self.reporter)
        url=reverse('report_job',args=[self.job.pk])
        for data in [{'reason':'invalid','details':'Test'}, {'reason':'fee','details':'x'*2001}]:
            self.assertEqual(self.client.post(url,data).status_code,200)
        self.assertFalse(OpportunityReport.objects.exists())
        self.job.published=False;self.job.save()
        self.assertEqual(self.client.post(url,{'reason':'fee','details':'Test'}).status_code,404)

    def test_moderator_can_hide_listing_with_audited_action(self):
        self.report()
        report=OpportunityReport.objects.get()
        self.client.force_login(self.moderator)
        response=self.client.post(reverse('admin:opportunities_opportunityreport_changelist'),{'action':'hide_reported_listings','_selected_action':[report.pk]})
        self.assertEqual(response.status_code,302)
        self.job.refresh_from_db();report.refresh_from_db()
        self.assertFalse(self.job.published)
        self.assertEqual(report.status,'investigating')
        self.assertEqual(report.reviewed_by,self.moderator)
        self.assertIsNotNone(report.reviewed_at)
        self.assertEqual(LogEntry.objects.filter(user=self.moderator).count(),2)
        self.assertEqual(self.client.get(reverse('detail',args=[self.job.pk])).status_code,404)

    def test_report_only_permission_cannot_hide_opportunity(self):
        self.report()
        report=OpportunityReport.objects.get()
        reviewer=User.objects.create_user('restricted-reviewer',is_staff=True)
        reviewer.user_permissions.add(Permission.objects.get(codename='change_opportunityreport'))
        self.client.force_login(reviewer)
        response=self.client.post(reverse('admin:opportunities_opportunityreport_changelist'),{'action':'hide_reported_listings','_selected_action':[report.pk]})
        self.assertEqual(response.status_code,403)
        self.job.refresh_from_db();self.assertTrue(self.job.published)

    def test_moderator_notes_are_never_shown_to_reporter(self):
        self.report()
        report=OpportunityReport.objects.get()
        self.client.force_login(self.moderator)
        response=self.client.post(reverse('admin:opportunities_opportunityreport_change',args=[report.pk]),{'status':'resolved','moderator_notes':'INTERNAL PRIVATE NOTE','_save':'Save'})
        self.assertEqual(response.status_code,302)
        report.refresh_from_db()
        self.assertEqual(report.reviewed_by,self.moderator)
        self.client.force_login(self.reporter)
        response=self.client.get(reverse('report_detail',args=[report.pk]))
        self.assertContains(response,'Resolved')
        self.assertNotContains(response,'INTERNAL PRIVATE NOTE')

    def test_report_is_retained_without_identity_after_account_deletion(self):
        self.report()
        self.reporter.delete()
        self.assertIsNone(OpportunityReport.objects.get().reporter)
