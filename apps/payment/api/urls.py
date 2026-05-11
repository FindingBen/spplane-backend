from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payment.api.views import (
	ShopifyBillingCheckViewSet,
	ShopifyOneTimeChargeViewSet,
	ShopifyOneTimeChargeWebhookView,
)


router = DefaultRouter()
router.register(r'v1/one-time-charges', ShopifyOneTimeChargeViewSet, basename='payment_one_time_charges')
router.register(r'v1/billing-status', ShopifyBillingCheckViewSet, basename='payment_billing_status')


urlpatterns = [
	path('shopify/one_time_charge', ShopifyOneTimeChargeWebhookView.as_view(), name='shopify_one_time_charge_webhook'),
	path('shopify/one_time_charge/', ShopifyOneTimeChargeWebhookView.as_view(), name='shopify_one_time_charge_webhook_slash'),
	path('', include(router.urls)),
]
