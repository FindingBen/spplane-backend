from django.contrib import admin
from django.urls import path, include
from apps.sms.apis.views import VonageDeliveryWebhookView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('apps.accounts.apis.urls')),
    path('api/content/', include('apps.content.apis.urls')),
    path('api/campaign/', include('apps.campaign.apis.urls')),
    path('api/contacts/', include('apps.contacts.apis.urls')),
    path('api/sms/', include('apps.sms.apis.urls')),
    path('sms/delivery', VonageDeliveryWebhookView.as_view(), name='vonage_delivery_webhook'),
]
