import base64
import hashlib
import hmac
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ShopifyProfile
from apps.shopify.apis.serializers import (
    ShopifyCustomerListQuerySerializer,
    ShopifyProductListQuerySerializer,
)
from apps.shopify.service import (
    ShopifyCustomerImportStateError,
    ShopifyCustomerService,
    ShopifyGraphQLError,
    ShopifyProductImportStateError,
    ShopifyProductService,
)


IMPORT_ALREADY_COMPLETED_MESSAGE = "Customers can be imported only once. Contact support for more info."
logger = logging.getLogger(__name__)


def _verify_shopify_webhook_hmac(raw_body: bytes, received_hmac: str) -> bool:
    secret = settings.SHOPIFY_API_SECRET
    if not secret or not received_hmac:
        return False

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected_hmac = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_hmac, received_hmac)


def _handle_product_webhook(request, *, log_prefix: str, handler):
    raw_body = request.body
    shop_domain = request.headers.get("X-Shopify-Shop-Domain", "").strip().lower()
    received_hmac = request.headers.get("X-Shopify-Hmac-Sha256", "").strip()

    if not _verify_shopify_webhook_hmac(raw_body, received_hmac):
        logger.warning("%s: invalid HMAC for shop %s", log_prefix, shop_domain or "<missing>")
        return Response({"error": "Invalid HMAC signature."}, status=status.HTTP_401_UNAUTHORIZED)

    if not shop_domain:
        logger.warning("%s: missing shop domain header.", log_prefix)
        return Response(status=status.HTTP_200_OK)

    shopify_profile = ShopifyProfile.objects.filter(shop_domain__iexact=shop_domain).first()
    if shopify_profile is None:
        logger.warning("%s: unknown shop %s", log_prefix, shop_domain)
        return Response(status=status.HTTP_200_OK)

    try:
        payload = handler(shopify_profile, request.data)
    except ValueError:
        logger.warning("%s: missing product id for %s", log_prefix, shop_domain)
        return Response(status=status.HTTP_200_OK)
    except ShopifyGraphQLError:
        logger.exception("%s: failed to sync product for %s", log_prefix, shop_domain)
        return Response(status=status.HTTP_200_OK)

    return Response(payload, status=status.HTTP_200_OK)


class ShopifyCustomerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ShopifyCustomerListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {"error": "Shopify store is not connected for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if shopify_profile.first_time_import_customers:
            return Response(
                {"error": IMPORT_ALREADY_COMPLETED_MESSAGE},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = ShopifyCustomerService.fetch_customers(
                shopify_profile,
                search_query=serializer.validated_data["search"],
                cursor=serializer.validated_data["cursor"],
                first=serializer.validated_data["first"],
                reverse=serializer.validated_data["reverse"],
            )
        except ShopifyGraphQLError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload, status=status.HTTP_200_OK)


class ShopifyCustomerImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {"error": "Shopify store is not connected for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = ShopifyCustomerService.import_customers(
                shopify_profile,
                user=request.user,
            )
        except ShopifyCustomerImportStateError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ShopifyGraphQLError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload, status=status.HTTP_200_OK)


class ShopifyProductListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ShopifyProductListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {"error": "Shopify store is not connected for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = ShopifyProductService.list_products(
            shopify_profile,
            search_query=serializer.validated_data["search"],
            first=serializer.validated_data["first"],
        )
        return Response(payload, status=status.HTTP_200_OK)


class ShopifyProductImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {"error": "Shopify store is not connected for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = ShopifyProductService.import_products(shopify_profile)
        except ShopifyProductImportStateError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ShopifyGraphQLError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload, status=status.HTTP_200_OK)


class ShopifyProductCreateWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        return _handle_product_webhook(
            request,
            log_prefix="ShopifyProductCreateWebhook",
            handler=ShopifyProductService.sync_product_from_webhook,
        )


class ShopifyProductUpdateWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        return _handle_product_webhook(
            request,
            log_prefix="ShopifyProductUpdateWebhook",
            handler=ShopifyProductService.sync_product_from_webhook,
        )


class ShopifyProductDeleteWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        return _handle_product_webhook(
            request,
            log_prefix="ShopifyProductDeleteWebhook",
            handler=ShopifyProductService.delete_product_from_webhook,
        )


