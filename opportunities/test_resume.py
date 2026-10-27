import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader

from .models import Profile, ResumeDraft
from .resumes import AI_FIELDS, ResumeAIError, generate_resume, resume_pdf


class ResumeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('resume-seeker','private@example.invalid','Test-pass-91!')
        cls.profile=Profile.objects.create(user=cls.user,role='seeker',full_name='ሀና አበበ',skills='Spreadsheet skills',education='School certificate',bio='Community volunteer',location='Addis Ababa')
        cls.other=User.objects.create_user('other-resume-seeker')
        Profile.objects.create(user=cls.other,role='seeker',full_name='Other applicant')
        cls.employer=User.objects.create_user('resume-employer')
        Profile.objects.create(user=cls.employer,role='employer',full_name='Employer')

    def setUp(self):
        self.client.force_login(self.user)
        self.url=reverse('resume_builder')

    def data(self, **changes):
        return {'full_name':'ሀና አበበ','email':'private@example.invalid','phone':'0900000000','location':'Addis Ababa','target_role':'Community assistant','language':'am','summary':'የማህበረሰብ በጎ ፈቃደኛ','education':'የትምህርት ማስረጃ','experience':'Helped organize a school event.','skills':'Spreadsheet skills','expected_version':0,**changes}

    def save(self, **changes):
        return self.client.post(self.url,self.data(**changes))

    def test_profile_prefill_without_writing_or_reading_cv(self):
        response=self.client.get(self.url)
        self.assertEqual(response.context['form'].initial['summary'],self.profile.bio)
        self.assertFalse(ResumeDraft.objects.exists())
        self.assertIn('no-store',response['Cache-Control'])

    def test_private_save_and_download_do_not_replace_cv(self):
        self.assertRedirects(self.save(),self.url)
        draft=ResumeDraft.objects.get()
        self.assertEqual(draft.user,self.user)
        self.profile.refresh_from_db();self.assertFalse(self.profile.cv)
        response=self.client.get(reverse('resume_download'))
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertIn('attachment',response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertIn('no-store',response['Cache-Control'])
        text=''.join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
        self.assertIn('ሀና',text)
        self.assertIn('Spreadsheet skills',text)

    def test_other_seekers_cannot_access_saved_draft(self):
        self.save();self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('resume_download')).status_code,404)
        self.assertNotContains(self.client.get(self.url),'private@example.invalid')

    def test_employer_and_anonymous_permissions(self):
        self.client.force_login(self.employer)
        for name in ['resume_builder','resume_download']:
            self.assertEqual(self.client.get(reverse(name)).status_code,403)
        self.assertEqual(self.client.post(reverse('resume_generate'),self.data(consent='on')).status_code,403)
        self.client.logout();self.assertEqual(self.client.get(self.url).status_code,302)

    def test_csrf_and_post_only_generation(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(self.url,self.data()).status_code,403)
        self.assertEqual(secure.post(reverse('resume_generate'),self.data(consent='on')).status_code,403)
        self.assertEqual(self.client.get(reverse('resume_generate')).status_code,405)

    @override_settings(OPENAI_API_KEY='test-secret-key')
    @patch('opportunities.resume_views.generate_resume')
    def test_consent_required_and_manual_save_never_calls_ai(self, generate):
        response=self.client.post(reverse('resume_generate'),self.data())
        self.assertIn('consent',response.context['form'].errors)
        self.assertFalse(ResumeDraft.objects.exists())
        self.save();generate.assert_not_called()

    @override_settings(OPENAI_API_KEY='test-secret-key')
    @patch('opportunities.resume_views.generate_resume')
    def test_ai_result_editable_and_contact_fields_stay_user_supplied(self, generate):
        generate.return_value={field:'Rewritten '+field for field in AI_FIELDS}
        self.assertRedirects(self.client.post(reverse('resume_generate'),self.data(consent='on')),self.url)
        draft=ResumeDraft.objects.get()
        self.assertEqual(draft.summary,'Rewritten summary')
        self.assertEqual(draft.email,'private@example.invalid')
        self.assertEqual(draft.full_name,'ሀና አበበ')
        self.save(expected_version=1,summary='Applicant correction')
        draft.refresh_from_db();self.assertEqual(draft.summary,'Applicant correction')

    @override_settings(OPENAI_API_KEY='')
    def test_missing_key_is_honest_and_retains_editor_text(self):
        response=self.client.post(reverse('resume_generate'),self.data(consent='on'))
        self.assertContains(response,'AI drafting is not configured.')
        self.assertContains(response,'Community assistant')
        self.assertFalse(ResumeDraft.objects.exists())

    @patch('opportunities.resume_views.generate_resume',side_effect=ResumeAIError('Service unavailable'))
    def test_provider_failure_does_not_overwrite_existing_draft(self, generate):
        self.save()
        response=self.client.post(reverse('resume_generate'),self.data(expected_version=1,consent='on',summary='Unsaved applicant edits'))
        self.assertContains(response,'Unsaved applicant edits')
        self.assertNotEqual(ResumeDraft.objects.get().summary,'Unsaved applicant edits')

    @patch('opportunities.resume_views.generate_resume')
    def test_stale_tab_rejected_before_ai_call(self, generate):
        self.save()
        response=self.client.post(reverse('resume_generate'),self.data(consent='on'))
        self.assertEqual(response.status_code,409)
        generate.assert_not_called()
        self.assertEqual(self.save(summary='Stale edit').status_code,409)
        self.assertEqual(ResumeDraft.objects.get().version,1)

    @patch('opportunities.resume_views.generate_resume')
    def test_delayed_ai_result_cannot_overwrite_newer_save(self, generate):
        self.save()
        def delayed(data):
            ResumeDraft.objects.filter(user=self.user).update(version=2,summary='Newer manual correction')
            return {field:'Late AI text' for field in AI_FIELDS}
        generate.side_effect=delayed
        response=self.client.post(reverse('resume_generate'),self.data(expected_version=1,consent='on'))
        self.assertEqual(response.status_code,409)
        self.assertEqual(ResumeDraft.objects.get().summary,'Newer manual correction')

    def test_client_cannot_assign_draft_to_another_user(self):
        self.save(user=self.other.pk,version=99)
        self.assertEqual(ResumeDraft.objects.get().user,self.user)
        self.assertEqual(ResumeDraft.objects.get().version,1)

    def test_invalid_and_oversized_inputs_rejected(self):
        for changes in [{'summary':'x'*2001},{'language':'invalid'},{'email':'bad-email'},{'full_name':''}]:
            self.assertTrue(self.save(**changes).context['form'].errors)
        self.assertFalse(ResumeDraft.objects.exists())

    def test_html_is_literal_in_pdf_not_active_markup(self):
        self.save(summary='<script>example</script> & literal text')
        text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(self.client.get(reverse('resume_download')).content)).pages)
        self.assertIn('<script>example</script>',text)

    def test_amharic_ui_and_cascade_deletion(self):
        self.client.cookies['django_language']='am'
        self.assertContains(self.client.get(self.url),'የግል ረቂቅዎ')
        self.save();self.user.delete()
        self.assertFalse(ResumeDraft.objects.exists())

    def test_long_sections_export_multiple_pages(self):
        draft=ResumeDraft(**{k:v for k,v in self.data().items() if k!='expected_version'},user=self.user)
        draft.experience=('Community volunteer work.\n'*200)[:6000]
        self.assertGreater(len(PdfReader(io.BytesIO(resume_pdf(draft))).pages),1)


@override_settings(OPENAI_API_KEY='test-only-not-a-real-key',RESUME_AI_MODEL='gpt-4.1-mini')
class AIAdapterTests(TestCase):
    def data(self):
        return {'full_name':'PRIVATE NAME','email':'private@example.invalid','phone':'PRIVATE PHONE','location':'PRIVATE LOCATION','target_role':'Assistant','language':'am',**{field:'Factual text' for field in AI_FIELDS}}

    def response(self, content=None, **changes):
        value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(content if content is not None else {f:'Plain draft' for f in AI_FIELDS})}]}],**changes}
        context=MagicMock();context.__enter__.return_value.read.return_value=json.dumps(value).encode()
        return context

    @patch('opportunities.resumes.urlopen')
    def test_payload_minimizes_personal_data_disables_storage_and_bounds_timeout(self, send):
        send.return_value=self.response()
        self.assertEqual(generate_resume(self.data())['summary'],'Plain draft')
        request=send.call_args.args[0];payload=json.loads(request.data)
        source=json.loads(payload['input'])
        self.assertEqual(set(source),{'target_role','language',*AI_FIELDS})
        self.assertFalse(payload['store'])
        self.assertEqual(send.call_args.kwargs['timeout'],25)
        self.assertIn('Never invent',payload['instructions'])

    @patch('opportunities.resumes.urlopen')
    def test_malformed_refused_oversized_and_extra_fields_rejected(self, send):
        for content in [{'summary':'only summary'}, {**{f:'' for f in AI_FIELDS},'extra':'leak'}, {**{f:'' for f in AI_FIELDS},'summary':'x'*2001}]:
            send.return_value=self.response(content)
            with self.assertRaises(ResumeAIError):generate_resume(self.data())
        send.return_value=self.response(status='incomplete')
        with self.assertRaises(ResumeAIError):generate_resume(self.data())

    @patch('opportunities.resumes.urlopen',side_effect=URLError('secret provider details'))
    def test_errors_sanitized(self, send):
        with self.assertRaises(ResumeAIError) as error:generate_resume(self.data())
        self.assertNotIn('secret',str(error.exception))

    @patch('opportunities.resumes.urlopen')
    def test_empty_facts_do_not_call_provider(self, send):
        data=self.data();data.update({field:'' for field in AI_FIELDS})
        with self.assertRaises(ResumeAIError):generate_resume(data)
        send.assert_not_called()
