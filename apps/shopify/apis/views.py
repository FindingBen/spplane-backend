from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ShopifyProfile
from apps.shopify.apis.serializers import (
    ShopifyCustomerImportSerializer,
    ShopifyCustomerListQuerySerializer,
)
from apps.shopify.service import ShopifyCustomerService, ShopifyGraphQLError


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
        serializer = ShopifyCustomerImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shopify_profile = ShopifyProfile.objects.filter(user=request.user).first()
        if shopify_profile is None:
            return Response(
                {"error": "Shopify store is not connected for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = ShopifyCustomerService.import_customers(
            shopify_profile,
            user=request.user,
            customers=serializer.validated_data["customers"],
            segment_ids=serializer.validated_data.get("segment_ids") or [],
            contact_list=serializer.validated_data.get("contact_list"),
        )
        return Response(payload, status=status.HTTP_200_OK)
