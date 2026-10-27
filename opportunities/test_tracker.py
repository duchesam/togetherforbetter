from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Application, Interview, Opportunity
from .test_hiring import HiringFixture


class TrackerTests(HiringFixture, TestCase):
    def setUp(self):
        self.client.force_login(self.candidate)
        self.url=reverse('application_tracker')

    def test_private_owner_only_rows_and_counts(self):
        other=Application.objects.create(applicant=self.other,opportunity=self.job,cover_letter='Secret',status='hired')
        response=self.client.get(self.url)
        self.assertEqual(response.context['total'],1)
        self.assertEqual([a.pk for a in response.context['page']],[self.application.pk])
        self.assertEqual(dict(response.context['counts'])['Hired (employer reported)'],0)
        self.assertNotContains(response,'Secret')
        self.assertIn('no-store',response['Cache-Control'])

    def test_employer_staff_without_seeker_profile_and_anonymous_denied(self):
        for user in [self.owner]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)

    def test_search_title_organization_and_status(self):
        for query in ['Community assistant','Hiring test organization']:
            self.assertEqual(len(self.client.get(self.url,{'q':query}).context['page']),1)
        self.assertEqual(len(self.client.get(self.url,{'status':'hired'}).context['page']),0)
        self.assertEqual(len(self.client.get(self.url,{'status':'reviewing','q':'missing'}).context['page']),0)
        self.assertEqual(self.client.get(self.url,{'q':'missing'}).context['total'],1)

    def test_invalid_filters_have_errors_no_results(self):
        for data in [{'status':'not-a-status'},{'q':'x'*101}]:
            response=self.client.get(self.url,data)
            self.assertEqual(response.status_code,400)
            self.assertTrue(response.context['form'].errors)
            self.assertNotIn('page',response.context)
        self.assertEqual(self.client.post(self.url).status_code,405)

    def test_upcoming_shows_invitation_state_without_attendance_claim(self):
        invitation=self.invite()
        response=self.client.get(self.url,{'upcoming':'on'})
        self.assertEqual(response.context['page'][0].interview_at,invitation.scheduled_at)
        self.assertContains(response,'Awaiting applicant response')
        self.assertContains(response,'An invitation does not confirm attendance.')

    def test_excludes_past_cancelled_and_closed_application_interviews(self):
        invitation=self.invite()
        for changes in [{'status':'cancelled'},{'status':'declined'},{'status':'replaced'},{'status':'pending','scheduled_at':timezone.now()-timedelta(minutes=1)}]:
            Interview.objects.filter(pk=invitation.pk).update(**changes)
            self.assertEqual(len(self.client.get(self.url,{'upcoming':'on'}).context['page']),0)
        Interview.objects.filter(pk=invitation.pk).update(status='accepted',scheduled_at=timezone.now()+timedelta(days=1))
        for status in ['hired','declined','withdrawn']:
            Application.objects.filter(pk=self.application.pk).update(status=status)
            self.assertEqual(len(self.client.get(self.url,{'upcoming':'on'}).context['page']),0)

    def test_all_statuses_filter_including_withdrawn(self):
        for status in Application.Status.values:
            Application.objects.filter(pk=self.application.pk).update(status=status)
            response=self.client.get(self.url,{'status':status})
            self.assertEqual(len(response.context['page']),1)
            self.assertEqual(response.context['total'],1)

    def test_pagination_preserves_filters_and_stable_order(self):
        for index in range(14):
            job=Opportunity.objects.create(employer=self.employer,title=f'Sample match {index}',kind='entry',location='Addis Ababa',category='Community',description='Test',requirements='Test',compensation='Stipend',deadline=self.job.deadline)
            Application.objects.create(applicant=self.candidate,opportunity=job,cover_letter='Test',status='reviewing')
        first=self.client.get(self.url,{'q':'Sample match','status':'reviewing'})
        second=self.client.get(self.url,{'q':'Sample match','status':'reviewing','page':'2'})
        self.assertEqual(len(first.context['page']),12)
        self.assertEqual(len(second.context['page']),2)
        self.assertFalse(set(a.pk for a in first.context['page']) & set(a.pk for a in second.context['page']))
        self.assertContains(first,'q=Sample+match&amp;status=reviewing&amp;page=2')
        self.assertEqual(self.client.get(self.url,{'page':'invalid'}).status_code,200)

    def test_amharic_empty_state_and_dashboard_link(self):
        self.client.cookies['django_language']='am'
        self.assertContains(self.client.get(self.url),'የማመልከቻዎቼ መከታተያ')
        self.assertContains(self.client.get(reverse('dashboard')),self.url)
        self.assertEqual(self.client.get(self.url,{'upcoming':'on'}).status_code,200)

    def test_upcoming_order_uses_interview_time(self):
        later=self.invite()
        job=Opportunity.objects.create(employer=self.employer,title='Earlier interview role',kind='entry',location='Hawassa',category='Community',description='Test',requirements='Test',compensation='Stipend',deadline=self.job.deadline)
        earlier=Application.objects.create(applicant=self.candidate,opportunity=job,cover_letter='Test')
        Interview.objects.create(application=earlier,scheduled_at=timezone.now()+timedelta(days=1),duration_minutes=30,mode='phone',location='Demo instructions')
        response=self.client.get(self.url,{'upcoming':'on'})
        self.assertEqual([a.pk for a in response.context['page']],[earlier.pk,self.application.pk])
