from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import ShopifyProfile, User
from apps.payment.models import PaymentOrder, SmsPackage
from apps.payment.service import (
    PaymentEligibilityResult,
    PaymentOrderService,
    ShopifyOneTimePaymentService,
)


class ShopifyOneTimeChargeViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='merchant@example.com',
            password='password123',
            user_type='shopify',
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain='merchant.myshopify.com',
            access_token='test-token',
        )
        self.package = SmsPackage.objects.create(
            merchant_profile=self.shopify_profile,
            external_package_id='starter',
            shopify_product_handle='basic-package',
            shopify_product_title='Basic plan',
            name='Starter topup',
            sms_count=200,
            price=Decimal('9.00'),
            currency='USD',
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.eligibility = PaymentEligibilityResult(
            is_allowed=True,
            code='eligible',
            reason='Merchant is allowed to purchase SMS packages.',
            plan_public_name='basic',
            partner_development=False,
        )

    @staticmethod
    def _charge_payload(provider_charge_id):
        return {
            'provider': 'shopify',
            'provider_charge_id': provider_charge_id,
            'confirmation_url': 'https://shopify.example/confirm',
            'created_at': '2026-05-12T10:00:00Z',
            'name': 'Starter topup',
            'amount': '9.00',
            'currency_code': 'USD',
            'raw_response': {},
        }

    @patch('apps.payment.api.views.ShopifyOneTimePaymentService.create_one_time_charge')
    @patch('apps.payment.api.views.ShopifyBillingStateService.sync_billing_state')
    def test_create_charge_accepts_external_package_id(self, sync_billing_state_mock, create_charge_mock):
        sync_billing_state_mock.return_value = (None, self.eligibility)
        create_charge_mock.return_value = self._charge_payload('gid://shopify/AppPurchaseOneTime/1')

        response = self.client.post(
            '/api/payment/v1/one-time-charges/',
            {
                'package_id': 'starter',
                'description': 'Starter topup',
                'test': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payment_order = PaymentOrder.objects.get(provider_charge_id='gid://shopify/AppPurchaseOneTime/1')
        self.assertEqual(payment_order.package, self.package)
        self.assertEqual(response.json()['provider_charge_id'], 'gid://shopify/AppPurchaseOneTime/1')

    @patch('apps.payment.api.views.ShopifyOneTimePaymentService.create_one_time_charge')
    @patch('apps.payment.api.views.ShopifyBillingStateService.sync_billing_state')
    def test_create_charge_accepts_shopify_product_handle(self, sync_billing_state_mock, create_charge_mock):
        sync_billing_state_mock.return_value = (None, self.eligibility)
        create_charge_mock.return_value = self._charge_payload('gid://shopify/AppPurchaseOneTime/2')

        response = self.client.post(
            '/api/payment/v1/one-time-charges/',
            {
                'package_id': 'basic-package',
                'description': 'Starter topup',
                'test': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payment_order = PaymentOrder.objects.get(provider_charge_id='gid://shopify/AppPurchaseOneTime/2')
        self.assertEqual(payment_order.package, self.package)

    @patch('apps.payment.api.views.ShopifyOneTimePaymentService.create_one_time_charge')
    @patch('apps.payment.api.views.ShopifyBillingStateService.sync_billing_state')
    def test_create_charge_keeps_uuid_lookup_backwards_compatible(self, sync_billing_state_mock, create_charge_mock):
        sync_billing_state_mock.return_value = (None, self.eligibility)
        create_charge_mock.return_value = self._charge_payload('gid://shopify/AppPurchaseOneTime/3')

        response = self.client.post(
            '/api/payment/v1/one-time-charges/',
            {
                'package_id': str(self.package.package_id),
                'description': 'Starter topup',
                'test': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payment_order = PaymentOrder.objects.get(provider_charge_id='gid://shopify/AppPurchaseOneTime/3')
        self.assertEqual(payment_order.package, self.package)

    @patch('apps.payment.service.ShopifyGraphQLClient.execute')
    def test_service_serializes_decimal_amount_for_shopify_graphql(self, execute_mock):
        execute_mock.return_value = {
            'appPurchaseOneTimeCreate': {
                'userErrors': [],
                'appPurchaseOneTime': {
                    'id': 'gid://shopify/AppPurchaseOneTime/4',
                    'createdAt': '2026-05-12T10:00:00Z',
                },
                'confirmationUrl': 'https://shopify.example/confirm',
            }
        }

        payload = ShopifyOneTimePaymentService.create_one_time_charge(
            self.shopify_profile,
            {
                'amount': Decimal('9.00'),
                'currency_code': 'USD',
                'description': 'Starter topup',
                'test': False,
            },
        )

        self.assertEqual(execute_mock.call_args.kwargs['variables']['price']['amount'], '9.00')
        self.assertEqual(payload['amount'], '9.00')


class SmsPackageViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='merchant-list@example.com',
            password='password123',
            user_type='shopify',
            is_active=True,
        )
        self.other_user = User.objects.create_user(
            email='other-merchant@example.com',
            password='password123',
            user_type='shopify',
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain='list-merchant.myshopify.com',
            access_token='test-token',
        )
        self.other_profile = ShopifyProfile.objects.create(
            user=self.other_user,
            shop_domain='other-merchant.myshopify.com',
            access_token='other-token',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.active_package = SmsPackage.objects.create(
            merchant_profile=self.shopify_profile,
            external_package_id='starter',
            shopify_product_handle='basic-package',
            shopify_product_title='Basic plan',
            name='Starter topup',
            sms_count=200,
            price=Decimal('9.00'),
            currency='USD',
            is_active=True,
        )
        SmsPackage.objects.create(
            merchant_profile=self.shopify_profile,
            external_package_id='inactive-plan',
            name='Inactive topup',
            sms_count=50,
            price=Decimal('1.00'),
            currency='USD',
            is_active=False,
        )
        SmsPackage.objects.create(
            merchant_profile=self.other_profile,
            external_package_id='foreign-package',
            name='Foreign topup',
            sms_count=500,
            price=Decimal('19.00'),
            currency='USD',
            is_active=True,
        )

    def test_list_returns_only_active_packages_for_authenticated_shop(self):
        response = self.client.get('/api/payment/v1/sms-packages/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['package_id'], str(self.active_package.package_id))
        self.assertEqual(payload[0]['external_package_id'], 'starter')
        self.assertEqual(payload[0]['shopify_product_handle'], 'basic-package')
        self.assertEqual(payload[0]['display_name'], 'Basic plan')
        self.assertEqual(payload[0]['price'], '9.00')

    def test_list_requires_connected_shopify_store(self):
        user_without_store = User.objects.create_user(
            email='no-store@example.com',
            password='password123',
            user_type='shopify',
            is_active=True,
        )
        self.client.force_authenticate(user=user_without_store)

        response = self.client.get('/api/payment/v1/sms-packages/')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Shopify store is not connected for this user.')


class ShopifyOneTimeChargeWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='merchant-webhook@example.com',
            password='password123',
            user_type='shopify',
            is_active=True,
        )
        self.shopify_profile = ShopifyProfile.objects.create(
            user=self.user,
            shop_domain='webhook-merchant.myshopify.com',
            access_token='test-token',
        )
        self.package = SmsPackage.objects.create(
            merchant_profile=self.shopify_profile,
            external_package_id='starter',
            name='Starter topup',
            sms_count=200,
            price=Decimal('9.00'),
            currency='USD',
            is_active=True,
        )
        self.payment_order = PaymentOrder.objects.create(
            user=self.user,
            package=self.package,
            provider=PaymentOrder.Provider.SHOPIFY,
            purchase_kind=PaymentOrder.PurchaseKind.ONE_TIME,
            status=PaymentOrder.Status.PENDING,
            provider_charge_id='gid://shopify/AppPurchaseOneTime/99',
            price_snapshot={
                'amount': '9.00',
                'currency_code': 'USD',
            },
            credits_snapshot={
                'amount': 200,
                'unit': 'sms',
            },
            plan_snapshot={},
        )

    def test_cancelled_webhook_marks_order_cancelled(self):
        result = PaymentOrderService.handle_one_time_charge_webhook(
            shopify_profile=self.shopify_profile,
            payload={
                'id': self.payment_order.provider_charge_id,
                'status': 'CANCELLED',
            },
            topic='app_purchases_one_time/update',
            external_event_id='webhook-cancelled-1',
            payload_hash=PaymentOrderService.build_payload_hash(b'cancelled-payload'),
        )

        self.payment_order.refresh_from_db()

        self.assertEqual(self.payment_order.status, PaymentOrder.Status.CANCELLED)
        self.assertEqual(result['status'], 'cancelled')
