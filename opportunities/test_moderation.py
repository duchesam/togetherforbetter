from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission, User
from django.test import TestCase, Client
from django.urls import reverse
from .models import Opportunity
from .test_listings import ListingFixture


class ModerationTests(ListingFixture, TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('reviewer', is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=['change_employer', 'change_opportunity']))
        self.client.force_login(self.staff)

    def url(self, kind='opportunity'):
        return reverse('moderation_review', args=[kind, self.job.pk if kind == 'opportunity' else self.employer.pk])

    def payload(self, kind='opportunity', decision='approve'):
        response = self.client.get(self.url(kind))
        return {'snapshot': response.context['form']['snapshot'].value(), 'decision': decision, 'reason': 'Independent review completed.'}

    def test_approval_and_withdrawal_are_audited_and_versioned(self):
        data = self.payload(decision='withdraw')
        self.assertEqual(self.client.post(self.url(), data).status_code, 302)
        self.job.refresh_from_db()
        self.assertFalse(self.job.published)
        self.assertEqual(self.job.version, 2)
        self.assertIn('Independent review', LogEntry.objects.get().change_message)
        self.client.post(self.url(), self.payload())
        self.job.refresh_from_db()
        self.assertTrue(self.job.published)
        self.assertEqual(LogEntry.objects.count(), 2)

    def test_stale_listing_and_employer_details_rejected(self):
        data = self.payload()
        Opportunity.objects.filter(pk=self.job.pk).update(title='Changed')
        self.assertEqual(self.client.post(self.url(), data).status_code, 409)
        data = self.payload('employer')
        self.employer.name = 'New identity'
        self.employer.save()
        self.assertEqual(self.client.post(self.url('employer'), data).status_code, 409)
        self.assertFalse(LogEntry.objects.exists())

    def test_changed_org_invalidates_listing_review(self):
        data = self.payload()
        self.employer.verified = False
        self.employer.save()
        self.assertEqual(self.client.post(self.url(), data).status_code, 409)

    def test_approval_blocked_for_unverified_closed_expired(self):
        from django.utils import timezone
        from datetime import timedelta
        for changes in [{'closed_at': timezone.now()}, {'closed_at': None, 'deadline': timezone.localdate()-timedelta(days=1)}]:
            Opportunity.objects.filter(pk=self.job.pk).update(**changes, published=False)
            response = self.client.post(self.url(), self.payload())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].non_field_errors())
        self.employer.verified = False
        self.employer.save()
        Opportunity.objects.filter(pk=self.job.pk).update(deadline=timezone.localdate())
        self.assertTrue(self.client.post(self.url(), self.payload()).context['form'].non_field_errors())

    def test_reason_required_and_tokens_actor_bound(self):
        data = self.payload(decision='withdraw')
        data['reason'] = ''
        self.assertTrue(self.client.post(self.url(), data).context['form'].errors)
        data['reason'] = 'Reason'
        data['snapshot'] += 'invalid'
        self.assertEqual(self.client.post(self.url(), data).status_code, 409)

    def test_permissions_are_required_even_for_staff(self):
        for user in [self.owner, User.objects.create_user('no-permissions', is_staff=True)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('moderation_queue')).status_code, 403)
            self.assertEqual(self.client.get(self.url()).status_code, 403)
            self.assertEqual(self.client.post(self.url(), {}).status_code, 403)

    def test_permission_scoping_and_history_privacy(self):
        self.staff.user_permissions.remove(Permission.objects.get(codename='change_employer'))
        self.assertEqual(self.client.get(self.url('employer')).status_code, 403)
        self.assertEqual(self.client.get(reverse('moderation_queue')+'?kind=employer').status_code, 403)
        self.assertEqual(self.client.get(reverse('moderation_queue')).status_code, 200)

    def test_csrf_required_no_get_mutation_and_amharic(self):
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.staff)
        self.assertEqual(secure.post(self.url(), self.payload()).status_code, 403)
        self.assertFalse(LogEntry.objects.exists())
        self.client.cookies['django_language'] = 'am'
        self.assertContains(self.client.get(reverse('moderation_queue')), 'lang="am"')
        self.assertContains(self.client.get(self.url()), 'የግምገማ ምክንያት')

    def test_employer_withdrawal_hides_public_listing(self):
        self.client.post(self.url('employer'), self.payload('employer', 'withdraw'))
        self.assertEqual(self.client.get(reverse('detail', args=[self.job.pk])).status_code, 404)
        self.job.refresh_from_db()
        self.assertTrue(self.job.published)

    def test_pending_withholding_is_audited_and_cannot_be_replayed(self):
        Opportunity.objects.filter(pk=self.job.pk).update(published=False)
        data = self.payload(decision='withdraw')
        self.client.post(self.url(), data)
        self.assertEqual(LogEntry.objects.count(), 1)
        self.assertEqual(self.client.post(self.url(), data).status_code, 409)

    def test_review_expiry_and_actor_binding(self):
        from unittest.mock import patch
        from django.core import signing
        data = self.payload()
        other = User.objects.create_superuser('other-reviewer', 'other@example.invalid', 'Test-password-9!')
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url(), data).status_code, 409)
        self.client.force_login(self.staff)
        from types import SimpleNamespace
        from unittest.mock import Mock
        with patch('opportunities.moderation_views.signing', SimpleNamespace(dumps=signing.dumps, loads=Mock(side_effect=signing.SignatureExpired), BadSignature=signing.BadSignature)):
            self.assertEqual(self.client.post(self.url(), data).status_code, 409)

    def test_cannot_review_own_organization_or_listing(self):
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.get(self.url('employer')).status_code, 403)

    def test_all_records_includes_approved_for_withdrawal(self):
        response = self.client.get(reverse('moderation_queue')+'?kind=opportunity&state=all')
        self.assertContains(response, self.job.title)
