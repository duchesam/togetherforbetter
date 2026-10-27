from unittest.mock import patch
from django.contrib.admin.models import LogEntry
from django.test import Client, TestCase
from django.urls import reverse
from .models import ReviewDecision, Employer
from .test_moderation import ModerationFixture


class ReviewReceiptTests(ModerationFixture, TestCase):
    def create_receipt(self, kind='opportunity', decision='withdraw'):
        self.client.post(self.url(kind), self.payload(kind, decision))
        return ReviewDecision.objects.latest('pk')

    def test_shared_message_only_reaches_owner(self):
        receipt = self.create_receipt()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('employer_reviews'))
        self.assertContains(response, receipt.employer_message)
        self.assertNotContains(response, 'Independent review completed.')
        self.assertNotContains(response, self.staff.username)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIsNone(ReviewDecision.objects.get().read_at)
        for user in [self.seeker, self.other, self.staff]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('employer_reviews')).status_code, 404)
            self.assertEqual(self.client.post(reverse('review_read', args=[receipt.pk])).status_code, 404)

    def test_mark_read_post_csrf_and_idempotent(self):
        receipt = self.create_receipt()
        self.client.force_login(self.owner)
        url = reverse('review_read', args=[receipt.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.owner)
        self.assertEqual(secure.post(url).status_code, 403)
        self.client.post(url)
        receipt.refresh_from_db(); stamp = receipt.read_at
        self.client.post(url); receipt.refresh_from_db()
        self.assertEqual(receipt.read_at, stamp)
        self.assertIsNotNone(stamp)

    def test_dashboard_unread_count(self):
        receipt = self.create_receipt()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('dashboard')).context['unread_reviews'], 1)
        self.client.post(reverse('review_read',args=[receipt.pk]))
        self.assertEqual(self.client.get(reverse('dashboard')).context['unread_reviews'], 0)

    def test_withdrawal_needs_actionable_message(self):
        data = self.payload(decision='withdraw'); data['employer_message'] = '  '
        self.assertIn('employer_message', self.client.post(self.url(), data).context['form'].errors)
        self.assertFalse(ReviewDecision.objects.exists())
        self.assertFalse(LogEntry.objects.exists())

    def test_employer_decision_replay_rejected_even_when_state_unchanged(self):
        data = self.payload('employer', 'approve')
        self.assertEqual(self.client.post(self.url('employer'), data).status_code, 302)
        self.assertEqual(self.client.post(self.url('employer'), data).status_code, 409)
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_receipt_and_audit_rollback_with_failed_save(self):
        data = self.payload(decision='withdraw')
        with patch('opportunities.moderation_views.ReviewDecision.objects.create', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError): self.client.post(self.url(), data)
        self.job.refresh_from_db()
        self.assertTrue(self.job.published)
        self.assertFalse(LogEntry.objects.exists())

    def test_old_decision_cannot_restore_approval_after_edit(self):
        receipt = self.create_receipt(decision='approve')
        old_title = receipt.reviewed_title
        self.client.force_login(self.owner)
        self.job.refresh_from_db()
        self.client.post(reverse('listing_edit',args=[self.job.pk]),self.data(title='Revised after approval'))
        self.job.refresh_from_db(); receipt.refresh_from_db()
        self.assertFalse(self.job.published)
        self.assertEqual(receipt.reviewed_title, old_title)
        self.assertEqual(self.client.get(reverse('detail',args=[self.job.pk])).status_code,404)

    def test_filter_only_own_listing_and_pagination(self):
        self.create_receipt()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('employer_reviews')+'?listing=999999').status_code,404)
        self.assertEqual(self.client.get(reverse('employer_reviews')+'?listing=invalid').status_code,404)
        self.assertEqual(len(self.client.get(reverse('employer_reviews')+f'?listing={self.job.pk}').context['page']),1)
        ReviewDecision.objects.bulk_create([ReviewDecision(employer=self.employer, decision='approve',reviewed_title='Example') for _ in range(13)])
        self.assertEqual(len(self.client.get(reverse('employer_reviews')).context['page']),12)

    def test_message_html_is_escaped(self):
        data=self.payload();data['employer_message']='<script>alert(1)</script>'
        self.client.post(self.url(),data)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('employer_reviews'))
        self.assertNotContains(response,'<script>')
        self.assertContains(response,'&lt;script&gt;')


    def test_foreign_employer_cannot_read_receipt_or_filter_listing(self):
        receipt = self.create_receipt()
        Employer.objects.create(user=self.other, name='Another employer')
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('employer_reviews')), receipt.employer_message)
        self.assertEqual(self.client.get(reverse('employer_reviews')+f'?listing={self.job.pk}').status_code,404)
        self.assertEqual(self.client.post(reverse('review_read',args=[receipt.pk])).status_code,404)

    def test_amharic_owner_history_and_anonymous_access(self):
        self.create_receipt()
        self.client.force_login(self.owner)
        self.client.cookies['django_language']='am'
        self.assertContains(self.client.get(reverse('employer_reviews')), 'የግምገማ ውሳኔዎች')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('employer_reviews')).status_code,302)
