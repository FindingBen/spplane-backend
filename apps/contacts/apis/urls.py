from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ContactListViewSet, ContactViewSet,QRContactViewset

router = DefaultRouter()
router.register(r'v1', ContactListViewSet, basename='contact_lists')
router.register(r'audience/v1', ContactViewSet, basename='contacts')
router.register(r'sms-optin/v1', QRContactViewset, basename='sms-optin')

urlpatterns = [
    path('', include(router.urls)),
]
