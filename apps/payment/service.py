from dataclasses import dataclass
import hashlib

import logging
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounts.service import WalletTransactionService
from apps.shopify.service import ShopifyGraphQLClient, ShopifyGraphQLError
from apps.shopify.queries import CREATE_PURCHASED_CHARGE,GET_SHOP_BILLING_STATE
from apps.payment.models import MerchantBillingState, PaymentOrder, WebhookEvent

logger = logging.getLogger(__name__)

class ShopifyPaymentError(Exception):
    """Custom exception for Shopify payment-related errors.
    """

@dataclass(frozen=True)
class PaymentEligibilityResult:
    is_allowed: bool
    code: str
    reason: str
    plan_public_name: str
    partner_development: bool


class PaymentEligibilityService:
    DEFAULT_NON_BILLABLE_PLANS = frozenset(
        {
            'development',
            'trial',
            'plus trial',
            'inactive',
            'paused',
        }
    )
    PLAN_ALLOWLIST_SETTING = 'PAYMENT_BILLABLE_PLAN_ALLOWLIST'
    PLAN_DENYLIST_SETTING = 'PAYMENT_NON_BILLABLE_PLAN_DENYLIST'

    @classmethod
    def evaluate_plan(cls, *, plan_public_name: str = '', partner_development: bool = False):
        normalized_plan = cls._normalize_plan_name(plan_public_name)

        if partner_development:
            return PaymentEligibilityResult(
                is_allowed=False,
                code='partner_development_shop',
                reason='Partner development shops are not allowed to purchase SMS packages.',
                plan_public_name=plan_public_name or '',
                partner_development=True,
            )

        if not normalized_plan:
            return PaymentEligibilityResult(
                is_allowed=False,
                code='unknown_shop_plan',
                reason='Shop plan is unavailable, so purchases are blocked until billing status is refreshed.',
                plan_public_name=plan_public_name or '',
                partner_development=False,
            )

        allowed_plans = cls._get_normalized_setting_values(cls.PLAN_ALLOWLIST_SETTING)
        if allowed_plans is not None:
            is_allowed = normalized_plan in allowed_plans
            return PaymentEligibilityResult(
                is_allowed=is_allowed,
                code='eligible' if is_allowed else 'plan_not_billable',
                reason=(
                    'Merchant is allowed to purchase SMS packages.'
                    if is_allowed
                    else f'Shops on the {plan_public_name} plan are not allowed to purchase SMS packages.'
                ),
                plan_public_name=plan_public_name or '',
                partner_development=False,
            )

        denied_plans = cls._get_normalized_setting_values(
            cls.PLAN_DENYLIST_SETTING,
            default=cls.DEFAULT_NON_BILLABLE_PLANS,
        )
        is_allowed = normalized_plan not in denied_plans
        return PaymentEligibilityResult(
            is_allowed=is_allowed,
            code='eligible' if is_allowed else 'plan_not_billable',
            reason=(
                'Merchant is allowed to purchase SMS packages.'
                if is_allowed
                else f'Shops on the {plan_public_name} plan are not allowed to purchase SMS packages.'
            ),
            plan_public_name=plan_public_name or '',
            partner_development=False,
        )

    @classmethod
    def evaluate_billing_state(cls, billing_state: MerchantBillingState):
        return cls.evaluate_plan(
            plan_public_name=billing_state.plan_public_name,
            partner_development=billing_state.partner_development,
        )

    @classmethod
    def evaluate_merchant_profile(cls, merchant_profile):
        billing_state = getattr(merchant_profile, 'billing_state', None)
        if billing_state is None:
            return PaymentEligibilityResult(
                is_allowed=False,
                code='missing_billing_state',
                reason='Billing status has not been synced for this merchant yet.',
                plan_public_name='',
                partner_development=False,
            )
        return cls.evaluate_billing_state(billing_state)

    @classmethod
    def assert_can_purchase(cls, merchant_profile):
        result = cls.evaluate_merchant_profile(merchant_profile)
        if not result.is_allowed:
            raise ValidationError(result.reason)
        return result

    @staticmethod
    def _normalize_plan_name(plan_public_name: str) -> str:
        return ' '.join((plan_public_name or '').strip().lower().split())

    @classmethod
    def _get_normalized_setting_values(cls, setting_name: str, default=None):
        raw_value = getattr(settings, setting_name, None)
        if raw_value is None:
            if default is None:
                return None
            raw_value = default

        normalized_values = {
            cls._normalize_plan_name(value)
            for value in raw_value
            if cls._normalize_plan_name(value)
        }
        return normalized_values


class ShopifyOneTimePaymentService:
    @staticmethod
    def create_one_time_charge(shopify_profile, payment_data: dict) -> dict:
        """Creates onetime charge"""
        client = ShopifyGraphQLClient(
            shop_domain=shopify_profile.shop_domain,
            access_token=shopify_profile.access_token,
        )

        amount = payment_data.get("amount")
        if amount in (None, ""):
            raise ShopifyPaymentError("Amount is required to create a one-time charge.")

        description = payment_data.get("description", "One-time purchase 200 credits")
        currency_code = payment_data.get("currency_code", "USD")

        return_url = ShopifyOneTimePaymentService.verify_and_build_callback_url(
            shopify_profile.shop_domain
        )
        charge_data = {
            "name": description,
            "price": {
                "amount": amount,
                "currencyCode": currency_code,
            },
            "returnUrl": return_url,
            "test": payment_data.get("test", False),
        }

        try:
            data = client.execute(
                CREATE_PURCHASED_CHARGE,
                variables=charge_data,
            )
        except ShopifyGraphQLError as exc:
            logger.exception(
                "Failed to create Shopify one-time charge for %s",
                shopify_profile.shop_domain,
            )
            raise ShopifyPaymentError("Failed to create Shopify one-time charge.") from exc

        purchase_payload = data.get("appPurchaseOneTimeCreate") or {}
        user_errors = purchase_payload.get("userErrors") or []
        if user_errors:
            error_message = "; ".join(
                error.get("message", "Unknown Shopify payment error.")
                for error in user_errors
            )
            raise ShopifyPaymentError(error_message)

        purchase = purchase_payload.get("appPurchaseOneTime") or {}
        provider_charge_id = purchase.get("id")
        confirmation_url = purchase_payload.get("confirmationUrl") or ""

        if not provider_charge_id or not confirmation_url:
            raise ShopifyPaymentError(
                "Shopify did not return a valid one-time charge confirmation payload."
            )

        return {
            "provider": "shopify",
            "provider_charge_id": provider_charge_id,
            "confirmation_url": confirmation_url,
            "created_at": purchase.get("createdAt"),
            "name": charge_data["name"],
            "amount": charge_data["price"]["amount"],
            "currency_code": charge_data["price"]["currencyCode"],
            "raw_response": purchase_payload,
        }

    @staticmethod
    def verify_and_build_callback_url(shop_domain: str) -> str:
        base_url = "https://spplane.app" if settings.ENVIRONMENT == "production" else "http://localhost:3000"
        callback_url = f"{base_url}/shopify/one_time_charge/confirmation?shop={shop_domain}"
        return callback_url
    
class ShopifyBillingStateService:
    @staticmethod
    def sync_billing_state(shopify_profile):
        client = ShopifyGraphQLClient(
            shop_domain=shopify_profile.shop_domain,
            access_token=shopify_profile.access_token,
        )
        data = client.execute(GET_SHOP_BILLING_STATE)
        shop = data.get("shop") or {}
        plan = shop.get("plan") or {}

        billing_state, _ = MerchantBillingState.objects.update_or_create(
            merchant_profile=shopify_profile,
            defaults={
                "plan_public_name": plan.get("publicDisplayName", ""),
                "partner_development": plan.get("partnerDevelopment", False),
                "shopify_plus": plan.get("shopifyPlus", False),
                "checked_at": timezone.now(),
                "raw_shop_snapshot": shop,
            },
        )

        eligibility = PaymentEligibilityService.evaluate_billing_state(billing_state)
        if billing_state.is_billable != eligibility.is_allowed:
            billing_state.is_billable = eligibility.is_allowed
            billing_state.save(update_fields=["is_billable"])

        return billing_state, eligibility


class PaymentOrderService:
    FINAL_WEBHOOK_STATUSES = {
        'ACTIVE': PaymentOrder.Status.SETTLED,
        'DECLINED': PaymentOrder.Status.DECLINED,
        'EXPIRED': PaymentOrder.Status.CANCELLED,
        'PENDING': PaymentOrder.Status.PENDING,
    }

    @staticmethod
    def create_pending_one_time_order(*, user, package, eligibility: PaymentEligibilityResult):
        return PaymentOrder.objects.create(
            user=user,
            package=package,
            provider=PaymentOrder.Provider.SHOPIFY,
            purchase_kind=PaymentOrder.PurchaseKind.ONE_TIME,
            status=PaymentOrder.Status.PENDING,
            price_snapshot={
                'amount': str(package.price),
                'currency_code': package.currency,
            },
            credits_snapshot={
                'amount': package.sms_count,
                'unit': 'sms',
            },
            plan_snapshot={
                'plan_public_name': eligibility.plan_public_name,
                'partner_development': eligibility.partner_development,
                'eligibility_code': eligibility.code,
                'eligibility_reason': eligibility.reason,
            },
        )

    @staticmethod
    def attach_shopify_charge(payment_order: PaymentOrder, charge_payload: dict):
        payment_order.provider_charge_id = charge_payload['provider_charge_id']
        payment_order.confirmation_url = charge_payload['confirmation_url']
        payment_order.failure_reason = ''
        payment_order.save(
            update_fields=['provider_charge_id', 'confirmation_url', 'failure_reason', 'updated_at']
        )
        return payment_order

    @staticmethod
    @transaction.atomic
    def handle_one_time_charge_webhook(
        *,
        shopify_profile,
        payload: dict,
        topic: str,
        external_event_id: str = '',
        payload_hash: str,
    ) -> dict:
        webhook_event = None
        created = False
        if external_event_id:
            webhook_event = WebhookEvent.objects.select_for_update().filter(
                topic=topic,
                shop_domain=shopify_profile.shop_domain,
                external_event_id=external_event_id,
            ).first()

        if webhook_event is None:
            webhook_event, created = WebhookEvent.objects.get_or_create(
                payload_hash=payload_hash,
                defaults={
                    'topic': topic,
                    'shop_domain': shopify_profile.shop_domain,
                    'external_event_id': external_event_id,
                    'payload': payload,
                },
            )
        if not created and webhook_event.processed_at is not None:
            return webhook_event.processing_result or {
                'status': 'duplicate',
                'message': 'Webhook event already processed.',
            }

        provider_charge_id = PaymentOrderService.extract_provider_charge_id(payload)
        purchase_status = PaymentOrderService.extract_purchase_status(payload)

        if not provider_charge_id:
            return PaymentOrderService._finalize_webhook_event(
                webhook_event,
                {
                    'status': 'ignored',
                    'reason': 'Missing provider charge id in webhook payload.',
                },
                payload=payload,
                topic=topic,
                external_event_id=external_event_id,
            )

        payment_order = PaymentOrderService.get_payment_order_for_charge(
            shopify_profile=shopify_profile,
            provider_charge_id=provider_charge_id,
        )
        if payment_order is None:
            return PaymentOrderService._finalize_webhook_event(
                webhook_event,
                {
                    'status': 'ignored',
                    'reason': 'No local payment order matches this Shopify charge.',
                    'provider_charge_id': provider_charge_id,
                },
                payload=payload,
                topic=topic,
                external_event_id=external_event_id,
            )

        normalized_status = (purchase_status or '').strip().upper()
        if not normalized_status:
            return PaymentOrderService._finalize_webhook_event(
                webhook_event,
                {
                    'status': 'ignored',
                    'reason': 'Missing purchase status in webhook payload.',
                    'provider_charge_id': provider_charge_id,
                    'payment_order_id': str(payment_order.id),
                },
                payload=payload,
                topic=topic,
                external_event_id=external_event_id,
            )

        if normalized_status == 'ACTIVE':
            if payment_order.status == PaymentOrder.Status.SETTLED:
                return PaymentOrderService._finalize_webhook_event(
                    webhook_event,
                    {
                        'status': 'already_settled',
                        'provider_charge_id': provider_charge_id,
                        'payment_order_id': str(payment_order.id),
                    },
                    payload=payload,
                    topic=topic,
                    external_event_id=external_event_id,
                )

            now_value = timezone.now()
            top_up_amount = PaymentOrderService.get_credit_amount(payment_order)
            top_up_result = WalletTransactionService.top_up_wallet(
                str(payment_order.user_id),
                top_up_amount,
                payment_refferance={
                    'payment_order_id': str(payment_order.id),
                    'provider_charge_id': provider_charge_id,
                    'topic': topic,
                    'note': 'Wallet top-up via Shopify one-time charge',
                },
            )
            if top_up_result is not True:
                payment_order.status = PaymentOrder.Status.APPROVED
                payment_order.approved_at = payment_order.approved_at or now_value
                payment_order.failure_reason = str(top_up_result)
                payment_order.save(
                    update_fields=['status', 'approved_at', 'failure_reason', 'updated_at']
                )
                raise ShopifyPaymentError(
                    f'Failed to top up wallet for payment order {payment_order.id}: {top_up_result}'
                )

            payment_order.status = PaymentOrder.Status.SETTLED
            payment_order.approved_at = payment_order.approved_at or now_value
            payment_order.settled_at = now_value
            payment_order.failure_reason = ''
            payment_order.save(
                update_fields=['status', 'approved_at', 'settled_at', 'failure_reason', 'updated_at']
            )
            return PaymentOrderService._finalize_webhook_event(
                webhook_event,
                {
                    'status': 'settled',
                    'provider_charge_id': provider_charge_id,
                    'payment_order_id': str(payment_order.id),
                    'credited_amount': top_up_amount,
                },
                payload=payload,
                topic=topic,
                external_event_id=external_event_id,
            )

        mapped_status = PaymentOrderService.FINAL_WEBHOOK_STATUSES.get(
            normalized_status,
            PaymentOrder.Status.FAILED,
        )
        payment_order.status = mapped_status
        payment_order.failure_reason = f'Shopify one-time charge moved to {normalized_status.lower()}.'
        payment_order.save(update_fields=['status', 'failure_reason', 'updated_at'])
        return PaymentOrderService._finalize_webhook_event(
            webhook_event,
            {
                'status': normalized_status.lower(),
                'provider_charge_id': provider_charge_id,
                'payment_order_id': str(payment_order.id),
            },
            payload=payload,
            topic=topic,
            external_event_id=external_event_id,
        )

    @staticmethod
    def build_payload_hash(raw_body: bytes) -> str:
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    def extract_provider_charge_id(payload: dict) -> str:
        if not isinstance(payload, dict):
            return ''

        direct_id = str(
            payload.get('admin_graphql_api_id')
            or payload.get('id')
            or ''
        ).strip()
        if direct_id:
            return direct_id

        nested_purchase = payload.get('app_purchase_one_time') or payload.get('appPurchaseOneTime') or {}
        return str(
            nested_purchase.get('admin_graphql_api_id')
            or nested_purchase.get('id')
            or ''
        ).strip()

    @staticmethod
    def extract_purchase_status(payload: dict) -> str:
        if not isinstance(payload, dict):
            return ''

        direct_status = str(payload.get('status') or '').strip()
        if direct_status:
            return direct_status

        nested_purchase = payload.get('app_purchase_one_time') or payload.get('appPurchaseOneTime') or {}
        return str(nested_purchase.get('status') or '').strip()

    @staticmethod
    def get_payment_order_for_charge(*, shopify_profile, provider_charge_id: str):
        payment_orders = PaymentOrder.objects.select_for_update().filter(user=shopify_profile.user)
        payment_order = payment_orders.filter(provider_charge_id=provider_charge_id).first()
        if payment_order is not None:
            return payment_order

        if provider_charge_id.startswith('gid://'):
            charge_tail = provider_charge_id.rsplit('/', 1)[-1]
            return payment_orders.filter(provider_charge_id__endswith=f'/{charge_tail}').first()

        return payment_orders.filter(provider_charge_id__endswith=f'/{provider_charge_id}').first()

    @staticmethod
    def get_credit_amount(payment_order: PaymentOrder) -> int:
        credit_amount = payment_order.credits_snapshot.get('amount')
        if credit_amount in (None, ''):
            credit_amount = payment_order.package.sms_count
        return int(credit_amount)

    @staticmethod
    def _finalize_webhook_event(
        webhook_event: WebhookEvent,
        result: dict,
        *,
        payload: dict,
        topic: str,
        external_event_id: str,
    ) -> dict:
        webhook_event.topic = topic
        webhook_event.shop_domain = webhook_event.shop_domain or ''
        webhook_event.external_event_id = external_event_id
        webhook_event.payload = payload
        webhook_event.processing_result = result
        webhook_event.processed_at = timezone.now()
        webhook_event.save(
            update_fields=['topic', 'external_event_id', 'payload', 'processing_result', 'processed_at']
        )
        return result