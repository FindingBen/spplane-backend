from django.test import TestCase

from rest_framework.test import APIClient
from django.urls import reverse

from apps.accounts.models import User
from apps.sms.models import Sms, SmsPage, SmsRecipient, SmsEvent


class PublicSmsPageTests(TestCase):
	def setUp(self):
		self.client = APIClient()

		# owner user for sms records
		self.user = User.objects.create_user(email='owner@example.com', password='pass', user_type='regular')

		# public page (no token required)
		self.sms_public = Sms.objects.create(
			user=self.user,
			tracking_id='track_public',
			sender='SENDER',
			body='Hello public',
			status='sent',
		)
		self.page_public = SmsPage.objects.create(
			sms=self.sms_public,
			public_slug='publicslug1',
			content_snapshot={'hello': 'world'},
			requires_token=False,
			page_status='published',
		)

		# token-protected page
		self.sms_token = Sms.objects.create(
			user=self.user,
			tracking_id='track_token',
			sender='SENDER',
			body='Hello token',
			status='sent',
		)
		self.page_token = SmsPage.objects.create(
			sms=self.sms_token,
			public_slug='tokenpage1',
			content_snapshot={'components': []},
			requires_token=True,
			page_status='published',
		)
		self.recipient = SmsRecipient.objects.create(
			sms=self.sms_token,
			phone='+1234567890',
			access_token='secrettoken123',
			status='sent',
		)

	def test_public_page_no_token(self):
		url = reverse('sms_public_page', kwargs={'slug': self.page_public.public_slug})
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		data = resp.json()
		self.assertEqual(data['public_slug'], self.page_public.public_slug)
		self.assertFalse(data['requires_token'])
		self.assertIn('content_snapshot', data)

	def test_token_required_flow(self):
		url = reverse('sms_public_page', kwargs={'slug': self.page_token.public_slug})

		# missing token
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 401)

		# invalid token
		resp = self.client.get(url + '?t=badtoken')
		self.assertEqual(resp.status_code, 403)

		# valid token — should return page and record recipient open + event
		resp = self.client.get(url + '?t=' + self.recipient.access_token)
		self.assertEqual(resp.status_code, 200)

		self.recipient.refresh_from_db()
		self.assertIsNotNone(self.recipient.page_opened_at)
		self.assertTrue(SmsEvent.objects.filter(recipient=self.recipient, event_type='page_view').exists())
