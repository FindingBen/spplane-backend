from django.test import TestCase, override_settings
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rest_framework.test import APIClient
from django.urls import reverse

from apps.accounts.models import User
from apps.contacts.models import Contact, ContactList, SegmentMembership
from apps.sms.models import Sms, SmsPage, SmsRecipient, SmsEvent
from apps.sms.sending_service import VonageProvider, SmsSendingService


class PublicSmsPageTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # owner user for sms records
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="pass",
            user_type="regular",
        )

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


class SmsEstimateCostTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='merchant@example.com',
            password='pass12345',
            user_type='regular',
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)

        self.contact_list = ContactList.objects.create(
            users=self.user,
            segment_name='VIP Customers',
        )
        self.contact = Contact.objects.create(
            users=self.user,
            phone='+4552529924',
            first_name='Ada',
            status='subscribed',
        )
        SegmentMembership.objects.create(
            contact_list=self.contact_list,
            contact=self.contact,
        )
        self.sms = Sms.objects.create(
            user=self.user,
            contact_list=self.contact_list,
            tracking_id='track_estimate',
            sender='SENDER',
            body='Hello Ada',
            status='draft',
        )

    def test_estimate_cost_uses_segment_membership_contacts(self):
        response = self.client.get(f'/api/sms/v1/{self.sms.id}/estimate-cost/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['recipients'], 1)
        self.assertEqual(payload['details'][0]['phone'], '+4552529924')

    def test_estimate_cost_rejects_us_numbers(self):
        self.contact.phone = '+12025550123'
        self.contact.save(update_fields=['phone', 'updated_at'])

        response = self.client.get(f'/api/sms/v1/{self.sms.id}/estimate-cost/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('US and CA numbers is not supported yet', response.json()['error'])


class SmsSendValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='send-validation@example.com',
            password='pass12345',
            user_type='regular',
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)

        self.contact_list = ContactList.objects.create(
            users=self.user,
            segment_name='Blocked Region Contacts',
        )
        self.contact = Contact.objects.create(
            users=self.user,
            phone='+14165550123',
            first_name='Lin',
            status='subscribed',
        )
        SegmentMembership.objects.create(
            contact_list=self.contact_list,
            contact=self.contact,
        )
        self.sms = Sms.objects.create(
            user=self.user,
            contact_list=self.contact_list,
            tracking_id='track_send_validation',
            sender='SENDER',
            body='Hello Lin',
            status='draft',
        )

    @patch('apps.sms.tasks.dispatch_sms_send.delay')
    def test_send_rejects_ca_numbers_before_queueing(self, delay_mock):
        response = self.client.post(f'/api/sms/v1/{self.sms.id}/send/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('US and CA numbers is not supported yet', response.json()['error'])
        delay_mock.assert_not_called()


class SmsSendingServiceTests(TestCase):
    @override_settings(FRONTEND_URL='https://frontend.example.com/')
    def test_render_body_uses_sms_page_route_for_hosted_pages(self):
        service = SmsSendingService.__new__(SmsSendingService)

        body = service.render_body(
            template='Hello {{first_name}}\n{{page_link}}',
            first_name='Ada',
            page_slug='publicslug1',
            access_token='token123',
        )

        self.assertIn('Hello Ada', body)
        self.assertIn(
            'https://frontend.example.com/sms/page/publicslug1?t=token123',
            body,
        )
        self.assertNotIn('/p/publicslug1?t=token123', body)


class VonageProviderTests(TestCase):
    def test_send_normalizes_e164_recipient_number_for_sdk(self):
        provider = VonageProvider(api_key='key', api_secret='secret')
        provider._vonage.messages.send = Mock(return_value=SimpleNamespace(message_uuid='msg-1'))

        result = provider.send(
            from_='SPPLANE',
            to='+4552529924',
            text='Hello world',
            client_ref='ref-1',
        )

        self.assertTrue(result.success)
        sent_message = provider._vonage.messages.send.call_args.args[0]
        self.assertEqual(sent_message.to, '4552529924')

    def test_send_marks_invalid_recipient_number_as_permanent_failure(self):
        provider = VonageProvider(api_key='key', api_secret='secret')

        result = provider.send(
            from_='SPPLANE',
            to='invalid-number',
            text='Hello world',
            client_ref='ref-2',
        )

        self.assertFalse(result.success)
        self.assertTrue(result.is_permanent_failure)
        self.assertEqual(result.error_code, 'validation_error')

    def test_send_rejects_us_and_ca_recipient_numbers(self):
        provider = VonageProvider(api_key='key', api_secret='secret')
        provider._vonage.messages.send = Mock()

        for phone in ('+12025550123', '+14165550123'):
            with self.subTest(phone=phone):
                result = provider.send(
                    from_='SPPLANE',
                    to=phone,
                    text='Hello world',
                    client_ref='ref-blocked',
                )

                self.assertFalse(result.success)
                self.assertTrue(result.is_permanent_failure)
                self.assertEqual(result.error_code, 'validation_error')
                self.assertIn('US and CA numbers is not supported yet', result.error_message)

        provider._vonage.messages.send.assert_not_called()
