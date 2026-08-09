from .views import SmsEventViewSet,SmsPageActionViewSet,SmsViewSet,VonageDeliveryWebhookView,PublicSmsPageView,SmsRecipientViewSet,SmsPageViewSet,QrCodeViewset
from django.urls import include, path
from rest_framework.routers import DefaultRouter
router = DefaultRouter()
router.register(r'v1', SmsViewSet, basename='smses')

router.register(r'sms-pages', SmsPageViewSet, basename='sms_pages')

router.register(r'sms-page-actions', SmsPageActionViewSet, basename='sms_page_actions')

router.register(r'sms-recipients', SmsRecipientViewSet, basename='sms_recipients')

router.register(r'sms-events', SmsEventViewSet, basename='sms_events')


urlpatterns = [
    path('', include(router.urls)),
    path('sms-page-signup/', QrCodeViewset.as_view(), name='sms_page_signup'),
    path('public/page/<slug:slug>/', PublicSmsPageView.as_view(), name='sms_public_page'),
    path('delivery', VonageDeliveryWebhookView.as_view(), name='vonage_delivery_webhook'),
]