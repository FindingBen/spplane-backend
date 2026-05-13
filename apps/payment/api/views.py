import base64
import hashlib
import hmac
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ShopifyProfile
from apps.payment.api.serializers import SmsPackageListSerializer, ShopifyOneTimeChargeSerializer
from apps.payment.models import PaymentOrder, SmsPackage
from apps.payment.service import (
    PaymentOrderService,
    SmsPackageService,
    ShopifyBillingStateService,
    ShopifyOneTimePaymentService,
    ShopifyPaymentError,
)
from apps.shopify.service import ShopifyGraphQLError


logger = logging.getLogger(__name__)


def _verify_shopify_webhook_hmac(raw_body: bytes, received_hmac: str) -> bool:
    secret = settings.SHOPIFY_API_SECRET
    if not secret or not received_hmac:
        return False

    digest = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).digest()
    expected_hmac = base64.b64encode(digest).decode('utf-8')
    return hmac.compare_digest(expected_hmac, received_hmac)


class ShopifyOneTimeChargeViewSet(viewsets.GenericViewSet):
    serializer_class = ShopifyOneTimeChargeSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *_args, **_kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment_order = None

        shopify_profile = (
            ShopifyProfile.objects
            .select_related('billing_state')
            .filter(user=request.user)
            .first()
        )
        if shopify_profile is None:
            return Response(
                {'error': 'Shopify store is not connected for this user.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            _, eligibility = ShopifyBillingStateService.sync_billing_state(shopify_profile)
            if not eligibility.is_allowed:
                return Response({'error': eligibility.reason}, status=status.HTTP_400_BAD_REQUEST)

            package = SmsPackageService.resolve_active_package(
                shopify_profile=shopify_profile,
                package_identifier=serializer.validated_data['package_id'],
            )
            if package is None:
                return Response(
                    {
                        'error': (
                            'SMS package was not found for this Shopify store. '
                            'Use the local package UUID or the configured external package key.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            payment_order = PaymentOrderService.create_pending_one_time_order(
                user=request.user,
                package=package,
                eligibility=eligibility,
            )

            payload = ShopifyOneTimePaymentService.create_one_time_charge(
                shopify_profile,
                {
                    'amount': package.price,
                    'currency_code': package.currency,
                    'description': serializer.validated_data.get('description') or package.name,
                    'test': serializer.validated_data.get('test', False),
                },
            )
            PaymentOrderService.attach_shopify_charge(payment_order, payload)
        except ValidationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ShopifyGraphQLError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except ShopifyPaymentError as exc:
            if payment_order is not None and not payment_order.provider_charge_id:
                payment_order.status = PaymentOrder.Status.FAILED
                payment_order.failure_reason = str(exc)
                payment_order.save(update_fields=['status', 'failure_reason', 'updated_at'])
            response_status = (
                status.HTTP_502_BAD_GATEWAY
                if isinstance(exc.__cause__, ShopifyGraphQLError)
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({'error': str(exc)}, status=response_status)

        payload['payment_order_id'] = str(payment_order.id)
        payload['return_token'] = str(payment_order.return_token)
        return Response(payload, status=status.HTTP_201_CREATED)


class SmsPackageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SmsPackageListSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        shopify_profile = (
            ShopifyProfile.objects
            .filter(user=self.request.user)
            .first()
        )
        if shopify_profile is None:
            return SmsPackage.objects.none()

        return (
            SmsPackageService
            .get_available_packages_queryset(shopify_profile=shopify_profile)
            .order_by('price', 'name')
        )

    def list(self, request, *_args, **_kwargs):
        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {'error': 'Shopify store is not connected for this user.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class ShopifyBillingCheckViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request, *_args, **_kwargs):
        shopify_profile = (
            ShopifyProfile.objects
            .select_related('billing_state')
            .filter(user=request.user)
            .first()
        )
        if shopify_profile is None:
            return Response(
                {'error': 'Shopify store is not connected for this user.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            billing_state, eligibility = ShopifyBillingStateService.sync_billing_state(shopify_profile)
        except ShopifyGraphQLError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                'is_billable': eligibility.is_allowed,
                'code': eligibility.code,
                'reason': eligibility.reason,
                'plan_public_name': billing_state.plan_public_name,
                'partner_development': billing_state.partner_development,
                'shopify_plus': billing_state.shopify_plus,
                'checked_at': billing_state.checked_at.isoformat(),
            }
        )


class ShopifyOneTimeChargeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw_body = request.body
        shop_domain = request.headers.get('X-Shopify-Shop-Domain', '').strip().lower()
        received_hmac = request.headers.get('X-Shopify-Hmac-Sha256', '').strip()
        topic = request.headers.get('X-Shopify-Topic', '').strip() or 'app_purchases_one_time/update'
        external_event_id = request.headers.get('X-Shopify-Webhook-Id', '').strip()

        if not _verify_shopify_webhook_hmac(raw_body, received_hmac):
            logger.warning(
                'ShopifyOneTimeChargeWebhook: invalid HMAC for shop %s',
                shop_domain or '<missing>',
            )
            return Response({'error': 'Invalid HMAC signature.'}, status=status.HTTP_401_UNAUTHORIZED)

        if not shop_domain:
            logger.warning('ShopifyOneTimeChargeWebhook: missing shop domain header.')
            return Response(status=status.HTTP_200_OK)

        shopify_profile = ShopifyProfile.objects.filter(shop_domain__iexact=shop_domain).first()
        if shopify_profile is None:
            logger.warning('ShopifyOneTimeChargeWebhook: unknown shop %s', shop_domain)
            return Response(status=status.HTTP_200_OK)

        try:
            payload = PaymentOrderService.handle_one_time_charge_webhook(
                shopify_profile=shopify_profile,
                payload=request.data,
                topic=topic,
                external_event_id=external_event_id,
                payload_hash=PaymentOrderService.build_payload_hash(raw_body),
            )
        except ShopifyPaymentError:
            logger.exception(
                'ShopifyOneTimeChargeWebhook: failed to settle charge for shop %s',
                shop_domain,
            )
            return Response(status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(payload, status=status.HTTP_200_OK)