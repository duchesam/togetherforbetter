from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from .models import Application, Employer, Opportunity, Profile
from .test_hiring import HiringFixture


class ApplicantWorkspaceTests(HiringFixture, TestCase):
    def setUp(self):
        self.client.force_login(self.owner)
        self.url=reverse('employer_applicants')
        self.foreign_user=User.objects.create_user('foreign-employer')
        Profile.objects.create(user=self.foreign_user,role='employer',full_name='Foreign employer')
        self.foreign_org=Employer.objects.create(user=self.foreign_user,name='Other organization')
        self.foreign_job=Opportunity.objects.create(employer=self.foreign_org,title='Private foreign listing',kind='entry',location='Hawassa',category='Community',description='Private',requirements='Private',compensation='Stipend',deadline=self.job.deadline)
        Application.objects.create(applicant=self.other,opportunity=self.foreign_job,cover_letter='Private foreign application',status='hired')

    def test_owner_rows_counts_and_options_exclude_foreign_data(self):
        response=self.client.get(self.url)
        self.assertEqual(response.context['total'],1)
        self.assertEqual([a.pk for a in response.context['page']],[self.application.pk])
        self.assertEqual(dict(response.context['counts'])['Hired (employer reported)'],0)
        self.assertNotContains(response,self.foreign_job.title)
        self.assertNotContains(response,self.other.username)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(list(response.context['form'].fields['listing'].queryset),[self.job])

    def test_cannot_use_foreign_listing_as_filter(self):
        for listing in [self.foreign_job.pk,999999,'invalid']:
            response=self.client.get(self.url,{'listing':listing})
            self.assertEqual(response.status_code,400)
            self.assertIn('listing',response.context['form'].errors)
            self.assertNotIn('page',response.context)
            self.assertNotContains(response,self.foreign_job.title,status_code=400)

    def test_seeker_staff_without_employer_profile_and_anonymous_denied(self):
        admin=User.objects.create_superuser('workspace-admin','admin@example.invalid','Password-9!')
        for user in [self.candidate,admin]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)

    def test_search_name_username_and_title_status_intersection(self):
        for query in [self.candidate.profile.full_name,self.candidate.username,self.job.title]:
            self.assertEqual(len(self.client.get(self.url,{'q':query}).context['page']),1)
        response=self.client.get(self.url,{'status':'hired','q':self.job.title})
        self.assertEqual(len(response.context['page']),0)
        self.assertEqual(response.context['total'],1)
        self.assertEqual(len(self.client.get(self.url,{'q':self.other.username}).context['page']),0)

    def test_listing_filter_includes_closed_unpublished_listings(self):
        Opportunity.objects.filter(pk=self.job.pk).update(published=False)
        response=self.client.get(self.url,{'listing':self.job.pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['page']),1)

    def test_upcoming_and_empty_filters_preserve_interview_state(self):
        invitation=self.invite()
        response=self.client.get(self.url,{'upcoming':'on','listing':self.job.pk})
        self.assertEqual(response.context['page'][0].interview_at,invitation.scheduled_at)
        self.assertContains(response,'Awaiting applicant response')
        Application.objects.filter(pk=self.application.pk).update(status='withdrawn')
        self.assertEqual(len(self.client.get(self.url,{'upcoming':'on'}).context['page']),0)
        self.assertEqual(len(self.client.get(self.url,{'status':'withdrawn'}).context['page']),1)

    def test_pagination_stable_and_retains_search_listing_status(self):
        for index in range(13):
            user=User.objects.create_user(f'pagination-candidate-{index}')
            Profile.objects.create(user=user,role='seeker',full_name=f'Pagination person {index}')
            Application.objects.create(applicant=user,opportunity=self.job,cover_letter='Test',status='reviewing')
        filters={'q':'Pagination','listing':str(self.job.pk),'status':'reviewing'}
        first=self.client.get(self.url,filters)
        second=self.client.get(self.url,dict(filters,page='2'))
        self.assertEqual(len(first.context['page']),12)
        self.assertEqual(len(second.context['page']),1)
        self.assertFalse(set(a.pk for a in first.context['page']) & set(a.pk for a in second.context['page']))
        self.assertContains(first,'q=Pagination&amp;listing=')
        self.assertContains(first,'&amp;status=reviewing&amp;page=2')

    def test_localization_dashboard_and_listing_entry_points(self):
        self.client.cookies['django_language']='am'
        self.assertContains(self.client.get(self.url),'አመልካቾችን ያስተዳድሩ')
        self.assertContains(self.client.get(reverse('dashboard')),self.url)
        self.assertContains(self.client.get(reverse('listing_manage',args=[self.job.pk])),f'{self.url}?listing={self.job.pk}')

    def test_invalid_filters_and_posts_do_not_mutate(self):
        for data in [{'status':'bad'},{'q':'x'*101}]:
            self.assertEqual(self.client.get(self.url,data).status_code,400)
        self.assertEqual(self.client.post(self.url,{'status':'hired'}).status_code,405)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status,'reviewing')

    def test_cross_employer_rows_remain_separate(self):
        self.client.force_login(self.foreign_user)
        response=self.client.get(self.url)
        self.assertEqual(response.context['total'],1)
        self.assertContains(response,self.foreign_job.title)
        self.assertNotContains(response,self.job.title)
        self.assertNotContains(response,self.candidate.username)
