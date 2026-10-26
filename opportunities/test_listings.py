from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client,TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Application,Employer,Opportunity,OpportunityChange,Profile,SavedOpportunity


class ListingFixture:
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user('listing-owner','owner@example.com','Owner-listing-password-71!')
        cls.seeker=User.objects.create_user('listing-seeker','seeker@example.com','Seeker-listing-password-72!')
        cls.other=User.objects.create_user('listing-other','other@example.com','Other-listing-password-73!')
        for user,role in [(cls.owner,'employer'),(cls.seeker,'seeker'),(cls.other,'seeker')]:
            Profile.objects.create(user=user,full_name=user.username,role=role,verified_email=user.email,email_verified_at=timezone.now())
        cls.employer=Employer.objects.create(user=cls.owner,name='Listing test organization',verified=True)
        cls.job=Opportunity.objects.create(employer=cls.employer,title='Original public title',kind='internship',location='Addis Ababa',category='Community',description='Original description',requirements='Curiosity',compensation='Stipend',deadline=timezone.localdate()+timedelta(days=30),published=True)

    def data(self,**changes):
        return {field:getattr(self.job,field) for field in ['title','kind','location','category','description','requirements','compensation','deadline']} | {'expected_version':self.job.version} | changes

    def action(self,name,**data):
        self.client.force_login(self.owner)
        return self.client.post(reverse(name,args=[self.job.pk]),{'expected_version':self.job.version,**data})


class ListingManagementTests(ListingFixture,TestCase):
    def test_edit_withdraws_publication_and_records_changed_fields(self):
        self.client.force_login(self.owner)
        response=self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(title='Revised title',published='on',employer=self.other.pk))
        self.assertRedirects(response,reverse('listing_manage',args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.title,'Revised title')
        self.assertFalse(self.job.published)
        self.assertEqual(self.job.employer,self.employer)
        self.assertEqual(self.job.version,2)
        self.assertEqual(OpportunityChange.objects.get().fields_changed,['title'])
        self.assertEqual(self.client.get(reverse('detail',args=[self.job.pk])).status_code,404)

    def test_no_op_edit_does_not_unpublish_or_add_history(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data())
        self.job.refresh_from_db()
        self.assertTrue(self.job.published)
        self.assertEqual(self.job.version,1)
        self.assertFalse(OpportunityChange.objects.exists())

    def test_foreign_users_cannot_view_or_edit_manage_or_close(self):
        for user in [self.seeker,self.other]:
            self.client.force_login(user)
            for name in ['listing_manage','listing_edit']:
                self.assertEqual(self.client.get(reverse(name,args=[self.job.pk])).status_code,404)
            self.assertEqual(self.client.post(reverse('listing_close',args=[self.job.pk]),{'expected_version':1}).status_code,404)
        self.job.refresh_from_db();self.assertTrue(self.job.published)

    def test_close_preserves_applications_blocks_new_ones_and_is_idempotent(self):
        application=Application.objects.create(applicant=self.seeker,opportunity=self.job,cover_letter='Existing application')
        from .hiring import invite_to_interview
        import uuid
        interview=invite_to_interview(application.pk,self.owner,{'request_key':uuid.uuid4(),'scheduled_at':timezone.now()+timedelta(days=2),'duration_minutes':30,'mode':'phone','location':'','meeting_url':'','details':'We will arrange a call by email.'})
        self.action('listing_close');self.action('listing_close')
        self.job.refresh_from_db();self.assertIsNotNone(self.job.closed_at)
        self.assertFalse(self.job.published)
        self.assertEqual(self.job.changes.count(),1)
        self.assertTrue(Application.objects.filter(pk=application.pk).exists())
        interview.refresh_from_db();self.assertEqual(interview.status,'pending')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('apply',args=[self.job.pk]),{'cover_letter':'New application'}).status_code,404)
        self.assertEqual(Application.objects.count(),1)

    def test_reopening_requires_review_and_can_be_repeated_safely(self):
        self.action('listing_close');self.job.refresh_from_db()
        self.action('listing_reopen');self.job.refresh_from_db()
        self.assertIsNone(self.job.closed_at);self.assertFalse(self.job.published)
        version=self.job.version
        self.action('listing_reopen')
        self.job.refresh_from_db();self.assertEqual(self.job.version,version)
        self.assertEqual(list(self.job.changes.order_by('pk').values_list('action',flat=True)),['closed','reopened'])

    def test_expired_listing_must_have_deadline_updated_before_reopening(self):
        self.action('listing_close')
        Opportunity.objects.filter(pk=self.job.pk).update(deadline=timezone.localdate()-timedelta(days=1))
        self.job.refresh_from_db()
        self.assertRedirects(self.action('listing_reopen'),reverse('listing_manage',args=[self.job.pk]))
        self.job.refresh_from_db();self.assertIsNotNone(self.job.closed_at)
        self.client.force_login(self.owner)
        self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(deadline=timezone.localdate()+timedelta(days=10)))
        self.job.refresh_from_db();self.assertIsNotNone(self.job.closed_at)
        self.action('listing_reopen');self.job.refresh_from_db();self.assertIsNone(self.job.closed_at)
        self.assertFalse(self.job.published)

    def test_stale_edit_cannot_overwrite_a_newer_change(self):
        self.client.force_login(self.owner)
        stale=self.data(title='Old browser edit')
        self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(title='Current revision'))
        self.assertEqual(self.client.post(reverse('listing_edit',args=[self.job.pk]),stale).status_code,409)
        self.job.refresh_from_db();self.assertEqual(self.job.title,'Current revision')
        self.assertEqual(self.job.changes.count(),1)

    def test_validation_failure_preserves_current_live_listing(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(title='')).status_code,200)
        self.job.refresh_from_db();self.assertTrue(self.job.published)
        self.assertEqual(self.job.title,'Original public title')

    def test_unverified_email_can_close_but_cannot_edit_or_reopen(self):
        Profile.objects.filter(user=self.owner).update(email_verification_required=True,verified_email='',email_verified_at=None)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('listing_edit',args=[self.job.pk])),reverse('account_settings'))
        self.action('listing_close');self.job.refresh_from_db();self.assertIsNotNone(self.job.closed_at)
        self.action('listing_reopen');self.job.refresh_from_db();self.assertIsNotNone(self.job.closed_at)

    def test_mutation_requires_post_and_csrf(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('listing_close',args=[self.job.pk])).status_code,405)
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post(reverse('listing_close',args=[self.job.pk]),{'expected_version':1}).status_code,403)
        self.assertEqual(self.action('listing_close',expected_version='bad').status_code,400)
        self.job.refresh_from_db();self.assertIsNone(self.job.closed_at)

    def test_public_and_apply_paths_reject_closed_even_if_published_is_set(self):
        self.action('listing_close')
        Opportunity.objects.filter(pk=self.job.pk).update(published=True)
        self.assertNotContains(self.client.get(reverse('home')),'Original public title')
        self.assertEqual(self.client.get(reverse('detail',args=[self.job.pk])).status_code,404)

    def test_application_rechecks_listing_after_validation_before_commit(self):
        self.client.force_login(self.seeker)
        from .forms import ApplicationForm
        original=ApplicationForm.is_valid
        def close_during_validation(form):
            valid=original(form)
            Opportunity.objects.filter(pk=self.job.pk).update(closed_at=timezone.now(),published=False)
            return valid
        with patch('opportunities.views.ApplicationForm.is_valid',close_during_validation):
            response=self.client.post(reverse('apply',args=[self.job.pk]),{'cover_letter':'New application'})
        self.assertEqual(response.status_code,404)
        self.assertFalse(Application.objects.exists())

    def test_admin_approval_respects_closed_state_and_stale_versions(self):
        admin=User.objects.create_superuser('listing-admin','admin@example.com','Admin-listing-password-74!')
        self.client.force_login(admin)
        url=reverse('admin:opportunities_opportunity_change',args=[self.job.pk])
        self.assertContains(self.client.get(url),'name="expected_version"')
        self.action('listing_close');self.job.refresh_from_db()
        self.client.force_login(admin)
        data=self.data(employer=self.employer.pk,published='on',is_demo='',_save='Save')
        response=self.client.post(url,data)
        self.assertContains(response,'must reopen')
        self.job.refresh_from_db();self.assertFalse(self.job.published)
        self.action('listing_reopen');self.job.refresh_from_db()
        self.client.force_login(admin)
        stale={**data,'expected_version':1}
        self.assertContains(self.client.post(url,stale),'changed while you were working')
        data=self.data(employer=self.employer.pk,published='on',_save='Save')
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.job.refresh_from_db();self.assertTrue(self.job.is_open)


class SavedOpportunityTests(ListingFixture,TestCase):
    def save(self):
        self.client.force_login(self.seeker)
        return self.client.post(reverse('save_opportunity',args=[self.job.pk]))

    def test_save_is_private_idempotent_and_does_not_apply(self):
        self.save();self.save()
        self.assertEqual(SavedOpportunity.objects.count(),1)
        self.assertFalse(Application.objects.exists())
        self.assertContains(self.client.get(reverse('saved_opportunities')),'Original public title')
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('saved_opportunities')),'Original public title')

    def test_employers_and_anonymous_users_cannot_save(self):
        url=reverse('save_opportunity',args=[self.job.pk])
        self.assertEqual(self.client.post(url).status_code,302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url).status_code,403)
        self.assertEqual(self.client.get(reverse('saved_opportunities')).status_code,403)
        self.assertFalse(SavedOpportunity.objects.exists())

    def test_save_requires_post_csrf_and_a_current_public_listing(self):
        self.client.force_login(self.seeker)
        url=reverse('save_opportunity',args=[self.job.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        client=Client(enforce_csrf_checks=True);client.force_login(self.seeker)
        self.assertEqual(client.post(url).status_code,403)
        self.action('listing_close');self.client.force_login(self.seeker)
        self.assertEqual(self.client.post(url).status_code,404)

    def test_unpublished_edits_are_not_leaked_to_prior_savers(self):
        self.save()
        self.client.force_login(self.owner)
        self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(title='PRIVATE UNREVIEWED TITLE',description='PRIVATE UNREVIEWED TEXT',location='PRIVATE LOCATION'))
        self.client.force_login(self.seeker)
        response=self.client.get(reverse('saved_opportunities'))
        self.assertContains(response,'Original public title')
        self.assertContains(response,'Currently unavailable')
        for value in ['PRIVATE UNREVIEWED TITLE','PRIVATE UNREVIEWED TEXT','PRIVATE LOCATION']:
            self.assertNotContains(response,value)

    def test_remove_is_owner_only_and_post_only(self):
        self.save();save=SavedOpportunity.objects.get()
        url=reverse('remove_saved',args=[save.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code,404)
        self.assertTrue(SavedOpportunity.objects.exists())
        self.client.force_login(self.seeker)
        self.assertRedirects(self.client.post(url),reverse('saved_opportunities'))
        self.assertFalse(SavedOpportunity.objects.exists())

    def test_closed_or_expired_saved_entries_remain_without_public_links(self):
        self.save();self.action('listing_close');self.client.force_login(self.seeker)
        response=self.client.get(reverse('saved_opportunities'))
        self.assertContains(response,'Original public title')
        self.assertNotContains(response,'href="'+reverse('detail',args=[self.job.pk])+'"')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertTrue(SavedOpportunity.objects.exists())

    def test_production_hides_saved_demo_details_and_account_deletion_removes_saves(self):
        self.save();self.employer.is_demo=True;self.employer.save()
        with override_settings(DEBUG=False,SECURE_SSL_REDIRECT=False):
            self.assertContains(self.client.get(reverse('saved_opportunities')),'Currently unavailable')
        self.seeker.delete()
        self.assertFalse(SavedOpportunity.objects.exists())

    def test_saved_view_has_bounded_pagination_and_amharic_shell(self):
        for number in range(14):
            SavedOpportunity.objects.create(user=self.seeker,opportunity=Opportunity.objects.create(employer=self.employer,title=f'Saved {number}',kind='entry',location='Addis Ababa',category='Test',description='Test',requirements='Test',compensation='Stipend',deadline=timezone.localdate()+timedelta(days=10),published=True),title=f'Saved {number}',employer_name=self.employer.name,location='Addis Ababa')
        self.client.force_login(self.seeker)
        response=self.client.get(reverse('saved_opportunities'),HTTP_ACCEPT_LANGUAGE='am')
        self.assertEqual(len(response.context['page']),12)
        self.assertContains(response,'<html lang="am">')
        self.assertEqual(len(self.client.get(reverse('saved_opportunities'),{'page':2}).context['page']),2)
