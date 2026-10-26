from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Profile, Employer, Opportunity, Application

class PlatformTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seeker = User.objects.create_user('candidate', 'candidate@example.com', 'Strong-test-password-47')
        Profile.objects.create(user=cls.seeker, full_name='Aster Tesfaye', skills='Writing, spreadsheets')
        cls.other = User.objects.create_user('other', password='Strong-test-password-48')
        Profile.objects.create(user=cls.other, full_name='Other seeker')
        cls.owner = User.objects.create_user('employer', password='Strong-test-password-49')
        Profile.objects.create(user=cls.owner, full_name='Employer', role='employer')
        cls.employer = Employer.objects.create(user=cls.owner, name='Test Organization', verified=True)
        cls.job = Opportunity.objects.create(employer=cls.employer, title='Junior Program Assistant', kind='entry', location='Addis Ababa', category='Operations', description='Help coordinate community programs.', requirements='Willingness to learn', compensation='ETB 12,000 / month', deadline=timezone.localdate()+timedelta(days=10), published=True)

    def apply(self):
        self.client.force_login(self.seeker)
        return self.client.post(reverse('apply', args=[self.job.pk]), {'cover_letter': 'I would love to contribute.'})

    def test_public_browsing_and_filtering(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.job.title)
        self.assertContains(response, 'Verified employer')
        for query in [{'q':'community'}, {'location':'Addis'}, {'kind':'entry'}, {'category':'Operations'}]:
            self.assertContains(self.client.get(reverse('home'), query), self.job.title)
        self.assertNotContains(self.client.get(reverse('home'), {'kind':'internship'}), self.job.title)
        self.assertNotContains(self.client.get(reverse('home'), {'q':'nonexistent'}), self.job.title)

    def test_unverified_unpublished_and_expired_jobs_hidden(self):
        for field, value in [('published', False), ('deadline', timezone.localdate()-timedelta(days=1))]:
            original = getattr(self.job, field)
            setattr(self.job, field, value)
            self.job.save()
            self.assertNotContains(self.client.get(reverse('home')), self.job.title)
            self.assertEqual(self.client.get(reverse('detail', args=[self.job.pk])).status_code, 404)
            setattr(self.job, field, original)
            self.job.save()
        self.employer.verified = False
        self.employer.save()
        self.assertEqual(self.client.get(reverse('detail', args=[self.job.pk])).status_code, 404)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.post(reverse('apply', args=[self.job.pk]), {'cover_letter':'test'}).status_code, 404)

    def test_job_seeker_signup(self):
        response = self.client.post(reverse('signup'), {'username':'newperson', 'email':'new@example.com', 'full_name':'New Person', 'role':'seeker', 'password1':'Unique-strong-password-789', 'password2':'Unique-strong-password-789'})
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(Profile.objects.get(user__username='newperson').role, 'seeker')

    def test_employer_signup_requires_organization(self):
        data = {'username':'neworg', 'email':'org@example.com', 'full_name':'Org Owner', 'role':'employer', 'password1':'Unique-strong-password-789', 'password2':'Unique-strong-password-789'}
        response = self.client.post(reverse('signup'), data)
        self.assertContains(response, 'Enter your organization')
        self.assertFalse(User.objects.filter(username='neworg').exists())
        data['organization_name'] = 'New Organization'
        self.assertRedirects(self.client.post(reverse('signup'), data), reverse('dashboard'))
        self.assertFalse(Employer.objects.get(user__username='neworg').verified)

    def test_apply_once_then_track(self):
        self.assertRedirects(self.apply(), reverse('dashboard'))
        self.assertEqual(Application.objects.get().status, 'submitted')
        self.apply()
        self.assertEqual(Application.objects.count(), 1)
        self.assertContains(self.client.get(reverse('dashboard')), self.job.title)
        self.assertContains(self.client.get(reverse('detail', args=[self.job.pk])), 'Application submitted')

    def test_employer_can_review_and_confirm_placement(self):
        self.apply()
        application = Application.objects.get()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('application', args=[application.pk]))
        self.assertContains(response, 'Aster Tesfaye')
        self.assertContains(response, 'candidate@example.com')
        self.assertContains(response, 'Writing, spreadsheets')
        self.assertRedirects(self.client.post(reverse('application', args=[application.pk]), {'status':'hired'}), reverse('application', args=[application.pk]))
        application.refresh_from_db()
        self.assertEqual(application.status, 'hired')
        self.client.force_login(self.seeker)
        self.assertContains(self.client.get(reverse('dashboard')), 'Placement confirmed')

    def test_private_application_permissions(self):
        self.apply()
        application = Application.objects.get()
        url = reverse('application', args=[application.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'status':'hired'}).status_code, 403)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.post(url, {'status':'hired'}).status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status, 'submitted')

    def test_other_employer_cannot_read_or_modify_applications(self):
        self.apply()
        other_owner = User.objects.create_user('another-employer')
        Profile.objects.create(user=other_owner, full_name='Other', role='employer')
        Employer.objects.create(user=other_owner, name='Other organization', verified=True)
        self.client.force_login(other_owner)
        url = reverse('application', args=[Application.objects.get().pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'status':'hired'}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Aster Tesfaye')

    def test_employers_cannot_apply_and_seekers_cannot_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('apply', args=[self.job.pk])).status_code, 403)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse('post_job')).status_code, 404)

    def test_organization_edits_require_reverification(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.post(reverse('employer'), {'name':'Changed organization', 'website':'https://example.com', 'description':'Updated'}), reverse('dashboard'))
        self.employer.refresh_from_db()
        self.assertFalse(self.employer.verified)
        self.assertEqual(self.client.get(reverse('detail', args=[self.job.pk])).status_code, 404)

    def test_posting_cannot_self_publish_or_verify(self):
        self.client.force_login(self.owner)
        data = {'title':'New internship', 'kind':'internship', 'location':'Hawassa', 'category':'Technology', 'description':'Learn with us', 'requirements':'Curiosity', 'compensation':'Stipend', 'deadline':str(timezone.localdate()+timedelta(days=20)), 'published':'on'}
        self.assertRedirects(self.client.post(reverse('post_job'), data), reverse('dashboard'))
        self.assertFalse(Opportunity.objects.get(title='New internship').published)
        data['title'] = 'Expired internship'
        data['deadline'] = str(timezone.localdate()-timedelta(days=1))
        self.assertContains(self.client.post(reverse('post_job'), data), 'Choose today or a future date')
        self.assertFalse(Opportunity.objects.filter(title='Expired internship').exists())

    def test_profile_edit_cannot_change_role(self):
        self.client.force_login(self.seeker)
        self.client.post(reverse('profile'), {'full_name':'Updated Name', 'skills':'Python', 'role':'employer'})
        self.seeker.profile.refresh_from_db()
        self.assertEqual(self.seeker.profile.role, 'seeker')
        self.assertEqual(self.seeker.profile.skills, 'Python')

    def test_anonymous_cannot_apply_or_access_dashboard(self):
        self.assertEqual(self.client.get(reverse('apply', args=[self.job.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        self.assertFalse(Application.objects.exists())

    def test_invalid_application_status_is_rejected(self):
        self.apply()
        self.client.force_login(self.owner)
        application = Application.objects.get()
        response = self.client.post(reverse('application', args=[application.pk]), {'status':'invalid'})
        self.assertContains(response, 'Select a valid choice')
        application.refresh_from_db()
        self.assertEqual(application.status, 'submitted')

    def test_application_message_is_escaped(self):
        self.client.force_login(self.seeker)
        self.client.post(reverse('apply', args=[self.job.pk]), {'cover_letter':'<script>alert(1)</script>'})
        response = self.client.get(reverse('application', args=[Application.objects.get().pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>')

    def test_production_excludes_demo_opportunities(self):
        self.employer.is_demo = True
        self.employer.save()
        with override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False):
            self.assertNotContains(self.client.get(reverse('home')), self.job.title)
            self.assertEqual(self.client.get(reverse('detail', args=[self.job.pk])).status_code, 404)

    def test_page_templates_render(self):
        self.assertEqual(self.client.get(reverse('about')).status_code, 200)
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)
        self.assertEqual(self.client.get(reverse('signup')).status_code, 200)
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.client.force_login(self.owner)
        for name in ['dashboard','employer','post_job']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_impact_is_staff_only_and_excludes_demo_data(self):
        self.apply()
        application = Application.objects.get()
        application.status = "hired"
        application.save()
        self.assertEqual(self.client.get(reverse('impact')).status_code, 302)
        self.seeker.is_staff = True
        self.seeker.save()
        response = self.client.get(reverse('impact'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['placements'], 1)
        self.assertEqual(response.context['people_placed'], 1)
        self.employer.is_demo = True
        self.employer.save()
        response = self.client.get(reverse('impact'))
        self.assertEqual(response.context['placements'], 0)
        self.assertEqual(response.context['application_count'], 0)

    def test_logout_requires_post(self):
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('logout')), reverse('home'))

    def test_csrf_is_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.seeker)
        self.assertEqual(client.post(reverse('apply', args=[self.job.pk]), {'cover_letter':'Missing CSRF'}).status_code, 403)
        self.assertFalse(Application.objects.exists())

    def test_demo_seed_is_repeatable_and_does_not_reset_edits(self):
        from django.core.management import call_command
        from io import StringIO
        with override_settings(DEBUG=True):
            call_command('seed_demo', stdout=StringIO())
            job = Opportunity.objects.filter(employer__is_demo=True).first()
            job.description = 'An intentional local edit'
            job.save()
            call_command('seed_demo', stdout=StringIO())
            self.assertEqual(Opportunity.objects.filter(employer__is_demo=True).count(), 6)
            job.refresh_from_db()
            self.assertEqual(job.description, 'An intentional local edit')
