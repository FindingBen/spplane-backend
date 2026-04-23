from .views import SmsEventViewSet
from .views import SmsRecipientViewSet
from .views import SmsPageActionViewSet
from .views import SmsPageViewSet
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import SmsViewSet

router = DefaultRouter()
router.register(r'v1', SmsViewSet, basename='smses')

router.register(r'sms-pages', SmsPageViewSet, basename='sms_pages')

router.register(r'sms-page-actions', SmsPageActionViewSet, basename='sms_page_actions')

router.register(r'sms-recipients', SmsRecipientViewSet, basename='sms_recipients')

router.register(r'sms-events', SmsEventViewSet, basename='sms_events')

urlpatterns = [
    path('', include(router.urls)),
]