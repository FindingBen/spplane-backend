from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from apps.sms.apis.views import VonageDeliveryWebhookView
from apps.accounts.apis.views import ShopifyOAuthInitView, ShopifyOAuthCallbackView
from django.conf.urls.static import static
from django.conf import settings

def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('', health_check),
    path('health/', health_check),
    path('admin/', admin.site.urls),
    path('api/accounts/', include('apps.accounts.apis.urls')),
    path('api/shopify/', include('apps.shopify.apis.urls')),
    path('api/content/', include('apps.content.apis.urls')),
    path('api/campaign/', include('apps.campaign.apis.urls')),
    path('api/contacts/', include('apps.contacts.apis.urls')),
    path('api/sms/', include('apps.sms.apis.urls')),
    path('sms/delivery', VonageDeliveryWebhookView.as_view(), name='vonage_delivery_webhook'),

    # Legacy Shopify Partner dashboard URLs (keep until dashboard is updated)
    path('api/oAuth-login', ShopifyOAuthInitView.as_view(), name='shopify_oauth_legacy'),
    path('api/oAuth-callback', ShopifyOAuthCallbackView.as_view(), name='shopify_callback_legacy'),
]


urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)